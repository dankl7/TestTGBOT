from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def get_main_menu() -> ReplyKeyboardMarkup:
    """
    Создает и возвращает главную reply-клавиатуру меню.
    Три кнопки: Поиск, История, Отслеживаемые.
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🔎 Поиск"),
                KeyboardButton(text="📜 История"),
                KeyboardButton(text="🔔 Отслеживаемые"),
            ],
            [
                KeyboardButton(text="ℹ️ Помощь"),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Введите модель или нажмите кнопку выше"
    )
