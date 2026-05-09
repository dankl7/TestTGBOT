import logging
from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import settings
from integrations.wol_api import wol_api_client
from database.session import async_session_maker
from database.repositories.catalog import catalog_repository
from services.redis_store import redis_store
from utils.text import escape_html
from utils.price_formatter import format_price

logger = logging.getLogger(__name__)
router = Router()


def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь администратором."""
    return user_id in settings.admin_user_ids


@router.message(Command("catalog"))
async def cmd_catalog(message: Message):
    """
    Обработчик команды /catalog и кнопки '🗂 Каталог'.
    Показывает доступные категории товаров из Window of Light API.
    """
    try:
        categories = await wol_api_client.get_categories()
        if not categories:
            await message.answer("Каталог временно недоступен.")
            return

        text = "🗂 <b>Доступные категории:</b>\n\n"
        for cat in categories:
            # Пропускаем неактивные категории, если такой флаг есть и он false
            if not cat.get("is_active", True):
                continue

            name = cat.get("name", "Без названия")
            cat_id = cat.get("id", "")

            text += f"• <b>{escape_html(name)}</b> (<code>{escape_html(cat_id)}</code>)\n"

        text += "\n<i>Вы можете использовать эти названия в поиске.</i>\n"
        text += "Также вы можете написать <code>последние товары</code> для просмотра новинок."

        await message.answer(text)
    except Exception as e:
        logger.error(f"Catalog fetch error: {e}")
        await message.answer("Не удалось загрузить каталог.")


@router.message(F.text.lower() == "последние товары")
async def cmd_latest_products(message: Message):
    wait_msg = await message.answer("⏳ <i>Загружаю последние товары...</i>")
    try:
        result = await wol_api_client.search_products({"limit": 20, "offset": 0})
        if not result or not result.get("products"):
            await wait_msg.edit_text("Ничего не найдено.")
            return
        products = result.get("products", [])
        from bot.handlers.search import _build_model_text
        model_groups = {}
        model_order = []
        for p in products:
            brand = p.get("brand") or ""
            model = p.get("model") or ""
            key = (brand, model)
            if key not in model_groups:
                model_groups[key] = []
                model_order.append(key)
            model_groups[key].append(p)
        text = "🆕 <b>Последние товары:</b>\n\n"
        for brand, model in model_order:
            text += _build_model_text(brand, model, model_groups[(brand, model)]) + "\n"
        await wait_msg.edit_text(text)
        from services.cleanup import cleanup_service
        await cleanup_service.register_message(message.bot, message.chat.id, wait_msg.message_id)
    except Exception as e:
        logger.error(f"Error fetching latest products: {e}")
        await wait_msg.edit_text("Не удалось загрузить последние товары.")


@router.message(Command("db_table"))
async def cmd_db_table(message: Message, command: CommandObject):
    """
    Read-only вывод allowlist таблиц БД с лимитом. (Только для администраторов)
    """
    if not is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    if not command.args:
        await message.answer("Укажите имя таблицы. Например: <code>/db_table products</code>")
        return

    table_name = command.args.split()[0].strip()

    try:
        async with async_session_maker() as session:
            rows = await catalog_repository.browse_table(session, table_name)
    except ValueError as e:
        await message.answer(str(e))
        return
    except Exception as e:
        logger.error(f"DB Error while accessing {table_name}: {e}")
        await message.answer("Ошибка при выполнении запроса к базе данных.")
        return

    if not rows:
        await message.answer(f"Таблица <b>{escape_html(table_name)}</b> пуста.", parse_mode="HTML")
        return

    text = f"🗂 <b>Таблица: {escape_html(table_name)}</b> (Top {len(rows)})\n\n"

    for i, row in enumerate(rows, 1):
        text += f"<b>Row {i}:</b>\n"
        for k, v in row.items():
            text += f"  <i>{escape_html(k)}</i>: {escape_html(str(v))}\n"
        text += "\n"

        # Отправляем сообщение частями, если оно слишком длинное (лимит Telegram 4096 символов)
        if len(text) > 3500:
            await message.answer(text, parse_mode="HTML")
            text = ""

    if text.strip():
        await message.answer(text, parse_mode="HTML")


@router.message(Command("db_schema"))
async def cmd_db_schema(message: Message, command: CommandObject):
    """
    Вывод схемы allowlist таблицы БД. (Только для администраторов)
    """
    if not is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    if not command.args:
        await message.answer("Укажите имя таблицы. Например: <code>/db_schema products</code>")
        return

    table_name = command.args.split()[0].strip()

    try:
        async with async_session_maker() as session:
            schema = await catalog_repository.get_table_schema(session, table_name)
    except ValueError as e:
        await message.answer(str(e))
        return
    except Exception as e:
        logger.error(f"DB Error while fetching schema for {table_name}: {e}")
        await message.answer("Ошибка при получении схемы.")
        return

    if not schema:
        await message.answer(f"Таблица <b>{escape_html(table_name)}</b> не найдена или не имеет колонок.")
        return

    text = f"🛠 <b>Схема таблицы: {escape_html(table_name)}</b>\n\n"
    for col in schema:
        text += f"• <b>{escape_html(col['column_name'])}</b> (<code>{escape_html(col['data_type'])}</code>)\n"

    await message.answer(text, parse_mode="HTML")
