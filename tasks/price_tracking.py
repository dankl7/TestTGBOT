import asyncio
import logging
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import settings
from tasks.celery import app
from database.session import async_session_maker
from database.repositories.tracked import tracked_repository
from integrations.wol_api import wol_api_client
from utils.price_formatter import format_price
from utils.text import escape_html

logger = logging.getLogger(__name__)


async def run_price_tracking():
    """
    Асинхронная бизнес-логика проверки отслеживаемых товаров.
    Получает все активные подписки, сверяет цену, и при изменении
    отправляет пользователю уведомление.
    """
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    try:
        async with async_session_maker() as session:
            trackings = await tracked_repository.get_all_active_trackings(session)

            if not trackings:
                logger.info("Нет активных отслеживаемых товаров.")
                return

            logger.info(f"Начало проверки цен для {len(trackings)} отслеживаний.")

            for tracking in trackings:
                try:
                    product_id_str = str(tracking.product_id)
                    product_data = await wol_api_client.get_product(product_id_str)

                    if not product_data or product_data.get("price") is None:
                        logger.warning(f"Не удалось получить актуальную цену для товара {product_id_str}")
                        continue

                    current_price = float(product_data["price"])
                    last_seen = float(tracking.last_seen_price) if tracking.last_seen_price else 0.0

                    if current_price != last_seen:
                        title = f"{product_data.get('brand', '')} {product_data.get('model', '')}".strip()
                        old_price_str = format_price(last_seen)
                        new_price_str = format_price(current_price)

                        if current_price < last_seen:
                            change_msg = "📉 <b>Цена снизилась!</b>"
                        else:
                            change_msg = "📈 <b>Цена выросла!</b>"

                        text = (
                            f"{change_msg}\n\n"
                            f"📦 <b>{escape_html(title)}</b>\n"
                            f"Старая цена: <s>{old_price_str}</s>\n"
                            f"Новая цена: <b>{new_price_str}</b>\n\n"
                            f"<i>Откройте бота, чтобы посмотреть историю цен или отключить отслеживание.</i>"
                        )

                        # Отправляем уведомление
                        notified = False
                        try:
                            await bot.send_message(chat_id=tracking.user_id, text=text)
                            notified = True
                        except Exception as e:
                            logger.error(f"Не удалось отправить уведомление пользователю {tracking.user_id}: {e}")

                        # Обновляем цены в базе
                        if notified:
                            await tracked_repository.update_prices(
                                session=session,
                                tracked_id=tracking.id,
                                last_seen_price=current_price,
                                last_notified_price=current_price
                            )
                        else:
                            # Даже если не удалось уведомить (например, бот заблокирован),
                            # обновляем last_seen_price, чтобы не спамить потом, если он разблокирует.
                            await tracked_repository.update_prices(
                                session=session,
                                tracked_id=tracking.id,
                                last_seen_price=current_price,
                                last_notified_price=tracking.last_notified_price
                            )

                except Exception as e:
                    logger.error(f"Ошибка при обработке отслеживания {tracking.id}: {e}")

            logger.info("Проверка цен успешно завершена.")

    except Exception as e:
        logger.error(f"Глобальная ошибка в задаче run_price_tracking: {e}")
    finally:
        await bot.session.close()


@app.task
def check_tracked_prices():
    """
    Синхронная обертка для Celery beat.
    Запускает асинхронную логику проверки цен.
    """
    asyncio.run(run_price_tracking())
