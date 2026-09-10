from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def get_main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    keyboard = []
    if is_admin:
        keyboard.append([KeyboardButton(text="📋 Проекты")])
    keyboard.append([KeyboardButton(text="🔧 Админ")])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Меню управления проектами"
    )
