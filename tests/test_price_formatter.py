from utils.price_formatter import format_price

def test_price_formatter():
    assert format_price(79990) == "79 990 ₽"
    assert format_price(0) == "0 ₽"
    assert format_price(None) == "Цена не указана"
