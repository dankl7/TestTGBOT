from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_product_keyboard(short_id: str, back_data: str | None = None, price: str | None = None) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для карточки товара.
    """
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text="📊 История цен", callback_data=f"ph:{short_id}"),
        InlineKeyboardButton(text="🔔 Отслеживать", callback_data=f"t:{short_id}"),
        InlineKeyboardButton(text="📄 Оригинал", callback_data=f"o:{short_id}")
    )

    if back_data:
        builder.row(
            InlineKeyboardButton(text="← Назад", callback_data=back_data)
        )

    return builder.as_markup()


def get_search_pagination_keyboard(token: str, current_page: int, has_next_page: bool) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для пагинации результатов поиска.
    """
    builder = InlineKeyboardBuilder()

    buttons = []

    if current_page > 0:
        buttons.append(
            InlineKeyboardButton(text="←", callback_data=f"s:{token}:{current_page - 1}")
        )

    # Кнопка-индикатор текущей страницы (можно сделать неактивной, передав фиктивный callback_data)
    buttons.append(
        InlineKeyboardButton(text=f"стр. {current_page + 1}", callback_data="noop")
    )

    if has_next_page:
        buttons.append(
            InlineKeyboardButton(text="→", callback_data=f"s:{token}:{current_page + 1}")
        )

    builder.row(*buttons)

    return builder.as_markup()
