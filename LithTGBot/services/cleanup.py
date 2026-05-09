import logging
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from redis.asyncio import Redis

from config import settings

logger = logging.getLogger(__name__)


class CleanupService:
    """
    Сервис для управления автоочисткой старых сообщений бота с результатами поиска.
    Оставляет не более заданного количества сообщений в чате (по умолчанию 3).
    """

    def __init__(self):
        self.redis = Redis.from_url(settings.redis_url, decode_responses=True)
        self.max_messages = settings.max_search_messages_per_chat
        self.ttl = 86400  # 24 часа

    async def register_message(self, bot: Bot, chat_id: int, message_id: int) -> None:
        """
        Регистрирует ID нового отправленного сообщения и при необходимости удаляет старые.

        Ошибки удаления не прерывают выполнение основного кода.
        """
        key = f"cleanup:{chat_id}"

        try:
            # Добавляем новый message_id в список
            await self.redis.rpush(key, message_id)
            # Обновляем срок жизни ключа
            await self.redis.expire(key, self.ttl)

            # Получаем текущую длину списка
            list_len = await self.redis.llen(key)

            # Пока сообщений больше лимита, удаляем самые старые
            while list_len > self.max_messages:
                old_message_id_str = await self.redis.lpop(key)
                if old_message_id_str:
                    try:
                        old_message_id = int(old_message_id_str)
                        await bot.delete_message(chat_id=chat_id, message_id=old_message_id)
                    except TelegramAPIError as e:
                        # Логируем как warning, не показываем пользователю и не падаем
                        logger.warning(
                            f"Не удалось удалить старое сообщение {old_message_id} "
                            f"в чате {chat_id}: {e.message}"
                        )
                    except Exception as e:
                        logger.warning(f"Непредвиденная ошибка при удалении сообщения: {e}")

                list_len -= 1

        except Exception as e:
            logger.error(f"Ошибка Redis при автоочистке сообщений для чата {chat_id}: {e}")

    async def clear_all(self, bot: Bot, chat_id: int) -> None:
        """
        Принудительно удаляет все сохраненные поисковые сообщения в чате.
        Полезно при сбросе состояния или команде /start.
        """
        key = f"cleanup:{chat_id}"

        try:
            while True:
                old_message_id_str = await self.redis.lpop(key)
                if not old_message_id_str:
                    break

                try:
                    await bot.delete_message(chat_id=chat_id, message_id=int(old_message_id_str))
                except TelegramAPIError:
                    pass  # Игнорируем ошибки при массовой очистке

        except Exception as e:
            logger.error(f"Ошибка Redis при полной очистке сообщений для чата {chat_id}: {e}")

    async def close(self):
        """Закрывает соединение с Redis."""
        await self.redis.aclose()


cleanup_service = CleanupService()
