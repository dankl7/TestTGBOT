import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

from config import settings
from bot.handlers import projects, common, login
from services.max_worker import start_worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

RESTART_DELAY = 15
MAX_RETRIES = 100


async def create_bot() -> Bot:
    session = None
    if settings.telegram_proxy_url:
        ptype = (settings.telegram_proxy_type or "HTTP").lower()
        if ptype in ("socks5", "socks"):
            session = AiohttpSession(proxy=settings.telegram_proxy_url)
        else:
            session = AiohttpSession(proxy=settings.telegram_proxy_url)
    return Bot(
        token=settings.telegram_bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )


async def test_bot(bot: Bot) -> bool:
    try:
        await asyncio.wait_for(bot.get_me(), timeout=10)
        return True
    except Exception:
        return False


async def run_bot():
    storage = RedisStorage.from_url(settings.redis_url)
    dp = Dispatcher(storage=storage)

    dp.include_router(common.router)
    dp.include_router(login.router)
    dp.include_router(projects.router)

    worker_task = None

    for attempt in range(1, MAX_RETRIES + 1):
        logger.info(f"Bot initialization (attempt {attempt}/{MAX_RETRIES})...")
        bot = await create_bot()
        try:
            if not await test_bot(bot):
                logger.warning("Telegram API unavailable, retrying in %ds...", RESTART_DELAY)
                await bot.session.close()
                await asyncio.sleep(RESTART_DELAY)
                continue

            logger.info("Telegram connection established!")
            logger.info("Starting polling...")
            await bot.delete_webhook(drop_pending_updates=True)

            worker_task = asyncio.create_task(start_worker())

            await dp.start_polling(bot)

        except Exception as e:
            if "ProxyError" in type(e).__name__ or "SOCKS" in str(e) or "ConnectionRefused" in str(e):
                logger.error("Proxy error: %s. Waiting for recovery...", e)
                await asyncio.sleep(RESTART_DELAY * 2)
            else:
                logger.error("Error: %s. Reconnecting in %ds...", e, RESTART_DELAY)
        finally:
            if worker_task:
                worker_task.cancel()
                try:
                    await worker_task
                except asyncio.CancelledError:
                    pass
            try:
                await bot.session.close()
            except Exception:
                pass
            await asyncio.sleep(RESTART_DELAY)

    logger.error("Max retries exceeded.")


async def main():
    logger.info("LithTGBot starting...")
    try:
        await run_bot()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())