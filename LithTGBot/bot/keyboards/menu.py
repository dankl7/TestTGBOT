from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def get_main_menu() -> ReplyKeyboardMarkup:
    """
    Создает и возвращает главную reply-клавиатуру меню.
    Кнопки: Поиск, История, Отслеживаемые, Каталог, Помощь.
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🔎 Поиск"),
                KeyboardButton(text="📜 История"),
                KeyboardButton(text="🔔 Отслеживаемые"),
            ],
            [
                KeyboardButton(text="🗂 Каталог"),
                KeyboardButton(text="ℹ️ Помощь"),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Введите модель или нажмите кнопку выше"
    )
