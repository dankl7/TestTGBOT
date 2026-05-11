"""
Каталог категорий для inline-меню.

Конфиг плоский: список словарей с короткой ключевой строкой (≤8 символов,
влезет в Telegram callback_data вместе с префиксом `cat:`) и SQL-фильтрами.

Фильтры объединяются по AND. Поддерживаются:
    brand          — exact, products.brand = :brand (case-insensitive ILIKE)
    brand_in       — список брендов (ILIKE ANY)
    category_id    — exact, products.category_id = :cid
    model_like     — ILIKE pattern (use % wildcards)
    model_regex    — POSIX regex (operator: ~*)
"""
from __future__ import annotations
from typing import Final, List, Tuple, TypedDict


class CatalogCategory(TypedDict, total=False):
    key: str
    label: str
    brand: str
    brand_in: List[str]
    category_id: str
    model_like: str
    model_regex: str


CATEGORIES: Final[List[CatalogCategory]] = [
    # ─── iPhones ───
    {"key": "ip17", "label": "📱 iPhone 17",       "brand": "Apple", "model_like": "iPhone 17%"},
    {"key": "ip16", "label": "📱 iPhone 16",       "brand": "Apple", "model_like": "iPhone 16%"},
    {"key": "ip15", "label": "📱 iPhone 15",       "brand": "Apple", "model_like": "iPhone 15%"},
    {"key": "ip14", "label": "📱 iPhone 14",       "brand": "Apple", "model_like": "iPhone 14%"},
    {"key": "ipold","label": "📱 iPhone SE/11/12/13", "brand": "Apple", "model_regex": "^iPhone (SE|11|12|13)( |$)"},
    # ─── Apple Watch / AirPods / accessories Apple ───
    {"key": "watch",  "label": "⌚ Apple Watch", "brand": "Apple", "model_like": "Apple Watch%"},
    {"key": "airpod", "label": "🎧 AirPods",     "brand": "Apple", "model_like": "AirPods%"},
    # ─── iPads ───
    {"key": "ipadpro","label": "📲 iPad Pro",  "brand": "Apple", "model_like": "iPad Pro%"},
    {"key": "ipadair","label": "📲 iPad Air",  "brand": "Apple", "model_like": "iPad Air%"},
    {"key": "ipad",   "label": "📲 iPad / Mini","brand": "Apple", "model_regex": "^iPad (Mini|[0-9])"},
    # ─── MacBooks / iMac / Mac Mini ───
    {"key": "mba",  "label": "💻 MacBook Air",       "brand": "Apple", "model_like": "MacBook Air%"},
    {"key": "mbp",  "label": "💻 MacBook Pro",       "brand": "Apple", "model_like": "MacBook Pro%"},
    {"key": "mneo", "label": "💻 MacBook Neo / iMac","brand": "Apple", "model_regex": "^(MacBook Neo|iMac|Mac Mini)"},
    # ─── Samsung ───
    {"key": "samsz","label": "📱 Samsung Galaxy S / Z", "brand": "Samsung", "model_regex": "^Samsung Galaxy [SZ]"},
    {"key": "sama", "label": "📱 Samsung Galaxy A",    "brand": "Samsung", "model_like": "Samsung Galaxy A%"},
    # ─── Other phones ───
    {"key": "pixel","label": "📱 Google Pixel",      "brand": "Google"},
    {"key": "xiao", "label": "📱 Xiaomi / Mi / Redmi","brand": "Xiaomi"},
    {"key": "poco", "label": "📱 Poco",              "brand": "Poco"},
    {"key": "honor","label": "📱 Honor",             "brand": "Honor"},
    {"key": "huawei","label": "📱 Huawei",           "brand": "Huawei"},
    # ─── Dyson ───
    {"key": "dysonh","label": "💇 Dyson HD/HS (фен/стайлер)", "brand": "Dyson",
     "model_regex": "^Dyson (HD|HS|Air|Supersonic)"},
    {"key": "dysonv","label": "🧹 Dyson V-Series (пылесос)",  "brand": "Dyson",
     "model_regex": "^Dyson (V[0-9]|Gen|Pencil|Ball|Big|Clean)"},
    # ─── Consoles ───
    {"key": "ps",   "label": "🎮 Sony PlayStation",  "brand": "Sony_PlayStation"},
    # ─── Прочее ───
    {"key": "acc",  "label": "🧰 Прочие аксессуары", "category_id": "accessories"},
]


CATEGORY_BY_KEY: Final[dict] = {c["key"]: c for c in CATEGORIES}


def build_where_clause(cat: CatalogCategory) -> Tuple[str, dict]:
    """SQL WHERE для категории. Возвращает (sql_fragment, params)."""
    parts: list = []
    params: dict = {}
    if "brand" in cat:
        parts.append("brand ILIKE :brand")
        params["brand"] = cat["brand"]
    if "brand_in" in cat:
        parts.append("brand = ANY(:brands)")
        params["brands"] = list(cat["brand_in"])
    if "category_id" in cat:
        parts.append("category_id = :cid")
        params["cid"] = cat["category_id"]
    if "model_like" in cat:
        parts.append("model ILIKE :model_like")
        params["model_like"] = cat["model_like"]
    if "model_regex" in cat:
        parts.append("model ~* :model_regex")
        params["model_regex"] = cat["model_regex"]
    if not parts:
        parts.append("TRUE")
    return " AND ".join(parts), params
