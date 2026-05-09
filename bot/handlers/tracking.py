import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.redis_store import redis_store
from integrations.wol_api import wol_api_client
from database.session import async_session_maker
from database.repositories.tracked import tracked_repository
from utils.price_formatter import format_price
from utils.text import escape_html

logger = logging.getLogger(__name__)
router = Router()


async def _render_tracked_message(message: Message, user_id: int):
    """
    Вспомогательная функция для рендеринга списка отслеживаемых товаров.
    Позволяет переиспользовать код для обновления сообщения при удалении.
    """
    async with async_session_maker() as session:
        trackings = await tracked_repository.get_user_tracked_products(session, user_id)

    if not trackings:
        text = (
            "Вы пока ничего не отслеживаете.\n"
            "Нажмите «🔔 Отслеживать» под любым товаром в результатах поиска, чтобы добавить его сюда."
        )
        try:
            if message.text != text and message.html_text != text:
                await message.edit_text(text, reply_markup=None)
        except Exception:
            # Если сообщение не редактируется (например, было отправлено как новое)
            pass
        return

    text = "🔔 <b>Ваши отслеживаемые товары:</b>\n\n"
    builder = InlineKeyboardBuilder()

    for i, (tracked, product) in enumerate(trackings, start=1):
        title = f"{product.brand or ''} {product.model or ''}".strip()
        price_str = format_price(tracked.last_seen_price)

        text += f"<b>{i}.</b> {escape_html(title)}\n"
        text += f"Текущая цена: <b>{price_str}</b>\n\n"

        builder.button(text=f"❌ Откл. {i}", callback_data=f"ut:{tracked.id}")

    builder.adjust(3)

    try:
        if message.text != text and message.html_text != text:
            await message.edit_text(text, reply_markup=builder.as_markup())
    except Exception:
        pass


@router.message(Command("tracked"))
@router.message(F.text == "🔔 Отслеживаемые")
async def cmd_tracked(message: Message):
    """
    Обработчик команды /tracked и кнопки "🔔 Отслеживаемые".
    Выводит список активных отслеживаний пользователя.
    """
    try:
        await message.delete()
    except Exception:
        pass
    async with async_session_maker() as session:
        trackings = await tracked_repository.get_user_tracked_products(session, message.from_user.id)

    if not trackings:
        await message.answer(
            "Вы пока ничего не отслеживаете.\n"
            "Нажмите «🔔 Отслеживать» под любым товаром в результатах поиска, чтобы добавить его сюда."
        )
        return

    text = "🔔 <b>Ваши отслеживаемые товары:</b>\n\n"
    builder = InlineKeyboardBuilder()

    for i, (tracked, product) in enumerate(trackings, start=1):
        title = f"{product.brand or ''} {product.model or ''}".strip()
        price_str = format_price(tracked.last_seen_price)

        text += f"<b>{i}.</b> {escape_html(title)}\n"
        text += f"Текущая цена: <b>{price_str}</b>\n\n"

        builder.button(text=f"❌ Откл. {i}", callback_data=f"ut:{tracked.id}")

    # Размещаем по 3 кнопки в ряд
    builder.adjust(3)

    await message.answer(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("t:"))
async def process_track_callback(callback: CallbackQuery):
    """
    Обрабатывает нажатие на кнопку "🔔 Отслеживать" под товаром.
    """
    parts = callback.data.split(":")
    if len(parts) < 2:
        await callback.answer("Ошибка: неверный код товара.", show_alert=True)
        return

    short_id = parts[1]
    full_id = await redis_store.get_full_id(short_id)

    if not full_id:
        await callback.answer("Товар устарел. Пожалуйста, выполните поиск заново.", show_alert=True)
        return

    product_data = await wol_api_client.get_product(full_id)
    if not product_data:
        await callback.answer("Не удалось получить актуальные данные о товаре.", show_alert=True)
        return

    current_price = product_data.get("price")
    if current_price is None:
        await callback.answer("Невозможно отслеживать товар без указанной цены.", show_alert=True)
        return

    try:
        async with async_session_maker() as session:
            await tracked_repository.add_or_update_tracking(
                session=session,
                user_id=callback.from_user.id,
                product_id=full_id,
                current_price=float(current_price)
            )
        await callback.answer("✅ Товар успешно добавлен в отслеживаемые!", show_alert=True)
    except Exception as e:
        logger.error(f"Error tracking product {full_id} for user {callback.from_user.id}: {e}")
        await callback.answer("Произошла ошибка при добавлении товара. Попробуйте позже.", show_alert=True)


@router.callback_query(F.data.startswith("ut:"))
async def process_untrack_callback(callback: CallbackQuery):
    """
    Обрабатывает нажатие на кнопку отключения отслеживания ("❌ Откл.").
    """
    parts = callback.data.split(":")
    if len(parts) < 2:
        await callback.answer("Ошибка: неверный ID отслеживания.", show_alert=True)
        return

    try:
        tracked_id = int(parts[1])
    except ValueError:
        await callback.answer("Ошибка: некорректный ID отслеживания.", show_alert=True)
        return

    try:
        async with async_session_maker() as session:
            success = await tracked_repository.deactivate_tracking(
                session=session,
                user_id=callback.from_user.id,
                tracked_id=tracked_id
            )

        if success:
            await callback.answer("❌ Отслеживание успешно отключено.", show_alert=False)
            # Обновляем сообщение со списком
            await _render_tracked_message(callback.message, callback.from_user.id)
        else:
            await callback.answer("Не удалось отключить. Возможно, отслеживание уже было отключено.", show_alert=True)
    except Exception as e:
        logger.error(f"Error untracking ID {tracked_id} for user {callback.from_user.id}: {e}")
        await callback.answer("Произошла ошибка.", show_alert=True)


@router.callback_query(F.data.startswith("ph:"))
async def process_price_history(callback: CallbackQuery):
    """
    Обрабатывает нажатие на кнопку "📊 История цен" под товаром.
    """
    parts = callback.data.split(":")
    if len(parts) < 2:
        await callback.answer("Ошибка: неверный код товара.", show_alert=True)
        return

    short_id = parts[1]
    full_id = await redis_store.get_full_id(short_id)

    if not full_id:
        await callback.answer("Товар устарел. Пожалуйста, выполните поиск заново.", show_alert=True)
        return

    # Запрашиваем информацию о самом товаре для названия и текущей цены
    product_data = await wol_api_client.get_product(full_id)
    if not product_data:
        await callback.answer("Не удалось получить данные о товаре.", show_alert=True)
        return

    history_data = await wol_api_client.get_product_history(full_id)

    # Универсальное извлечение списка истории
    history_list = []
    if isinstance(history_data, list):
        history_list = history_data
    elif isinstance(history_data, dict):
        for key in ["history", "items", "data", "records", "price_history"]:
            if key in history_data and isinstance(history_data[key], list):
                history_list = history_data[key]
                break

    # Если истории нет
    if not history_list:
        current_price = product_data.get("price")
        text = (
            "История цен пока отсутствует.\n"
            f"Текущая цена: <b>{format_price(current_price)}</b>"
        )
        await callback.message.answer(text)
        await callback.answer()
        return

    # Извлекаем и парсим записи
    records = []
    for item in history_list:
        try:
            ts_str = item["timestamp"].replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts_str)
            price = float(item["price"])
            records.append((dt, price))
        except (ValueError, KeyError, TypeError):
            continue

    if not records:
        current_price = product_data.get("price")
        text = (
            "История цен пока отсутствует.\n"
            f"Текущая цена: <b>{format_price(current_price)}</b>"
        )
        await callback.message.answer(text)
        await callback.answer()
        return

    # Сортируем по времени (от старых к новым) для вычисления процентов
    records.sort(key=lambda x: x[0])

    min_price = min(r[1] for r in records)
    max_price = max(r[1] for r in records)

    formatted_records = []
    for i in range(len(records)):
        dt, price = records[i]
        date_str = dt.strftime("%d.%m")

        if i == 0:
            change_str = ""
        else:
            prev_price = records[i - 1][1]
            if prev_price == 0:
                change_str = ""
            elif price == prev_price:
                change_str = " (→ без изменений)"
            else:
                pct = ((price - prev_price) / prev_price) * 100
                if pct > 0:
                    change_str = f" (↑ +{pct:.1f}%)"
                else:
                    change_str = f" (↓ {pct:.1f}%)"

        formatted_records.append(f"📅 {date_str} — {format_price(price)}{change_str}")

    # Переворачиваем список, чтобы новые записи были сверху, и берем последние 7
    display_records = list(reversed(formatted_records))[:7]

    title = f"{product_data.get('brand', '')} {product_data.get('model', '')}".strip()

    text = f"📊 <b>История цен: {escape_html(title)}</b>\n"
    text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    text += "\n".join(display_records)
    text += f"\n\nМин: {format_price(min_price)}  |  Макс: {format_price(max_price)}"

    await callback.message.answer(text)
    await callback.answer()
