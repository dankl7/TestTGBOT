import logging
from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import settings
from integrations.wol_api import wol_api_client
from database.session import async_session_maker
from database.repositories.catalog import catalog_repository
from services.redis_store import redis_store
from utils.text import escape_html
from utils.price_formatter import format_price
from bot.catalog_categories import (
    CATEGORIES,
    CATEGORY_BY_KEY,
    build_where_clause,
)

logger = logging.getLogger(__name__)
router = Router()

CATALOG_MSG_LIMIT = 3500  # запас под HTML-теги до Telegram-лимита 4096


def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь администратором."""
    return user_id in settings.admin_user_ids


def _build_catalog_keyboard() -> "InlineKeyboardBuilder":
    kb = InlineKeyboardBuilder()
    for cat in CATEGORIES:
        kb.button(text=cat["label"], callback_data=f"cat:{cat['key']}")
    kb.adjust(2)
    return kb


@router.message(Command("catalog"))
@router.message(F.text == "🗂 Каталог")
async def cmd_catalog(message: Message):
    """Кнопка «Каталог» — выводит inline-меню категорий."""
    kb = _build_catalog_keyboard()
    await message.answer(
        "🗂 <b>Каталог</b>\n\n"
        "Выберите категорию, чтобы увидеть все товары из двух каналов:",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.startswith("cat:"))
async def cb_catalog_category(callback: CallbackQuery):
    """Клик по категории — выводит все товары сравнительными таблицами."""
    await callback.answer()
    key = (callback.data or "").split(":", 1)[1] if callback.data else ""
    cat = CATEGORY_BY_KEY.get(key)
    if not cat:
        await callback.message.answer("Неизвестная категория.")
        return

    where, params = build_where_clause(cat)
    try:
        async with async_session_maker() as session:
            products = await catalog_repository.get_products_by_filter(
                session, where, params, limit=2000,
            )
    except Exception as e:
        logger.error(f"Catalog query failed for {key}: {e}")
        await callback.message.answer("Ошибка при загрузке каталога. Попробуйте позже.")
        return

    if not products:
        await callback.message.answer(
            f"В категории <b>{escape_html(cat['label'])}</b> пока нет товаров."
        )
        return

    from bot.handlers.search import (
        _index_variants,
        _build_table_text,
        CHANNEL_PRIORITY,
        canonical_channel,
    )

    # Канонизируем source_channel: в БД одна и та же группа Telegram-канала
    # хранится в двух формах ("1887497207" и "-1001887497207"). Сводим к одной,
    # иначе сравнительная таблица показывала бы две колонки одного и того же канала.
    for p in products:
        p["source_channel"] = canonical_channel(p.get("source_channel"))

    # Группируем по (brand, model), в том же порядке что и SQL ORDER BY.
    groups: dict = {}
    order: list = []
    for p in products:
        key2 = (p.get("brand") or "", p.get("model") or "")
        if key2 not in groups:
            groups[key2] = []
            order.append(key2)
        groups[key2].append(p)

    header = f"🗂 <b>{escape_html(cat['label'])}</b>  —  {len(products)} тов.\n\n"
    chunks: list = [header]

    for (brand, model) in order:
        items = groups[(brand, model)]
        variant_order, variants, channels_seen = _index_variants(items)
        # Сортируем каналы по приоритету, но НЕ добавляем фиктивные: показываем только реальные.
        channels_seen.sort(key=lambda ch: CHANNEL_PRIORITY.get(ch, 99))
        ch_best = channels_seen[0] if channels_seen else "?"
        ch_top = channels_seen[1] if len(channels_seen) >= 2 else None

        cat_emoji = {
            "smartphones": "📱", "laptops": "💻", "tablets": "📲",
            "consoles": "🎮", "accessories": "🎧",
        }.get(items[0].get("category_id") or "", "📦")

        block = _build_table_text(cat_emoji, model, variant_order, variants, ch_best, ch_top)

        # Если блок сам по себе больше лимита — отправляем отдельным сообщением.
        if len(block) > CATALOG_MSG_LIMIT:
            if chunks[-1].strip():
                chunks.append("")
            chunks.append(block)
            chunks.append("")
            continue
        # Иначе — прилепляем к текущему chunk, открывая новый при переполнении.
        if len(chunks[-1]) + len(block) + 2 > CATALOG_MSG_LIMIT:
            chunks.append("")
        chunks[-1] = chunks[-1] + (block if not chunks[-1] else "\n\n" + block)

    for chunk in chunks:
        if not chunk.strip():
            continue
        await callback.message.answer(chunk)


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
