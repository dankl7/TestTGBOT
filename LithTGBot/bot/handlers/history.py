import logging
import asyncio
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.session import async_session_maker
from database.repositories.history import history_repository
from integrations.wol_api import wol_api_client
from utils.price_formatter import format_price
from utils.text import escape_html
from services.cleanup import cleanup_service

logger = logging.getLogger(__name__)
router = Router()


async def _show_history(message: Message, user_id: int, edit: bool = False):
    """
    Получает историю запросов пользователя, актуализирует цены
    и выводит в виде списка с кнопками.
    """
    async with async_session_maker() as session:
        records = list(await history_repository.get_user_history(session, user_id, limit=20))

    if not records:
        text = "Ваша история поиска пуста."
        try:
            if edit:
                await message.edit_text(text, reply_markup=None)
            else:
                await message.answer(text)
        except Exception:
            pass
        return

    text = "📜 <b>История поиска</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    builder = InlineKeyboardBuilder()

    # Собираем запросы к API для актуализации цен параллельно
    tasks = []
    for r in records:
        if r.product_id:
            tasks.append(wol_api_client.get_product(str(r.product_id)))
        else:
            # Пустая корутина для сохранения порядка, если это просто поиск без товара
            async def dummy(): return None
            tasks.append(dummy())

    products = await asyncio.gather(*tasks, return_exceptions=True)

    for i, (record, product) in enumerate(zip(records, products), start=1):
        query_text = record.normalized_query or record.query
        date_str = record.created_at.strftime("%d.%m.%Y")

        if record.product_id:
            if isinstance(product, dict) and "price" in product:
                price_str = f"{format_price(product['price'])} (акт.)"
            else:
                price_str = "товар недоступен"
        else:
            if record.final_price:
                price_str = f"{format_price(record.final_price)} (сохр.)"
            else:
                price_str = f"Найдено: {record.results_count}"

        text += f"<b>{i}.</b> {escape_html(query_text)}\n"
        text += f"   {escape_html(price_str)} • {date_str}\n\n"

        builder.button(text=f"🔄 Повт. {i}", callback_data=f"r:{record.id}")
        builder.button(text=f"❌ Удал. {i}", callback_data=f"hd:{record.id}")

    # Размещаем по 2 кнопки в ряд: [Повторить N] [Удалить N]
    builder.adjust(2)

    try:
        if edit:
            if message.text != text and message.html_text != text:
                await message.edit_text(text, reply_markup=builder.as_markup())
        else:
            await message.answer(text, reply_markup=builder.as_markup())
    except Exception as e:
        logger.error(f"Error showing history for user {user_id}: {e}")


@router.message(Command("history"))
@router.message(F.text == "📜 История")
async def cmd_history(message: Message):
    """
    Обработчик команды /history и кнопки '📜 История'.
    """
    try:
        await message.delete()
    except Exception:
        pass
    await _show_history(message, message.from_user.id)


@router.callback_query(F.data.startswith("hd:"))
async def process_delete_history(callback: CallbackQuery):
    """
    Обрабатывает удаление записи из истории.
    """
    parts = callback.data.split(":")
    if len(parts) < 2:
        await callback.answer("Ошибка: неверный ID записи.", show_alert=True)
        return

    try:
        history_id = int(parts[1])
    except ValueError:
        await callback.answer("Ошибка: некорректный ID.", show_alert=True)
        return

    try:
        async with async_session_maker() as session:
            success = await history_repository.delete_record(session, history_id, callback.from_user.id)

        if success:
            await callback.answer("✅ Запись удалена.")
            await _show_history(callback.message, callback.from_user.id, edit=True)
        else:
            await callback.answer("Ошибка при удалении или запись уже удалена.", show_alert=True)
    except Exception as e:
        logger.error(f"Error deleting history {history_id} for user {callback.from_user.id}: {e}")
        await callback.answer("Произошла ошибка.", show_alert=True)


@router.callback_query(F.data.startswith("r:"))
async def process_repeat_search(callback: CallbackQuery):
    """
    Обрабатывает повтор поискового запроса из истории.
    """
    parts = callback.data.split(":")
    if len(parts) < 2:
        await callback.answer("Ошибка: неверный ID записи.", show_alert=True)
        return

    try:
        history_id = int(parts[1])
    except ValueError:
        await callback.answer("Ошибка: некорректный ID.", show_alert=True)
        return

    try:
        async with async_session_maker() as session:
            record = await history_repository.get_record(session, history_id)

        if not record or record.user_id != callback.from_user.id:
            await callback.answer("Запись не найдена.", show_alert=True)
            return

        query = record.query
        await callback.answer("🔄 Повторяю поиск...")

        # Отложенный импорт для предотвращения циклических зависимостей
        from bot.handlers.search import build_search_response

        text, markup, token = await build_search_response(query, callback.from_user.id, 0)
        sent_msg = await callback.message.answer(text, reply_markup=markup)

        # Регистрируем новое поисковое сообщение для автоочистки
        await cleanup_service.register_message(callback.bot, callback.message.chat.id, sent_msg.message_id)

    except Exception as e:
        logger.error(f"Error repeating search for history {history_id}: {e}")
        await callback.message.answer("Произошла ошибка при выполнении поиска. Попробуйте позже.")
