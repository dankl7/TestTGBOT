from decimal import Decimal
from typing import Union


def format_price(price: Union[int, float, Decimal, str, None]) -> str:
    """
    Форматирует цену с пробелами между тысячами и добавляет знак рубля.

    Примеры:
    - 79990 -> "79 990 ₽"
    - 0 -> "0 ₽"
    - None -> "Цена не указана"
    """
    if price is None:
        return "Цена не указана"

    try:
        price_val = int(float(price))
        formatted = f"{price_val:,}".replace(",", " ")
        return f"{formatted} ₽"
    except (ValueError, TypeError):
        return "Цена не указана"


def format_price_list(price: Union[int, float, Decimal, str, None]) -> str:
    """
    Компактный формат цены для вывода в списке товаров.
    Использует точку как разделитель тысяч, без знака валюты.

    Примеры:
    - 67000  -> "67.000"
    - 68200  -> "68.200"
    - 110000 -> "110.000"
    - None   -> "—"
    """
    if price is None:
        return "—"

    try:
        price_val = int(float(price))
        formatted = f"{price_val:,}".replace(",", ".")
        return formatted
    except (ValueError, TypeError):
        return "—"


def format_price_rub(price: Union[int, float, Decimal, str, None]) -> str:
    """
    Компактный формат цены для вывода в списке: с точкой как разделителем
    тысяч и символом ₽.

    Примеры:
    - 62700  -> "62.700₽"
    - 108700 -> "108.700₽"
    - None   -> "—"
    """
    if price is None:
        return "—"

    try:
        price_val = int(float(price))
        formatted = f"{price_val:,}".replace(",", ".")
        return f"{formatted}₽"
    except (ValueError, TypeError):
        return "—"
