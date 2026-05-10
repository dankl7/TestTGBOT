"""Тесты на форматирование таблицы цен и группировку вариантов."""
import re
from unittest.mock import AsyncMock, patch

import pytest

from bot.handlers.search import (
    CHANNEL_PRIORITY,
    _build_model_blocks,
    _build_table_text,
    _index_variants,
)


def _product(
    pid: str,
    storage: str,
    sim: str,
    flag: str,
    color: str,
    price: float,
    channel: str,
):
    return {
        "id": pid,
        "category_id": "smartphones",
        "brand": "Apple",
        "model": "iPhone 17 Pro Max",
        "price": price,
        "source_channel": channel,
        "attributes": {
            "storage": storage,
            "sim_type": sim,
            "flag": flag,
            "color": color,
        },
    }


CH_BEST = next(c for c, v in CHANNEL_PRIORITY.items() if v == 0)
CH_TOP = next(c for c, v in CHANNEL_PRIORITY.items() if v == 1)


def test_index_variants_keeps_cheapest_per_channel():
    """Если по одному варианту есть две цены в одном канале — выбирается дешёвая."""
    products = [
        _product("a", "256GB", "ESIM", "🇪🇺", "White", 110_400, CH_BEST),
        _product("b", "256GB", "ESIM", "🇪🇺", "White", 109_000, CH_BEST),
    ]
    order, variants, channels = _index_variants(products)
    assert len(order) == 1
    vkey = order[0]
    price, pid = variants[vkey][CH_BEST]
    assert price == 109_000
    assert pid == "b"


def test_index_variants_groups_by_attributes():
    """Разные цвета/SIM/storage → разные ключи."""
    products = [
        _product("1", "256GB", "ESIM", "🇪🇺", "White", 100, CH_BEST),
        _product("2", "256GB", "ESIM", "🇪🇺", "Blue", 100, CH_BEST),
        _product("3", "512GB", "ESIM", "🇪🇺", "White", 200, CH_BEST),
        _product("4", "256GB", "SIM+ESIM", "🇪🇺", "White", 150, CH_BEST),
    ]
    order, _, _ = _index_variants(products)
    assert len(order) == 4


def test_build_table_text_groups_by_storage():
    """Каждый storage становится своим заголовком в <pre>-блоке."""
    products = [
        _product("a", "256GB", "ESIM", "🇪🇺", "White", 100, CH_BEST),
        _product("b", "512GB", "ESIM", "🇪🇺", "White", 200, CH_BEST),
    ]
    order, variants, _ = _index_variants(products)
    text = _build_table_text(
        "📱", "iPhone 17 Pro Max", order, variants, CH_BEST, CH_TOP
    )
    # Заголовки storage с эмодзи коробки
    assert "<b>256GB</b>" in text
    assert "<b>512GB</b>" in text
    # Каждый storage в собственном <pre>-блоке
    assert text.count("<pre>") == 2
    assert text.count("</pre>") == 2


def test_build_table_text_separates_sim_types_with_blank_line():
    """Между разными SIM-типами в пределах одного storage — пустая строка."""
    products = [
        _product("a", "256GB", "ESIM", "🇪🇺", "White", 100, CH_BEST),
        _product("b", "256GB", "SIM+ESIM", "🇪🇺", "White", 200, CH_BEST),
    ]
    order, variants, _ = _index_variants(products)
    text = _build_table_text(
        "📱", "iPhone 17 Pro Max", order, variants, CH_BEST, CH_TOP
    )
    # SIM+ESIM сортируется первым, ESIM — вторым.
    # Между двумя SIM-блоками должна быть пустая строка внутри <pre>.
    pre_block = text[text.index("<pre>"):text.index("</pre>")]
    assert "\n\n" in pre_block


def test_build_table_text_has_channel_labels_at_top():
    """Над колонками цен — лейблы каналов (Best | Top)."""
    products = [
        _product("a", "256GB", "ESIM", "🇪🇺", "White", 100_000, CH_BEST),
        _product("b", "256GB", "ESIM", "🇪🇺", "White", 110_000, CH_TOP),
    ]
    order, variants, _ = _index_variants(products)
    text = _build_table_text(
        "📱", "iPhone 17 Pro Max", order, variants, CH_BEST, CH_TOP
    )
    assert "Best" in text
    assert "Top" in text


def test_build_table_text_aligns_prices_in_same_column():
    """Цены выровнены по правому краю в монопространственной колонке."""
    products = [
        _product("a", "256GB", "ESIM", "🇪🇺", "White", 100_000, CH_BEST),
        _product("b", "256GB", "ESIM", "🇪🇺", "Blue", 99_500, CH_BEST),
    ]
    order, variants, _ = _index_variants(products)
    text = _build_table_text(
        "📱", "iPhone 17 Pro Max", order, variants, CH_BEST, None
    )
    pre_match = re.search(r"<pre>(.*?)</pre>", text, flags=re.S)
    assert pre_match is not None
    block = pre_match.group(1)
    # Найдём строки, содержащие цены (форматированные числа)
    price_lines = [
        line for line in block.split("\n") if "100.000" in line or "99.500" in line
    ]
    assert len(price_lines) == 2
    # Строки должны иметь одинаковую длину (правое выравнивание цен)
    assert len(price_lines[0]) == len(price_lines[1])


@pytest.mark.asyncio
async def test_build_model_blocks_creates_buttons_per_variant_price():
    """Каждый вариант с ценой получает кликабельную кнопку (callback `pv:`)."""
    products = [
        _product("a", "256GB", "ESIM", "🇪🇺", "White", 100_000, CH_BEST),
        _product("b", "256GB", "ESIM", "🇪🇺", "White", 110_000, CH_TOP),
        _product("c", "256GB", "ESIM", "🇪🇺", "Blue", 99_500, CH_BEST),
    ]

    fake_short_ids = iter(["sa", "sb", "sc"])

    with patch("bot.handlers.search.redis_store") as mock_store:
        mock_store.generate_short_id = AsyncMock(side_effect=lambda _: next(fake_short_ids))

        text, button_rows, pid_map = await _build_model_blocks(
            "Apple", "iPhone 17 Pro Max", products
        )

        # 3 кнопки (по одной на цену) → 3 строки
        assert len(button_rows) == 3
        all_callbacks = [row[0].callback_data for row in button_rows]
        assert all(cb.startswith("pv:") for cb in all_callbacks)

        # Все цены отрисовались в подписях кнопок
        all_labels = " ".join(row[0].text for row in button_rows)
        assert "100.000" in all_labels
        assert "110.000" in all_labels
        assert "99.500" in all_labels

        # pid_map содержит short_id → product_id для всех кнопок
        assert set(pid_map.values()) == {"a", "b", "c"}

        # Текст содержит заголовок модели
        assert "iPhone 17 Pro Max" in text


@pytest.mark.asyncio
async def test_build_model_blocks_skips_variants_without_price():
    """Если у варианта нет цены ни в одном канале — кнопок не создаётся."""
    products = [
        {
            "id": "x",
            "category_id": "smartphones",
            "brand": "Apple",
            "model": "iPhone 17 Pro Max",
            "price": None,
            "source_channel": CH_BEST,
            "attributes": {
                "storage": "256GB",
                "sim_type": "ESIM",
                "flag": "🇺🇸",
                "color": "Cosmic Orange",
            },
        }
    ]
    with patch("bot.handlers.search.redis_store") as mock_store:
        mock_store.generate_short_id = AsyncMock(return_value="sx")
        _, button_rows, pid_map = await _build_model_blocks(
            "Apple", "iPhone 17 Pro Max", products
        )
        assert button_rows == []
        assert pid_map == {}
