import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession

from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

from config import settings

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

async def main():
    logger.info("Инициализация бота...")

    # Инициализация Redis storage для FSM (опционально, но полезно для aiogram)
    storage = RedisStorage.from_url(settings.redis_url)


    # Настройка прокси
    session = None
    if settings.telegram_proxy_url:
        logger.info(f"Используется прокси для Telegram: {settings.telegram_proxy_host}:{settings.telegram_proxy_port}")
        session = AiohttpSession(proxy=settings.telegram_proxy_url)

    # Инициализация бота с дефолтными настройками
    bot = Bot(
        token=settings.telegram_bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )


    # Инициализация диспетчера
    dp = Dispatcher(storage=storage)

    from bot.handlers.common import router as common_router
    from bot.handlers.search import router as search_router
    from bot.handlers.tracking import router as tracking_router
    from bot.handlers.history import router as history_router
    from bot.handlers.catalog import router as catalog_router
    from bot.handlers.admin import router as admin_router
    from bot.middlewares.rate_limit import RateLimitMiddleware

    dp.message.middleware(RateLimitMiddleware())
    # IMPORTANT: common, tracking, history, catalog routers MUST be registered
    # BEFORE search_router so their handlers match first.
    # search_router catches all non-menu text messages.
    dp.include_router(common_router)
    dp.include_router(tracking_router)
    dp.include_router(history_router)
    dp.include_router(catalog_router)
    dp.include_router(admin_router)
    dp.include_router(search_router)  # Must be last!

    # Удаляем вебхуки и запускаем polling
    try:
        logger.info("Запуск polling...")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка во время выполнения бота: {e}")
    finally:
        logger.info("Остановка бота, закрытие сессий...")
        await dp.storage.close()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен пользователем.")
