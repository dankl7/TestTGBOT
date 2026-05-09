import logging
from datetime import datetime, timedelta, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select, func, desc

from config import settings
from database.session import async_session_maker
from database.models import UserSearchHistory, TrackedProduct
from utils.text import escape_html

logger = logging.getLogger(__name__)
router = Router()


def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором."""
    return user_id in settings.admin_user_ids


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    """
    Главное меню администратора.
    """
    if not is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    text = (
        "🔧 <b>Админ-панель</b>\n\n"
        "Доступные команды:\n"
        "• /admin_stats — Краткая статистика\n"
        "• /admin_top_day — Топ-10 запросов за день\n"
        "• /admin_top_week — Топ-10 запросов за неделю\n"
        "• /admin_top_month — Топ-10 запросов за месяц\n"
        "• /db_table — Просмотр таблицы (напр. <code>/db_table products</code>)\n"
        "• /db_schema — Схема таблицы (напр. <code>/db_schema products</code>)"
    )
    await message.answer(text)


@router.message(Command("admin_stats"))
async def cmd_admin_stats(message: Message):
    """
    Выводит краткую статистику по пользователям, запросам и отслеживаниям.
    """
    if not is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    try:
        async with async_session_maker() as session:
            # Уникальные пользователи
            users_count = await session.scalar(
                select(func.count(func.distinct(UserSearchHistory.user_id)))
            )
            # Количество поисковых запросов
            queries_count = await session.scalar(
                select(func.count(UserSearchHistory.id))
            )
            # Количество отслеживаемых товаров (всего записей)
            tracked_total = await session.scalar(
                select(func.count(TrackedProduct.id))
            )
            # Количество активных отслеживаний
            tracked_active = await session.scalar(
                select(func.count(TrackedProduct.id)).where(TrackedProduct.is_active == True)
            )

        text = (
            "📊 <b>Краткая статистика</b>\n\n"
            f"Уникальных пользователей: <b>{users_count or 0}</b>\n"
            f"Всего поисковых запросов: <b>{queries_count or 0}</b>\n"
            f"Всего отслеживаний (вкл. неактивные): <b>{tracked_total or 0}</b>\n"
            f"Активных отслеживаний: <b>{tracked_active or 0}</b>"
        )
        await message.answer(text)

    except Exception as e:
        logger.error(f"Error getting admin stats: {e}")
        await message.answer("Произошла ошибка при получении статистики.")


async def _get_top_queries(since_date: datetime, limit: int = 10):
    """
    Вспомогательная функция для получения топа запросов.
    Группирует по normalized_query.
    """
    async with async_session_maker() as session:
        stmt = (
            select(
                func.coalesce(UserSearchHistory.normalized_query, UserSearchHistory.query).label("q_text"),
                func.count(UserSearchHistory.id).label("q_count")
            )
            .where(UserSearchHistory.created_at >= since_date)
            .group_by("q_text")
            .order_by(desc("q_count"))
            .limit(limit)
        )
        result = await session.execute(stmt)
        return result.all()


def _format_top_queries(title: str, top_data: list) -> str:
    """Форматирует результат топа запросов в строку."""
    text = f"🏆 <b>{title}</b>\n\n"
    if not top_data:
        text += "Нет данных за этот период."
        return text

    for i, (query, count) in enumerate(top_data, start=1):
        # Если запрос пустой (например, только фильтры), заменяем на метку
        display_query = query if query else "<без текста>"
        text += f"<b>{i}.</b> {escape_html(display_query)} — {count} раз(а)\n"
    return text


@router.message(Command("admin_top_day"))
async def cmd_admin_top_day(message: Message):
    """Топ-10 запросов за последние 24 часа."""
    if not is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    try:
        since = datetime.now(timezone.utc) - timedelta(days=1)
        top = await _get_top_queries(since)
        text = _format_top_queries("Топ-10 запросов за день", top)
        await message.answer(text)
    except Exception as e:
        logger.error(f"Error getting top day queries: {e}")
        await message.answer("Ошибка при получении данных.")


@router.message(Command("admin_top_week"))
async def cmd_admin_top_week(message: Message):
    """Топ-10 запросов за последние 7 дней."""
    if not is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    try:
        since = datetime.now(timezone.utc) - timedelta(days=7)
        top = await _get_top_queries(since)
        text = _format_top_queries("Топ-10 запросов за неделю", top)
        await message.answer(text)
    except Exception as e:
        logger.error(f"Error getting top week queries: {e}")
        await message.answer("Ошибка при получении данных.")


@router.message(Command("admin_top_month"))
async def cmd_admin_top_month(message: Message):
    """Топ-10 запросов за последние 30 дней."""
    if not is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    try:
        since = datetime.now(timezone.utc) - timedelta(days=30)
        top = await _get_top_queries(since)
        text = _format_top_queries("Топ-10 запросов за месяц", top)
        await message.answer(text)
    except Exception as e:
        logger.error(f"Error getting top month queries: {e}")
        await message.answer("Ошибка при получении данных.")
