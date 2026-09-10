"""Tests for the universal parser.

The fixtures under ``tests/data`` are real Telegram-channel posts so the
coverage assertion is measured against the production input format.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.models import RawMessage  # noqa: E402
from services.normalizer import NormalizerService  # noqa: E402
from parser.universal_parser import parse_products  # noqa: E402

DATA_DIR = Path(__file__).parent / "data"
DATE_PREFIX_RE = re.compile(r"^\n?(?=\[\d{2}\.\d{2}\.\d{4}\s+\d{1,2}:\d{2}\])")
POST_SPLIT_RE = re.compile(r"\n(?=\[\d{2}\.\d{2}\.\d{4}\s+\d{1,2}:\d{2}\])")


def _make_raw(text: str, idx: int = 0) -> RawMessage:
    return RawMessage(
        id=f"msg_{idx}",
        text=text,
        timestamp=datetime(2025, 1, 1),
        channel_id="test_channel",
        message_link=f"https://t.me/test/{idx}",
    )


# ---------------------------------------------------------------------------
# Per-format unit tests
# ---------------------------------------------------------------------------


def test_top_resale_iphone_with_explicit_sim_type():
    text = """IPhone 17 Pro:

🇪🇺 Sim+eSim 17 Pro 256GB  White — 100500₽
🇭🇰 Sim+eSim 17 Pro 256GB  Blue — 101000₽
🇯🇵 eSim 17 Pro 512GB  Orange — 105200₽
"""
    products = parse_products(_make_raw(text))
    assert len(products) == 3
    assert all(p.brand == "Apple" for p in products)
    assert all("iPhone 17 Pro" in p.model for p in products)
    assert {p.attributes["flag"] for p in products} == {"🇪🇺", "🇭🇰", "🇯🇵"}
    assert {p.attributes["sim_type"] for p in products} == {"sim+esim", "esim"}
    assert {p.price for p in products} == {100500.0, 101000.0, 105200.0}


def test_bests_resale_iphone_dot_thousands_and_trailing_flag():
    text = """iPhone 14 Plus

14 Plus 128GB Yellow — 42.600 🇭🇰
14 Plus 256GB Black — 45.200 🇺🇸
14 Plus 512GB Purple — 50.300 🇪🇺
"""
    products = parse_products(_make_raw(text))
    assert len(products) == 3
    assert all(p.brand == "Apple" for p in products)
    assert all("iPhone 14 Plus" in p.model for p in products)
    prices = {p.price for p in products}
    assert prices == {42600.0, 45200.0, 50300.0}


def test_skip_asis_lines_only():
    text = """IPhone 13:

iPhone 13 512Gb Starlight 🇸🇬 (Asis+) – 36 600 ₽
iPhone 13 512Gb Blue 🇹🇼 – 41 000 ₽
"""
    products = parse_products(_make_raw(text))
    assert len(products) == 1
    assert products[0].price == 41000.0
    assert "Blue" in (products[0].attributes.get("color") or "")


def test_skip_s_korobkoy_section():
    text = """Asis+ с коробкой

🇮🇳 13 128GB Black — 39400₽
🇮🇳 13 128GB Blue — 39700₽

iPhone 13:

🇮🇳 13 256GB Black — 46500₽
"""
    products = parse_products(_make_raw(text))
    # Lines under "Asis+ с коробкой" must be dropped, the iPhone 13 block kept.
    assert len(products) == 1
    assert products[0].price == 46500.0


def test_samsung_inline_model_codes():
    text = """A56 8/128 Graphite  🇦🇪 — 24800₽
S25 Ultra 12/256 Black S938B/DS 🇲🇾 — 67100₽
S26 Ultra 16/1024 White S948B 🇹🇭 — 111500₽
"""
    products = parse_products(_make_raw(text))
    assert len(products) == 3
    brands = {p.brand for p in products}
    assert brands == {"Samsung"}
    models = sorted(p.model for p in products)
    assert any("A56" in m for m in models)
    assert any("S25 ULTRA" in m for m in models)
    assert any("S26 ULTRA" in m for m in models)


def test_macbook_with_year_in_parens_header():
    text = """[08.06.2025 0:19] Bests re:sale: MacBook Air 13 (M2, 2022)

Air 13 M2 2022 16/256GB Midnight MC7X4 — 67.900 🇺🇸
Air 13 M2 2022 16/512GB Midnight MC7Y4 — 75.300 🇺🇸
"""
    products = parse_products(_make_raw(text))
    assert len(products) == 2
    assert all(p.brand == "Apple" for p in products)
    assert all("MacBook Air" in p.model for p in products)
    assert {p.price for p in products} == {67900.0, 75300.0}


def test_dyson_inferred_from_section_header():
    text = """Беспроводные пылесосы

V8
🇪🇺 V8 SV25 Absolute Yellow/Nickel — 38 500 ₽
🇬🇧 V8 SV25 Absolute Nickel/Yellow — 25 500 ₽

V15
🇪🇺 V15 SV47 Detect Absolute Yellow/Nickel — 48 000 ₽
"""
    products = parse_products(_make_raw(text))
    assert len(products) == 3
    assert all(p.brand == "Dyson" for p in products)
    assert {p.price for p in products} == {38500.0, 25500.0, 48000.0}


def test_sim_type_lookup_by_flag():
    cases = {"🇨🇳": "2sim", "🇪🇺": "sim+esim", "🇺🇸": "esim", "🇯🇵": "esim"}
    for flag, expected in cases.items():
        text = f"iPhone 17 Pro:\n\n{flag} 17 Pro 256GB Black — 100000₽"
        products = parse_products(_make_raw(text))
        assert products and products[0].attributes["sim_type"] == expected, (
            f"{flag}: got {products[0].attributes if products else None}"
        )


def test_meta_lines_ignored():
    text = """iPhone 16 Pro:

🇺🇸 16 Pro 128GB Black — 82300₽

Оформление заказа
💬Менеджер: @top_resale
⁉️Условия работы ( FAQ  (https://t.me/faq_resale))
"""
    products = parse_products(_make_raw(text))
    assert len(products) == 1
    assert products[0].price == 82300.0


def test_top_resale_white_is_corrected_to_silver_for_iphone_pro():
    text = """iPhone 17 Pro Max:

🇯🇵 eSim 17 Pro Max 256GB White - 98300₽
"""
    products = parse_products(_make_raw(text, idx=1).model_copy(update={"channel_id": "1963407298"}))
    assert len(products) == 1
    assert products[0].attributes.get("color") == "Silver"


def test_normalizer_corrects_top_resale_white_to_silver_for_existing_records():
    product = parse_products(
        _make_raw("iPhone 17 Pro:\n\n🇺🇸 eSim 17 Pro 256GB White - 100000₽", idx=2).model_copy(
            update={"channel_id": "1963407298"}
        )
    )[0]
    normalized = NormalizerService.normalize_product(product)
    assert normalized.attributes.get("color") == "Silver"


def test_top_resale_white_is_not_rewritten_for_iphone_air():
    text = """iPhone 17 Air:

🇺🇸 eSim 17 Air 256GB White - 69100₽
"""
    products = parse_products(_make_raw(text, idx=3).model_copy(update={"channel_id": "1963407298"}))
    assert len(products) == 1
    assert products[0].attributes.get("color") == "White"


def test_playstation_portal_is_not_collapsed_into_plain_ps5():
    text = "Sony Portal  — 31.000"
    products = parse_products(_make_raw(text, idx=4).model_copy(update={"channel_id": "1887497207"}))
    assert len(products) == 1
    normalized = NormalizerService.normalize_product(products[0])
    assert normalized.model == "PS5 Portal"


def test_dualsense_section_is_classified_as_ps5_dualshock():
    text = """DualSense PS5:

Black - 5500
Blue - 5300
"""
    products = parse_products(_make_raw(text, idx=5).model_copy(update={"channel_id": "1963407298"}))
    assert len(products) == 2
    normalized_models = {NormalizerService.normalize_product(p).model for p in products}
    assert normalized_models == {"PS5 DualShock"}


def test_ps5_pro_digital_keeps_digital_suffix():
    text = "PS5 Pro Digital 2TB - 74500"
    products = parse_products(_make_raw(text, idx=6).model_copy(update={"channel_id": "1963407298"}))
    assert len(products) == 1
    normalized = NormalizerService.normalize_product(products[0])
    assert normalized.model == "PS5 Pro Digital"


def test_ps5_storage_only_console_line_is_normalized_to_portal():
    text = "PS5 128GB — 27.300"
    products = parse_products(_make_raw(text, idx=7).model_copy(update={"channel_id": "1887497207"}))
    assert len(products) == 1
    normalized = NormalizerService.normalize_product(products[0])
    assert normalized.model == "PS5 Portal"


def test_deterministic_ids_for_same_input():
    text = "IPhone 17:\n\n🇺🇸 17 256GB Black — 60500₽"
    a = parse_products(_make_raw(text))
    b = parse_products(_make_raw(text))
    assert [p.id for p in a] == [p.id for p in b]


def test_empty_input_returns_empty_list():
    assert parse_products(_make_raw("")) == []
    assert parse_products(_make_raw("   \n\n")) == []


# ---------------------------------------------------------------------------
# End-to-end coverage on the real fixture files
# ---------------------------------------------------------------------------


def _split_posts(text: str) -> list[str]:
    return POST_SPLIT_RE.split(text)


@pytest.mark.parametrize(
    "fixture,min_products",
    [
        ("top_resale.txt", 580),  # baseline parser produced 128 here
        ("bests_resale.txt", 770),  # baseline parser produced 4 here
    ],
)
def test_real_fixture_coverage(fixture: str, min_products: int):
    raw = (DATA_DIR / fixture).read_text(encoding="utf-8")
    total = 0
    for idx, post in enumerate(_split_posts(raw)):
        total += len(parse_products(_make_raw(post, idx)))
    assert total >= min_products, (
        f"{fixture}: parsed {total} products, expected at least {min_products}"
    )


def test_no_asis_or_s_korobkoy_in_output():
    """No parsed product should originate from a skipped line."""
    for fixture in ("top_resale.txt", "bests_resale.txt"):
        raw = (DATA_DIR / fixture).read_text(encoding="utf-8")
        for idx, post in enumerate(_split_posts(raw)):
            for product in parse_products(_make_raw(post, idx)):
                attrs = product.attributes
                blob = " ".join(
                    str(v).lower() for v in (product.model, *attrs.values())
                )
                assert "asis" not in blob
                assert "асис" not in blob
                assert "с коробкой" not in blob
                assert "с коробки" not in blob
