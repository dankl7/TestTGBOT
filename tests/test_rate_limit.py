import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from bot.middlewares.rate_limit import RateLimitMiddleware
from aiogram.types import Message, User, Chat
import time

@pytest.fixture
def message_mock():
    msg = MagicMock(spec=Message)
    msg.text = "iphone"
    msg.from_user = MagicMock(spec=User)
    msg.from_user.id = 12345
    msg.answer = AsyncMock()
    return msg

@pytest.fixture
def handler_mock():
    return AsyncMock()

@pytest.mark.asyncio
async def test_rate_limit(message_mock, handler_mock):
    with patch('bot.middlewares.rate_limit.Redis') as mock_redis_cls:
        mock_redis = AsyncMock()
        mock_redis_cls.from_url.return_value = mock_redis
        
        middleware = RateLimitMiddleware()
        middleware.rate_limit = 10
        middleware.redis = mock_redis
        
        # Simulate first 10 requests
        mock_redis.incr.side_effect = list(range(1, 12))
        
        for i in range(10):
            await middleware(handler_mock, message_mock, {})
            assert handler_mock.call_count == i + 1
            
        # 11th request should be blocked
        await middleware(handler_mock, message_mock, {})
        assert handler_mock.call_count == 10
        message_mock.answer.assert_called_once_with("Слишком много запросов. Попробуйте через N секунд.")

