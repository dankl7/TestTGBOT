import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from database.models import UserSearchHistory
import uuid
from datetime import datetime
from bot.handlers.history import _show_history, process_delete_history, process_repeat_search
from aiogram.types import Message, CallbackQuery, User

@pytest.fixture
def mock_history_record():
    record = MagicMock(spec=UserSearchHistory)
    record.id = 1
    record.user_id = 12345
    record.query = "test query"
    record.normalized_query = "Test Query"
    record.product_id = uuid.uuid4()
    record.final_price = 100.0
    record.results_count = 1
    record.created_at = datetime.now()
    return record

@pytest.mark.asyncio
async def test_history_sorting_and_actual_price(mock_history_record):
    message_mock = MagicMock(spec=Message)
    message_mock.answer = AsyncMock()
    
    with patch("bot.handlers.history.history_repository") as mock_repo, \
         patch("bot.handlers.history.wol_api_client") as mock_wol, \
         patch("bot.handlers.history.async_session_maker"):
         
        record1 = mock_history_record
        record2 = MagicMock(spec=UserSearchHistory)
        record2.id = 2
        record2.user_id = 12345
        record2.query = "old query"
        record2.normalized_query = "Old Query"
        record2.product_id = uuid.uuid4()
        record2.final_price = 50.0
        record2.results_count = 1
        record2.created_at = datetime.now()
        
        mock_repo.get_user_history = AsyncMock(return_value=[record1, record2])
        
        async def mock_get_product(pid):
            if pid == str(record1.product_id):
                return {"price": 150.0}
            elif pid == str(record2.product_id):
                return {"price": 40.0}
            return None
            
        mock_wol.get_product = AsyncMock(side_effect=mock_get_product)
        
        await _show_history(message_mock, 12345, edit=False)
        
        assert message_mock.answer.call_count == 1
        call_args = message_mock.answer.call_args[0][0]
        assert "150" in call_args
        assert "40" in call_args

@pytest.mark.asyncio
async def test_history_delete(mock_history_record):
    callback_mock = MagicMock(spec=CallbackQuery)
    callback_mock.data = "hd:1"
    callback_mock.from_user = MagicMock(spec=User)
    callback_mock.from_user.id = 12345
    callback_mock.answer = AsyncMock()
    callback_mock.message = MagicMock()
    callback_mock.message.edit_text = AsyncMock()
    
    with patch("bot.handlers.history.history_repository") as mock_repo, \
         patch("bot.handlers.history.async_session_maker"):
         
        mock_repo.delete_record = AsyncMock(return_value=True)
        mock_repo.get_user_history = AsyncMock(return_value=[])
        
        await process_delete_history(callback_mock)
        
        mock_repo.delete_record.assert_called_once()
        callback_mock.answer.assert_called_with("✅ Запись удалена.")

@pytest.mark.asyncio
async def test_history_repeat():
    callback_mock = MagicMock(spec=CallbackQuery)
    callback_mock.data = "r:1"
    callback_mock.from_user = MagicMock(spec=User)
    callback_mock.from_user.id = 12345
    callback_mock.answer = AsyncMock()
    callback_mock.message = MagicMock()
    callback_mock.message.answer = AsyncMock()
    callback_mock.message.chat = MagicMock()
    callback_mock.message.chat.id = 777
    callback_mock.bot = MagicMock()
    
    mock_record = MagicMock()
    mock_record.user_id = 12345
    mock_record.query = "repeat me"
    
    with patch("bot.handlers.history.history_repository") as mock_repo, \
         patch("bot.handlers.history.async_session_maker"), \
         patch("bot.handlers.search.build_search_response", new_callable=AsyncMock) as mock_build, \
         patch("bot.handlers.history.cleanup_service.register_message", new_callable=AsyncMock) as mock_cleanup:
         
        mock_repo.get_record = AsyncMock(return_value=mock_record)
        mock_build.return_value = ("Search Results", MagicMock(), "token")
        
        await process_repeat_search(callback_mock)
        
        mock_build.assert_called_once_with("repeat me", 12345, 0)
        callback_mock.message.answer.assert_called_once()
        mock_cleanup.assert_called_once()
