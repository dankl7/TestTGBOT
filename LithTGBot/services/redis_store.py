import json
import uuid
import logging
from typing import Optional, Dict, Any

from redis.asyncio import Redis

from config import settings

logger = logging.getLogger(__name__)


class RedisStore:
    """
    Управляет сохранением и извлечением коротких идентификаторов (short_id)
    для обхода ограничения Telegram на длину callback_data (64 байта).
    """
    def __init__(self):
        self.redis = Redis.from_url(settings.redis_url, decode_responses=True)

    async def generate_short_id(self, full_id: str) -> str:
        """
        Сохраняет полный UUID товара и возвращает короткий токен.
        Ключ: product_short:{short_id} (TTL: 86400 сек / 24 часа)
        """
        short_id = uuid.uuid4().hex[:8]
        key = f"product_short:{short_id}"

        try:
            await self.redis.set(key, full_id, ex=86400)
            return short_id
        except Exception as e:
            logger.error(f"Redis save error (generate_short_id): {e}")
            # Fallback: возвращаем оригинальный ID (может сломать callback, если слишком длинный)
            return full_id

    async def get_full_id(self, short_id: str) -> Optional[str]:
        """
        Извлекает полный UUID по короткому токену.
        """
        # Если это уже похож на UUID (в случае fallback), возвращаем как есть
        if len(short_id) > 8 and "-" in short_id:
            return short_id

        key = f"product_short:{short_id}"
        try:
            return await self.redis.get(key)
        except Exception as e:
            logger.error(f"Redis read error (get_full_id): {e}")
            return None

    async def save_query_token(self, query_data: Dict[str, Any]) -> str:
        """
        Сохраняет параметры запроса (для пагинации/повтора) и возвращает короткий токен.
        Ключ: query_token:{token} (TTL: 1800 сек / 30 минут)
        """
        token = uuid.uuid4().hex[:8]
        key = f"query_token:{token}"
        try:
            await self.redis.set(key, json.dumps(query_data), ex=1800)
            return token
        except Exception as e:
            logger.error(f"Redis save error (save_query_token): {e}")
            return ""

    async def get_query_data(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Извлекает сохраненные параметры запроса по короткому токену.
        """
        key = f"query_token:{token}"
        try:
            data = await self.redis.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.error(f"Redis read error (get_query_data): {e}")
        return None

    async def close(self):
        """Закрывает соединения с Redis."""
        await self.redis.aclose()


redis_store = RedisStore()
