import html
from typing import Optional


def escape_html(text: Optional[str]) -> str:
    """
    Экранирует специальные символы для безопасного использования в HTML-разметке Telegram.

    Заменяет символы `&`, `<`, `>` и `"` на соответствующие HTML-сущности.
    """
    if not text:
        return ""
    return html.escape(str(text))


def truncate_text(text: Optional[str], max_length: int = 200, suffix: str = "...") -> str:
    """
    Обрезает длинный текст до указанной длины (max_length) и добавляет суффикс,
    если обрезка произошла. Полезно для превью постов.
    """
    if not text:
        return ""

    text = str(text)
    if len(text) <= max_length:
        return text

    return text[:max_length].strip() + suffix
