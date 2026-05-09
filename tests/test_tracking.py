import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import uuid
from bot.handlers.tracking import process_track_callback
from aiogram.types import CallbackQuery, User

@pytest.mark.asyncio
async def test_track_product():
    callback = MagicMock(spec=CallbackQuery)
    callback.data = "t:short_id_123"
    callback.from_user = MagicMock(spec=User)
    callback.from_user.id = 12345
    callback.answer = AsyncMock()
    
    with patch("bot.handlers.tracking.redis_store") as mock_redis, \
         patch("bot.handlers.tracking.wol_api_client") as mock_wol, \
         patch("bot.handlers.tracking.tracked_repository") as mock_repo, \
         patch("bot.handlers.tracking.async_session_maker"):
         
        mock_redis.get_full_id = AsyncMock(return_value=str(uuid.uuid4()))
        mock_wol.get_product = AsyncMock(return_value={"price": 1000.0, "brand": "Apple", "model": "iPhone 17"})
        mock_repo.add_or_update_tracking = AsyncMock(return_value=MagicMock())
        
        await process_track_callback(callback)
        
        mock_redis.get_full_id.assert_called_with("short_id_123")
        mock_wol.get_product.assert_called_once()
        mock_repo.add_or_update_tracking.assert_called_once()
        callback.answer.assert_called_with("✅ Товар успешно добавлен в отслеживаемые!", show_alert=True)

