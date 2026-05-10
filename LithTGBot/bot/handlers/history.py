import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.repositories.history import history_repository
from database.session import async_session_maker
from integrations.wol_api import wol_api_client
from services.cleanup import cleanup_service
from utils.price_formatter import format_price
from utils.text import escape_html

logger = logging.getLogger(__name__)
router = Router()

# Сколько последних записей показываем как отдельные карточки
HISTORY_RENDER_LIMIT = 10


def _record_keyboard(record_id: int) -> InlineKeyboardMarkup:
    """Клавиатура отдельной записи истории: повторить + удалить."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔄 Повторить", callback_data=f"r:{record_id}"),
        InlineKeyboardButton(text="❌ Удалить", callback_data=f"hd:{record_id}"),
    )
    return builder.as_markup()


def _footer_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура итогового сообщения: очистить всю историю."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🧹 Очистить всю историю",
            callback_data="hda:confirm",
        )
    )
    return builder.as_markup()


def _confirm_clear_keyboard() -> InlineKeyboardMarkup:
    """Подтверждение полной очистки истории."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, очистить", callback_data="hda:yes"),
        InlineKeyboardButton(text="✖️ Отмена", callback_data="hda:no"),
    )
    return builder.as_markup()


def _format_record_block(record, product) -> str:
    """Форматирует одну запись истории в виде компактного блока."""
    query_text = record.normalized_query or record.query
    date_str = record.created_at.strftime("%d.%m.%Y %H:%M")

    if record.product_id:
        if isinstance(product, dict) and "price" in product:
            price_str = f"{format_price(product['price'])} (актуальная)"
        else:
            price_str = "товар недоступен"
    elif record.final_price:
        price_str = f"{format_price(record.final_price)} (на момент поиска)"
    else:
        price_str = f"найдено: {record.results_count}"

    text = (
        f"🔍 <b>{escape_html(query_text)}</b>\n"
        f"<i>{escape_html(price_str)}</i> · <code>{date_str}</code>"
    )
    return text


async def _show_history(message: Message, user_id: int):
    """Отправляет историю как отдельные карточки + итоговую кнопку очистки."""
    async with async_session_maker() as session:
        records = list(
            await history_repository.get_user_history(
                session, user_id, limit=HISTORY_RENDER_LIMIT
            )
        )

    if not records:
        await message.answer("Ваша история поиска пуста.")
        return

    header_text = (
        f"📜 <b>История поиска</b>\n"
        f"<i>{len(records)} последн{_plural_records(len(records))}</i>"
    )
    await message.answer(header_text)

    # Параллельно тянем актуальные цены по тем записям, у которых есть product_id
    async def _fetch_product(rec):
        if rec.product_id:
            try:
                return await wol_api_client.get_product(str(rec.product_id))
            except Exception as e:
                logger.error(f"history: get_product failed for {rec.product_id}: {e}")
                return None
        return None

    products = await asyncio.gather(
        *[_fetch_product(r) for r in records], return_exceptions=False
    )

    for record, product in zip(records, products):
        try:
            await message.answer(
                _format_record_block(record, product),
                reply_markup=_record_keyboard(record.id),
            )
        except Exception as e:
            logger.error(f"history: failed to send record {record.id}: {e}")

    await message.answer(
        "🧹 <i>Очистить всю историю поиска?</i>",
        reply_markup=_footer_keyboard(),
    )


def _plural_records(n: int) -> str:
    """Возвращает суффикс для слова "последн<суффикс>" в зависимости от числа."""
    if n % 10 == 1 and n % 100 != 11:
        return "ий запрос"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "их запроса"
    return "их запросов"


@router.message(Command("history"))
@router.message(F.text == "📜 История")
async def cmd_history(message: Message):
    """Обработчик команды /history и кнопки '📜 История'."""
    try:
        await message.delete()
    except Exception:
        pass
    await _show_history(message, message.from_user.id)


@router.callback_query(F.data.startswith("hd:"))
async def process_delete_history(callback: CallbackQuery):
    """Удаление одной записи истории — удаляет соответствующее сообщение."""
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
            success = await history_repository.delete_record(
                session, history_id, callback.from_user.id
            )

        if not success:
            await callback.answer(
                "Запись не найдена или уже удалена.", show_alert=True
            )
            return

        await callback.answer("✅ Запись удалена")
        try:
            await callback.message.delete()
        except Exception:
            await callback.message.edit_text(
                "<i>Запись удалена.</i>", reply_markup=None
            )
    except Exception as e:
        logger.error(
            f"Error deleting history {history_id} for user "
            f"{callback.from_user.id}: {e}"
        )
        await callback.answer("Произошла ошибка.", show_alert=True)


@router.callback_query(F.data == "hda:confirm")
async def process_clear_all_confirm(callback: CallbackQuery):
    """Запрос подтверждения полной очистки истории."""
    await callback.message.edit_text(
        "❓ <b>Очистить всю историю поиска?</b>\n"
        "<i>Это действие нельзя отменить.</i>",
        reply_markup=_confirm_clear_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "hda:no")
async def process_clear_all_cancel(callback: CallbackQuery):
    """Отмена полной очистки истории."""
    await callback.message.edit_text(
        "🧹 <i>Очистить всю историю поиска?</i>",
        reply_markup=_footer_keyboard(),
    )
    await callback.answer("Отменено")


@router.callback_query(F.data == "hda:yes")
async def process_clear_all_history(callback: CallbackQuery):
    """Полная очистка истории поиска пользователя."""
    try:
        async with async_session_maker() as session:
            deleted = await history_repository.delete_all_for_user(
                session, callback.from_user.id
            )
        await callback.message.edit_text(
            f"🧹 <b>История очищена</b>\n<i>удалено записей: {deleted}</i>",
            reply_markup=None,
        )
        await callback.answer(f"Удалено: {deleted}")
    except Exception as e:
        logger.error(
            f"Error clearing history for user {callback.from_user.id}: {e}"
        )
        await callback.answer("Не удалось очистить историю.", show_alert=True)


@router.callback_query(F.data.startswith("r:"))
async def process_repeat_search(callback: CallbackQuery):
    """Повтор поискового запроса из истории."""
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

        from bot.handlers.search import build_search_response

        text, markup, _ = await build_search_response(
            query, callback.from_user.id, 0
        )
        sent_msg = await callback.message.answer(text, reply_markup=markup)

        await cleanup_service.register_message(
            callback.bot, callback.message.chat.id, sent_msg.message_id
        )
    except Exception as e:
        logger.error(
            f"Error repeating search for history {history_id}: {e}"
        )
        await callback.message.answer(
            "Произошла ошибка при выполнении поиска. Попробуйте позже."
        )
