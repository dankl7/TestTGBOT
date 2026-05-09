import logging
from typing import Any, Awaitable, Callable, Dict
import time

from aiogram import BaseMiddleware
from aiogram.types import Message, Update
from redis.asyncio import Redis

from config import settings

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseMiddleware):
    """
    Middleware для ограничения количества поисковых запросов пользователя.
    Лимит: 10 запросов в минуту (настраивается в config).
    Не применяется к командам (начинаются с /) и callback-ам.
    """

    def __init__(self):
        super().__init__()
        self.redis = Redis.from_url(settings.redis_url, decode_responses=True)
        self.rate_limit = settings.rate_limit_per_minute
        self.ttl = 60

    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        # Определяем текстовое сообщение (иногда Update содержит Message, иногда нужно взять event.message)
        message: Message | None = None
        if isinstance(event, Message):
            message = event
        else:
            # В aiogram Update может приходить с полем `message` (Message) или `callback_query` и т.д.
            msg = getattr(event, "message", None)
            if isinstance(msg, Message):
                message = msg

        if message and message.text:
            # Игнорируем команды
            if message.text.startswith('/'):
                return await handler(event, data)

            user_id = message.from_user.id
            # Текущая минута (int)
            current_minute = int(time.time() // 60)

            key = f"rate:{user_id}:{current_minute}"

            try:
                # Увеличиваем счетчик
                current_count = await self.redis.incr(key)

                # Если это первый инкремент в эту минуту, ставим TTL
                if current_count == 1:
                    await self.redis.expire(key, self.ttl)

                # Проверяем лимит
                if current_count > self.rate_limit:
                    logger.info(f"User {user_id} exceeded rate limit")
                    # Сообщаем пользователю
                    await message.answer("Слишком много запросов. Попробуйте через N секунд.")
                    # Прерываем обработку
                    return
            except Exception as e:
                # Если Redis недоступен, логируем и продолжаем без лимита
                logger.error(f"Redis rate limit error: {e}")

        # Продолжаем обработку для остальных событий или если лимит не превышен
        return await handler(event, data)
