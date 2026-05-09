import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.keyboards.menu import get_main_menu
from database.repositories.catalog import catalog_repository
from database.session import async_session_maker
from services.redis_store import redis_store

logger = logging.getLogger(__name__)
router = Router()

# Настройки отображения категорий на панели моделей
CATEGORY_CONFIG = {
    "smartphones": {"emoji": "📱", "label": "Смартфоны", "order": 0},
    "laptops": {"emoji": "💻", "label": "Ноутбуки", "order": 1},
    "tablets": {"emoji": "📲", "label": "Планшеты", "order": 2},
    "consoles": {"emoji": "🎮", "label": "Приставки", "order": 3},
    "accessories": {"emoji": "🎧", "label": "Аксессуары", "order": 4},
}

# Максимум моделей на категорию в панели
MAX_MODELS_PER_CATEGORY = 12


async def _build_model_panel():
    """
    Строит inline-клавиатуру с моделями товаров, подгружая данные из БД.
    Группирует по категориям, ограничивает количество кнопок.
    Возвращает (text, markup).
    """
    async with async_session_maker() as session:
        models = await catalog_repository.get_distinct_models(session, min_count=3)

    # Группировка по категории
    by_cat: dict = {}
    for m in models:
        cat = m.get("category_id") or "other"
        by_cat.setdefault(cat, []).append(m)

    builder = InlineKeyboardBuilder()

    cat_order = sorted(CATEGORY_CONFIG.items(), key=lambda x: x[1]["order"])

    has_buttons = False

    for cat_id, cfg in cat_order:
        cat_models = by_cat.get(cat_id, [])
        if not cat_models:
            continue

        # Берем топ-N самых популярных моделей категории
        top_models = cat_models[:MAX_MODELS_PER_CATEGORY]

        for m in top_models:
            model_name = m["model"]
            brand = m["brand"]
            emoji = cfg["emoji"]

            # Создаём короткую метку кнопки (убираем стандартные префиксы)
            short_label = model_name
            for prefix in [f"{brand} ", "Apple ", "Samsung ", "Dyson "]:
                if short_label.startswith(prefix):
                    short_label = short_label[len(prefix) :]
                    break

            button_label = f"{emoji} {short_label}"

            # Сохраняем brand|||model в Redis, получаем короткий токен
            key = await redis_store.generate_short_id(f"{brand}|||{model_name}")
            builder.button(text=button_label, callback_data=f"m:{key}")
            has_buttons = True

    if not has_buttons:
        builder.button(text="🔎 Открыть поиск", callback_data="noop")

    # 2 кнопки в ряд — компактная сетка
    builder.adjust(2)

    text = (
        "📦 <b>Каталог моделей</b>\n\n"
        "Выберите модель для просмотра актуальных цен 👇\n"
        "или воспользуйтесь кнопкой <b>🔎 Поиск</b> для ручного запроса.\n\n"
        "<i>Данные обновляются в реальном времени из базы Window of Light.</i>"
    )

    return text, builder.as_markup()


@router.message(CommandStart())
async def cmd_start(message: Message):
    """
    Обработчик /start.
    Показывает приветствие + главное меню + панель моделей из БД.
    """
    # Удаляем команду /start из чата (убираем "лишний" текст)
    try:
        await message.delete()
    except Exception:
        pass

    # Отправляем меню
    await message.answer(
        "👋 <b>Добро пожаловать!</b>\n\n"
        "Выберите модель из каталога или воспользуйтесь поиском.",
        reply_markup=get_main_menu(),
    )

    # Загружаем и отправляем панель моделей
    try:
        text, markup = await _build_model_panel()
        await message.answer(text, reply_markup=markup)
    except Exception as e:
        logger.error(f"Model panel build error: {e}")
        await message.answer(
            "Каталог временно недоступен. Используйте кнопку 🔎 Поиск."
        )


@router.callback_query(F.data == "refresh_panel")
async def cb_refresh_panel(callback: CallbackQuery):
    """Обновляет панель моделей."""
    try:
        text, markup = await _build_model_panel()
        await callback.message.edit_text(text, reply_markup=markup)
        await callback.answer("✅ Список обновлён")
    except Exception as e:
        logger.error(f"Panel refresh error: {e}")
        await callback.answer("Ошибка обновления", show_alert=True)


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Помощь")
async def cmd_help(message: Message):
    """
    Обработчик /help и кнопки «ℹ️ Помощь».
    """
    try:
        await message.delete()
    except Exception:
        pass

    text = (
        "ℹ️ <b>Справка по использованию бота</b>\n\n"
        "📦 <b>Панель моделей</b>\n"
        "На главном экране отображаются актуальные модели из каталога. "
        "Нажмите на модель — увидите все доступные варианты с ценами, "
        "сгруппированные по объёму памяти.\n\n"
        "🔎 <b>Как искать товары?</b>\n"
        "Нажмите кнопку «🔎 Поиск» или просто напишите запрос:\n"
        "• <code>16 PM</code> → iPhone 16 Pro Max\n"
        "• <code>Самсунг S26 Ultra</code> → Samsung Galaxy S26 Ultra\n"
        "• <code>MBA M5</code> → MacBook Air M5\n"
        "Можно уточнить память (<i>256, 512, 1tb</i>) и цвет.\n\n"
        "🔔 <b>Отслеживание цен</b>\n"
        "В карточке товара нажмите «🔔 Отслеживать». "
        "Бот уведомит вас об изменении цены.\n"
        "Список отслеживаемых — кнопка «🔔 Отслеживаемые».\n\n"
        "📜 <b>История</b>\n"
        "Кнопка «📜 История» — ваши последние 20 поисков с актуальными ценами."
    )
    await message.answer(text)


@router.message(F.text == "🔎 Поиск")
async def btn_search(message: Message):
    """
    Кнопка «🔎 Поиск» — подсказывает ввести запрос.
    """
    try:
        await message.delete()
    except Exception:
        pass

    await message.answer(
        "Введите поисковый запрос.\n\n"
        "💡 <i>Например: <code>iPhone 17 Pro 256</code> или <code>S26 Ultra</code></i>"
    )
