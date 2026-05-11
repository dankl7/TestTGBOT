# bot/handlers/search.py
import json
import logging
import re
from typing import Optional

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.keyboards.product import get_product_keyboard
from integrations.wol_api import wol_api_client
from services.cleanup import cleanup_service
from services.redis_store import redis_store
from services.search import search_service
from utils.price_formatter import format_price
from utils.text import escape_html

logger = logging.getLogger(__name__)
router = Router()

MENU_TEXTS = {"🔎 Поиск", "📜 История", "🔔 Отслеживаемые", "ℹ️ Помощь", "🗂 Каталог"}

# Маппинг каналов-поставщиков (source_channel -> название).
# В БД ID каждого канала встречается в двух формах: "<id>" и "-100<id>".
CHANNEL_NAMES: dict = {
    '1887497207': 'Best Resale',  '-1001887497207': 'Best Resale',
    '1963407298': 'Top Resale',   '-1001963407298': 'Top Resale',
}

# Короткие лейблы каналов для шапки таблицы
CHANNEL_SHORT: dict = {
    '1887497207': 'Best',  '-1001887497207': 'Best',
    '1963407298': 'Top',   '-1001963407298': 'Top',
}

# Приоритет отображения каналов (меньше = левее в таблице)
CHANNEL_PRIORITY: dict = {
    '1887497207': 0,  '-1001887497207': 0,   # Best Resale — первый
    '1963407298': 1,  '-1001963407298': 1,   # Top Resale — второй
}


def canonical_channel(raw) -> str:
    """Приводит обе формы ID канала (1887497207 / -1001887497207) к одной канонической."""
    s = str(raw or "").strip()
    if s.startswith("-100") and s[4:].isdigit():
        return s[4:]
    return s

# Сколько символов отводим под колонку с ценой в монопространственной таблице
PRICE_COL_WIDTH = 8
# Сколько символов отводим под колонку с цветом
COLOR_COL_WIDTH = 18



def _model_matches_query(product_model: str, search_model: str) -> bool:
    """
    Проверяет точное совпадение модели товара с поисковым запросом.
    Предотвращает ситуации, когда 'iPhone 17 Pro' матчит 'iPhone 17 Pro Max'.
    """
    if not product_model or not search_model:
        return True
    pm = product_model.lower().strip()
    sm = search_model.lower().strip()
    if pm == sm:
        return True
    if pm.startswith(sm) and len(pm) > len(sm):
        next_char = pm[len(sm)]
        if next_char not in (" ", "-", "_", "/"):
            return False
    if sm.startswith(pm):
        return True
    pm_tokens = set(pm.split())
    sm_tokens = set(sm.split())
    if not sm_tokens.issubset(pm_tokens):
        return False
    extra = pm_tokens - sm_tokens
    return not any(
        t in ("pro", "max", "plus", "mini", "air", "ultra", "se")
        for t in extra
    )


def _storage_sort_key(storage: str) -> int:
    """Числовой ключ для сортировки объёмов памяти (256GB < 512GB < 1TB)."""
    if not storage:
        return 9999
    s = storage.upper().strip()
    m = re.match(r"(\d+)\s*(GB|TB)", s)
    if not m:
        return 9999
    num = int(m.group(1))
    return num if m.group(2) == "GB" else num * 1024


def _sim_type_sort_key(sim_type: str) -> int:
    """Ключ сортировки для типа SIM: SIM+ESIM=0, ESIM=1, прочие=2."""
    s = (sim_type or "").upper()
    if "SIM+ESIM" in s:
        return 0
    if "ESIM" in s:
        return 1
    if "SIM" in s:
        return 2
    return 3


def _ram_sort_key(ram: str) -> int:
    """Числовой ключ для сортировки объёмов RAM (8GB < 12GB < 16GB)."""
    if not ram:
        return 9999
    s = ram.upper().strip()
    m = re.match(r"(\d+)\s*(GB|TB)", s)
    if not m:
        return 9999
    num = int(m.group(1))
    return num if m.group(2) == "GB" else num * 1024


def _get_short_model(model: str) -> str:
    """
    Возвращает краткое название модели без общего префикса бренда/линейки.
    Примеры:
      "iPhone 17 Air"       -> "17 Air"
      "MacBook Air 13 M5"   -> "Air 13 M5"
      "Samsung Galaxy S26"  -> "S26"
      "Dyson HS08"          -> "HS08"
    """
    if not model:
        return model
    short = model
    for prefix in [
        "iPhone ",
        "iPad ",
        "MacBook ",
        "Apple Watch ",
        "Samsung Galaxy ",
        "Galaxy ",
        "Dyson ",
    ]:
        if short.startswith(prefix):
            short = short[len(prefix) :]
            break
    return short




def _make_storage_ram_label(storage: str, ram: str) -> str:
    """Формирует метку объёма: '256GB', '12GB/256GB', '8GB'."""
    if storage and ram:
        return f"{ram}/{storage}"
    return storage or ram or ""


def _format_price_short(price_val) -> str:
    if price_val is None:
        return "—"
    try:
        return f"{int(float(price_val)):,}".replace(",", ".")
    except (ValueError, TypeError):
        return "—"


async def _show_product_card(callback: CallbackQuery, product_id: str):
    """Показывает карточку товара по его UUID."""
    product_data = await wol_api_client.get_product(product_id)
    if not product_data:
        await callback.answer("Не удалось загрузить данные о товаре.", show_alert=True)
        return
    brand = product_data.get("brand") or ""
    model_name = product_data.get("model") or ""
    title = f"{brand} {model_name}".strip()
    price = format_price(product_data.get("price"))
    text = f"📦 <b>{escape_html(title)}</b>\n\n"
    text += f"Цена: <b>{price}</b>\n"
    attrs = product_data.get("attributes") or {}
    if attrs:
        text += "\n<b>Характеристики:</b>\n"
        attr_labels = {
            "storage": "Память", "color": "Цвет", "sim_type": "SIM",
            "flag": "Страна", "ram": "RAM", "processor": "Процессор",
            "screen_size": "Экран", "connectivity": "Связь", "version": "Версия",
        }
        for k, v in attrs.items():
            label = attr_labels.get(k, k)
            text += f"• {label}: {escape_html(str(v))}\n"

    try:
        from datetime import datetime as dt_module
        history_data = await wol_api_client.get_product_history(product_id)
        history_list = []
        if isinstance(history_data, list):
            history_list = history_data
        elif isinstance(history_data, dict):
            for key in ["history", "items", "data", "records", "price_history"]:
                if key in history_data and isinstance(history_data[key], list):
                    history_list = history_data[key]
                    break
        if history_list:
            records = []
            for item in history_list:
                try:
                    ts_str = item["timestamp"].replace("Z", "+00:00")
                    dt = dt_module.fromisoformat(ts_str)
                    p = float(item["price"])
                    records.append((dt, p))
                except (ValueError, KeyError, TypeError):
                    continue
            if records:
                records.sort(key=lambda x: x[0])
                display_records = records[-7:]
                text += "\n<b>История:</b>\n"
                for i, (dt, p) in enumerate(display_records):
                    date_str = dt.strftime("%d.%m")
                    if i > 0:
                        prev_p = display_records[i - 1][1]
                        if prev_p > 0:
                            diff = p - prev_p
                            pct = (diff / prev_p) * 100
                            if diff == 0:
                                diff_str = " →"
                            elif diff > 0:
                                diff_str = f" ↑+{pct:.1f}%"
                            else:
                                diff_str = f" ↓{pct:.1f}%"
                        else:
                            diff_str = ""
                    else:
                        diff_str = ""
                    text += f"{date_str} — {format_price(p)}{diff_str}\n"
    except Exception as e:
        logger.error(f"Error fetching price history for {product_id}: {e}")

    updated_at = None
    try:
        from database.session import async_session_maker
        from sqlalchemy import text as sql_text
        async with async_session_maker() as session:
            db_result = await session.execute(
                sql_text("SELECT updated_at FROM products WHERE id = CAST(:id AS UUID)"),
                {"id": product_id}
            )
            row = db_result.fetchone()
            if row:
                updated_at = row[0]
    except Exception as e:
        logger.error(f"Error fetching updated_at for {product_id}: {e}")
    if updated_at:
        text += f"\n<i>Обновлено: {updated_at.strftime('%d.%m.%Y %H:%M')}</i>\n"
    else:
        ts = product_data.get("timestamp")
        if ts:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                text += f"\n<i>Обновлено: {dt.strftime('%d.%m.%Y %H:%M')}</i>\n"
            except Exception:
                pass
    short_id = await redis_store.generate_short_id(product_id)
    last_search = await redis_store.redis.get(f"last_search:{callback.from_user.id}")
    back_data = f"s:{last_search}" if last_search else None
    markup = get_product_keyboard(short_id, back_data=back_data, price=price)
    try:
        await callback.message.edit_text(text, reply_markup=markup)
        await callback.answer()
    except Exception as e:
        logger.error(f"Product card error: {e}")
        await callback.answer("Ошибка при отображении товара", show_alert=True)


def _index_variants(products: list) -> tuple:
    """
    Группирует товары по (storage, sim, flag, color, ram).
    Возвращает (variant_order, variants, channels_seen).
    variants[vkey][ch] = (price, product_id) — самая дешёвая цена по каналу.
    """
    def _sort_key(p: dict) -> tuple:
        attrs = p.get("attributes") or {}
        return (
            _storage_sort_key(attrs.get("storage") or ""),
            _sim_type_sort_key(attrs.get("sim_type") or ""),
            (attrs.get("flag") or "").lower(),
            (attrs.get("color") or "").lower(),
            _ram_sort_key(attrs.get("ram") or ""),
        )

    sorted_products = sorted(products, key=_sort_key)

    channels_seen: list = []
    variants: dict = {}
    variant_order: list = []

    for p in sorted_products:
        attrs = p.get("attributes") or {}
        ch = str(p.get("source_channel") or "?")
        if ch not in channels_seen:
            channels_seen.append(ch)
        vkey = (
            attrs.get("storage") or "",
            attrs.get("sim_type") or "",
            attrs.get("flag") or "",
            attrs.get("color") or "",
            attrs.get("ram") or "",
        )
        price = p.get("price")
        pid = str(p.get("id") or "")
        if vkey not in variants:
            variant_order.append(vkey)
            variants[vkey] = {}
        existing = variants[vkey].get(ch)
        new_price = float(price) if price is not None else None
        if new_price is not None and (existing is None or existing[0] is None or new_price < existing[0]):
            variants[vkey][ch] = (new_price, pid or (existing[1] if existing else ""))
        elif existing is None and pid:
            variants[vkey][ch] = (None, pid)

    return variant_order, variants, channels_seen


def _format_price_cell(price_val, width: int = PRICE_COL_WIDTH) -> str:
    """Цена внутри монопространственной колонки. Правое выравнивание."""
    return _format_price_short(price_val).rjust(width)


def _build_table_text(
    cat_emoji: str,
    model: str,
    variant_order: list,
    variants: dict,
    ch_best: str,
    ch_top: Optional[str],
) -> str:
    """
    Сборка читаемой таблицы:
      • Storage — заголовок
      • SIM-type — подзаголовок (между разными SIM — пустая строка)
      • Цвета и цены выровнены в монопространственной колонке
      • Над ценами — лейблы каналов (Best | Top)
    """
    title = f"{cat_emoji} <b>{escape_html(model)}</b>"

    best_label = CHANNEL_SHORT.get(ch_best, ch_best[:4])
    top_label = CHANNEL_SHORT.get(ch_top, (ch_top or "")[:4]) if ch_top else ""
    has_two = bool(ch_top)

    if has_two:
        col_header = (
            " " * COLOR_COL_WIDTH
            + best_label.rjust(PRICE_COL_WIDTH)
            + " │ "
            + top_label.rjust(PRICE_COL_WIDTH)
        )
    else:
        col_header = " " * COLOR_COL_WIDTH + best_label.rjust(PRICE_COL_WIDTH)

    blocks: list = []
    by_storage: dict = {}
    storage_order: list = []
    for vkey in variant_order:
        storage = vkey[0]
        if storage not in by_storage:
            by_storage[storage] = []
            storage_order.append(storage)
        by_storage[storage].append(vkey)

    for storage in storage_order:
        section_lines = [f"📦 <b>{escape_html(storage or '—')}</b>", col_header]
        prev_sim_flag: Optional[tuple] = None
        for vkey in by_storage[storage]:
            _, sim, flag, color, _ = vkey
            sim_flag_key = (sim, flag)
            if prev_sim_flag is not None and sim_flag_key != prev_sim_flag:
                section_lines.append("")
            if sim_flag_key != prev_sim_flag:
                head_parts = []
                if flag:
                    head_parts.append(flag)
                if sim:
                    head_parts.append(escape_html(sim))
                section_lines.append(" ".join(head_parts) if head_parts else "—")
                prev_sim_flag = sim_flag_key

            d = variants[vkey]
            p_best_entry = d.get(ch_best)
            p_top_entry = d.get(ch_top) if ch_top else None
            p_best = p_best_entry[0] if p_best_entry else None
            p_top = p_top_entry[0] if p_top_entry else None

            color_cell = (color or "—").ljust(COLOR_COL_WIDTH)[:COLOR_COL_WIDTH]
            if has_two:
                price_cell = (
                    _format_price_cell(p_best)
                    + " │ "
                    + _format_price_cell(p_top)
                )
            else:
                price_cell = _format_price_cell(p_best)
            section_lines.append(escape_html(color_cell) + price_cell)

        blocks.append("<pre>" + "\n".join(section_lines) + "</pre>")

    return title + "\n\n" + "\n".join(blocks)


async def _build_variant_buttons(
    variant_order: list,
    variants: dict,
    ch_best: str,
    ch_top: Optional[str],
) -> tuple:
    """
    Строит ряды inline-кнопок по вариантам (по одной кнопке на цену канала).
    Каждая кнопка ведёт в карточку товара (callback `pv:`).
    Возвращает (button_rows, pid_map).
    """
    button_rows: list = []
    pid_map: dict = {}

    for vkey in variant_order:
        storage, sim, flag, color, _ = vkey
        d = variants[vkey]
        row: list = []

        for ch, ch_label in (
            (ch_best, CHANNEL_SHORT.get(ch_best, "B")),
            (ch_top, CHANNEL_SHORT.get(ch_top, "T") if ch_top else None),
        ):
            if ch is None:
                continue
            entry = d.get(ch)
            if entry is None:
                continue
            price, pid = entry
            if not pid or price is None:
                continue
            short_id = await redis_store.generate_short_id(pid)
            pid_map[short_id] = pid
            label_parts = []
            if flag:
                label_parts.append(flag)
            if storage:
                label_parts.append(storage)
            if color:
                label_parts.append(color)
            variant_label = " ".join(label_parts) or "—"
            price_str = _format_price_short(price) if price is not None else "—"
            btn_text = f"{ch_label}: {variant_label} · {price_str}"
            row.append(
                InlineKeyboardButton(text=btn_text, callback_data=f"pv:{short_id}")
            )

        if row:
            # Показываем по 1 кнопке в ряд для длинных лейблов на мобильном экране
            for btn in row:
                button_rows.append([btn])

    return button_rows, pid_map


async def _build_model_text(brand: str, model: str, products: list) -> tuple:
    if not products:
        return "", {}

    cat = products[0].get("category_id") or ""
    cat_emoji = {
        "smartphones": "📱", "laptops": "💻", "tablets": "📲",
        "consoles": "🎮", "accessories": "🎧",
    }.get(cat, "📦")

    variant_order, variants, channels_seen = _index_variants(products)

    channels_seen.sort(key=lambda ch: CHANNEL_PRIORITY.get(ch, 99))
    if len(channels_seen) < 2:
        for ch_id in CHANNEL_PRIORITY:
            if ch_id not in channels_seen:
                channels_seen.append(ch_id)
        channels_seen.sort(key=lambda ch: CHANNEL_PRIORITY.get(ch, 99))

    ch_best = channels_seen[0]
    ch_top = channels_seen[1] if len(channels_seen) > 1 else None
    has_two_channels = len([ch for ch in channels_seen if ch != "?"]) >= 2
    if not has_two_channels:
        ch_top = None

    text = _build_table_text(cat_emoji, model, variant_order, variants, ch_best, ch_top)

    pid_map: dict = {}
    for vkey in variant_order:
        for ch in (ch_best, ch_top):
            if ch is None:
                continue
            entry = variants[vkey].get(ch)
            if entry and entry[1]:
                short_id = await redis_store.generate_short_id(entry[1])
                pid_map[short_id] = entry[1]

    return text, pid_map


async def _build_model_blocks(brand: str, model: str, products: list) -> tuple:
    """
    Полная сборка модельной карточки: текст + кнопки-варианты.
    Используется в режиме одиночной модели (build_model_response), где есть место
    под inline-кнопки на каждый прайс.
    Возвращает (text, button_rows, pid_map).
    """
    if not products:
        return "", [], {}

    cat = products[0].get("category_id") or ""
    cat_emoji = {
        "smartphones": "📱", "laptops": "💻", "tablets": "📲",
        "consoles": "🎮", "accessories": "🎧",
    }.get(cat, "📦")

    variant_order, variants, channels_seen = _index_variants(products)

    channels_seen.sort(key=lambda ch: CHANNEL_PRIORITY.get(ch, 99))
    if len(channels_seen) < 2:
        for ch_id in CHANNEL_PRIORITY:
            if ch_id not in channels_seen:
                channels_seen.append(ch_id)
        channels_seen.sort(key=lambda ch: CHANNEL_PRIORITY.get(ch, 99))

    ch_best = channels_seen[0]
    ch_top = channels_seen[1] if len(channels_seen) > 1 else None
    has_two_channels = len([ch for ch in channels_seen if ch != "?"]) >= 2
    if not has_two_channels:
        ch_top = None

    text = _build_table_text(cat_emoji, model, variant_order, variants, ch_best, ch_top)
    button_rows, pid_map = await _build_variant_buttons(variant_order, variants, ch_best, ch_top)

    return text, button_rows, pid_map




async def build_model_response(
    brand: str, model: str, user_id: int, page: int = 0, token: Optional[str] = None
) -> tuple:
    payload = {"brand": brand, "model": model, "limit": 500, "offset": 0}
    raw = await wol_api_client.search_products(payload)
    if not raw or not raw.get("products"):
        kb = InlineKeyboardBuilder()
        kb.button(text="← Назад к каталогу", callback_data="back_to_panel")
        return "Товары не найдены или временно недоступны.", kb.as_markup(), ""
    products = raw.get("products", [])
    if not token:
        token = await redis_store.save_query_token(
            {"brand": brand, "model": model, "mode": "model"}
        )
    model_text, button_rows, pid_map = await _build_model_blocks(brand, model, products)
    if token and pid_map:
        await redis_store.redis.set(
            f"pv_map:{token}",
            json.dumps(pid_map),
            ex=1800
        )
    builder = InlineKeyboardBuilder()
    for row in button_rows:
        builder.row(*row)
    builder.row(InlineKeyboardButton(text="← Каталог", callback_data="back_to_panel"))
    return model_text, builder.as_markup(), token


async def build_search_response(
    query: str, user_id: int, page: int, token: Optional[str] = None
) -> tuple:
    result = await search_service.search(query, user_id=user_id, page=page)
    if not result.items:
        return (
            "Ничего не найдено. Попробуйте изменить запрос.",
            InlineKeyboardMarkup(inline_keyboard=[]),
            "",
        )
    if not token:
        token = await redis_store.save_query_token({"query": query})
    await redis_store.redis.set(f"last_search:{user_id}", f"{token}:{page}", ex=1800)

    # Пост-фильтрация: точное совпадение модели из запроса
    from services.query_router import query_router as _qr
    search_req = _qr.route(result.normalized_query)
    search_model = search_req.model
    if search_model:
        filtered = [
            item for item in result.items
            if _model_matches_query(item.model or "", search_model)
        ]
        if filtered:
            result.items = filtered

    model_groups: dict = {}
    model_order: list = []
    for item in result.items:
        brand_key = item.brand or ""
        model_key = item.model or item.title or ""
        key = (brand_key, model_key)
        if key not in model_groups:
            model_groups[key] = []
            model_order.append(key)
        model_groups[key].append({
            "id": str(item.id),
            "brand": item.brand or "",
            "model": item.model or item.title or "",
            "category_id": item.category_id,
            "source_channel": item.source_channel,
            "price": item.price,
            "attributes": item.attributes or {},
        })

    text = f"🔎 <b>{escape_html(result.normalized_query)}</b>\n"
    if result.total > result.page_size * (page + 1) or page > 0:
        text += f"Найдено: ~{len(result.items)}\n"
    else:
        text += f"Найдено: {len(result.items)}\n"

    all_pid_maps: dict = {}
    for idx, (brand_key, model_key) in enumerate(model_order):
        products = model_groups[(brand_key, model_key)]
        model_text, pid_map = await _build_model_text(brand_key, model_key, products)
        if idx > 0:
            text += "\n"
        text += f"\n{model_text}\n"
        all_pid_maps.update(pid_map)

    if token and all_pid_maps:
        await redis_store.redis.set(
            f"pv_map:{token}",
            json.dumps(all_pid_maps),
            ex=1800
        )

    builder = InlineKeyboardBuilder()

    has_next_page = result.total > (page + 1) * result.page_size
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="←", callback_data=f"s:{token}:{page - 1}"))
    nav_buttons.append(InlineKeyboardButton(text=f"стр. {page + 1}", callback_data="noop"))
    if has_next_page:
        nav_buttons.append(InlineKeyboardButton(text="→", callback_data=f"s:{token}:{page + 1}"))
    if nav_buttons:
        builder.row(*nav_buttons)
    return text, builder.as_markup(), token


@router.message(F.text, ~F.text.startswith("/"), ~F.text.in_(MENU_TEXTS))
async def handle_search_query(message: Message):
    """
    Обрабатывает текстовые поисковые запросы.
    Кнопки меню явно исключены через фильтр ~F.text.in_(...).
    """
    query = (message.text or "").strip()
    if not query:
        return

    wait_msg = await message.answer("⏳ <i>Ищу товары...</i>")

    try:
        text, markup, token = await build_search_response(
            query, message.from_user.id, 0
        )
        sent_msg = await message.answer(text, reply_markup=markup)
        await wait_msg.delete()
        await cleanup_service.register_message(
            message.bot, message.chat.id, sent_msg.message_id
        )
    except Exception as e:
        logger.error(f"Search error for user {message.from_user.id}: {e}")
        await wait_msg.edit_text("Поиск временно недоступен. Попробуйте позже.")


@router.callback_query(F.data.startswith("m:"))
async def handle_model_callback(callback: CallbackQuery):
    """
    Нажатие на кнопку модели в панели каталога (/start).
    """
    short_id = callback.data.split(":", 1)[1]
    model_str = await redis_store.get_full_id(short_id)

    if not model_str or "|||" not in model_str:
        await callback.answer(
            "Данные устарели. Откройте /start заново.", show_alert=True
        )
        return

    brand, model = model_str.split("|||", 1)
    await callback.answer()

    wait_msg = await callback.message.answer("⏳ <i>Загружаю товары...</i>")

    try:
        text, markup, token = await build_model_response(
            brand, model, callback.from_user.id, 0
        )
        await wait_msg.edit_text(text, reply_markup=markup)
        await cleanup_service.register_message(
            callback.bot, callback.message.chat.id, wait_msg.message_id
        )
    except Exception as e:
        logger.error(f"Model search error for {brand} {model}: {e}")
        await wait_msg.edit_text("Не удалось загрузить товары. Попробуйте позже.")


@router.callback_query(F.data.startswith("ms:"))
async def handle_model_pagination(callback: CallbackQuery):
    """
    Пагинация для модельного поиска (ms:token:page).
    """
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Ошибка пагинации", show_alert=True)
        return

    token, page_str = parts[1], parts[2]
    try:
        page = int(page_str)
    except ValueError:
        await callback.answer("Ошибка пагинации", show_alert=True)
        return

    query_data = await redis_store.get_query_data(token)
    if not query_data or "brand" not in query_data:
        await callback.answer(
            "Сессия устарела. Откройте модель заново.", show_alert=True
        )
        return

    brand = query_data["brand"]
    model = query_data["model"]

    try:
        text, markup, _ = await build_model_response(
            brand, model, callback.from_user.id, page, token
        )
        await callback.message.edit_text(text, reply_markup=markup)
        await callback.answer()
    except Exception as e:
        logger.error(f"Model pagination error: {e}")
        await callback.answer("Ошибка загрузки", show_alert=True)


@router.callback_query(F.data == "back_to_panel")
async def handle_back_to_panel(callback: CallbackQuery):
    """
    Кнопка «← Каталог» — возвращает к панели моделей.
    """
    await callback.answer()
    from bot.handlers.common import _build_model_panel

    try:
        text, markup = await _build_model_panel()
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception as e:
        logger.error(f"Back to panel error: {e}")
        await callback.message.answer("Обновите список через /start")


@router.callback_query(F.data.startswith("s:"))
async def handle_pagination(callback: CallbackQuery):
    """
    Пагинация для текстового поиска (s:token:page).
    """
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Ошибка пагинации", show_alert=True)
        return

    token, page_str = parts[1], parts[2]
    try:
        page = int(page_str)
    except ValueError:
        await callback.answer("Ошибка пагинации", show_alert=True)
        return

    query_data = await redis_store.get_query_data(token)
    if not query_data or "query" not in query_data:
        await callback.answer(
            "Сессия устарела. Отправьте запрос заново.", show_alert=True
        )
        return

    query = query_data["query"]

    try:
        text, markup, _ = await build_search_response(
            query, callback.from_user.id, page, token
        )
        if callback.message.html_text != text:
            await callback.message.edit_text(text, reply_markup=markup)
        else:
            await callback.answer("Вы уже на этой странице")
            return
        await callback.answer()
    except Exception as e:
        logger.error(f"Pagination error for token {token}: {e}")
        await callback.answer("Ошибка при загрузке страницы", show_alert=True)




@router.callback_query(F.data.startswith("p:"))
async def handle_product_view(callback: CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) < 2:
        await callback.answer("Неверные данные товара", show_alert=True)
        return
    short_id = parts[1]
    full_id = await redis_store.get_full_id(short_id)
    if not full_id:
        await callback.answer("Товар устарел или не найден. Повторите поиск.", show_alert=True)
        return
    await _show_product_card(callback, full_id)




@router.callback_query(F.data.startswith("pv:"))
async def handle_price_variant_click(callback: CallbackQuery):
    """Клик по цене товара — показ карточки товара."""
    short_id = callback.data.split(":", 1)[1]
    if not short_id or short_id == "noop":
        await callback.answer()
        return
    full_id = await redis_store.get_full_id(short_id)
    if not full_id:
        await callback.answer("Товар устарел. Повторите поиск.", show_alert=True)
        return
    await _show_product_card(callback, full_id)


@router.callback_query(F.data.startswith("o:"))
async def handle_original_post(callback: CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) < 2:
        await callback.answer("Ошибка: неверный код товара.", show_alert=True)
        return
    short_id = parts[1]
    # Защита от двойного нажатия
    lock_key = f"orig_lock:{callback.from_user.id}:{short_id}"
    acquired = await redis_store.redis.set(lock_key, "1", ex=15, nx=True)
    if not acquired:
        await callback.answer()
        return
    full_id = await redis_store.get_full_id(short_id)
    if not full_id:
        await callback.answer("Товар устарел. Пожалуйста, выполните поиск заново.", show_alert=True)
        return
    product_data = await wol_api_client.get_product(full_id)
    if not product_data:
        await callback.answer("Не удалось получить данные о товаре.", show_alert=True)
        return
    raw_post_id = product_data.get("raw_post_id")
    message_link = product_data.get("message_link")
    if not raw_post_id:
        if message_link:
            await callback.message.answer(
                f"Оригинальный пост: {message_link}",
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
            await callback.answer()
        else:
            await callback.answer("Оригинал не найден.", show_alert=True)
        return
    raw_post = await wol_api_client.get_raw_post(raw_post_id)
    if not raw_post:
        if message_link:
            await callback.message.answer(
                f"Оригинальный пост: {message_link}",
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
            await callback.answer()
        else:
            await callback.answer("Оригинал не найден.", show_alert=True)
        return
    text = "📄 <b>Оригинальный пост</b>\n\n"
    post_text = raw_post.get("text") or ""
    if post_text:
        if len(post_text) > 3500:
            post_text = post_text[:3500] + "..."
        text += f"{escape_html(post_text)}\n\n"
    link = raw_post.get("message_link") or message_link
    if link:
        text += f'<a href="{link}">Перейти к посту</a>'
    await callback.message.answer(text, link_preview_options=LinkPreviewOptions(is_disabled=True))
    await callback.answer()




@router.callback_query(F.data.startswith("pt:"))
async def handle_price_table_callback(callback: CallbackQuery):
    token = callback.data.split(":", 1)[1]
    query_data = await redis_store.get_query_data(token)
    if not query_data or "brand" not in query_data:
        await callback.answer("Сессия устарела. Откройте модель заново.", show_alert=True)
        return
    brand = query_data["brand"]
    model = query_data["model"]
    try:
        payload = {"brand": brand, "model": model, "limit": 500, "offset": 0}
        raw = await wol_api_client.search_products(payload)
        if not raw or not raw.get("products"):
            await callback.answer("Нет данных.", show_alert=True)
            return
        products = raw.get("products", [])
        model_text, button_rows, pid_map = await _build_model_blocks(brand, model, products)
        if pid_map:
            await redis_store.redis.set(
                f"pv_map:{token}", json.dumps(pid_map), ex=1800
            )
        builder = InlineKeyboardBuilder()
        for row in button_rows:
            builder.row(*row)
        builder.row(InlineKeyboardButton(text="← Каталог", callback_data="back_to_panel"))
        await callback.message.edit_text(model_text, reply_markup=builder.as_markup())
        await callback.answer()
    except Exception as e:
        logger.error(f"Price table error for {brand} {model}: {e}")
        await callback.answer("Ошибка загрузки таблицы.", show_alert=True)


@router.callback_query(F.data.startswith("pl:"))
async def handle_price_list_callback(callback: CallbackQuery):
    """
    Возврат к списку товаров из таблицы цен (pl:token:page).
    """
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Ошибка", show_alert=True)
        return

    token, page_str = parts[1], parts[2]
    try:
        page = int(page_str)
    except ValueError:
        await callback.answer("Ошибка", show_alert=True)
        return

    query_data = await redis_store.get_query_data(token)
    if not query_data or "brand" not in query_data:
        await callback.answer("Сессия устарела. Откройте модель заново.", show_alert=True)
        return

    brand = query_data["brand"]
    model = query_data["model"]

    try:
        text, markup, _ = await build_model_response(brand, model, callback.from_user.id, page, token)
        await callback.message.edit_text(text, reply_markup=markup)
        await callback.answer()
    except Exception as e:
        logger.error(f"Price list callback error: {e}")
        await callback.answer("Ошибка загрузки", show_alert=True)


@router.callback_query(F.data == "noop")
async def handle_noop(callback: CallbackQuery):
    await callback.answer()
