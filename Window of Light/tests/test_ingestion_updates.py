from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingestion.telegram_client import TelegramIngestionService  # noqa: E402


class _FakeEvent:
    def __init__(self, message, chat_id: int):
        self.message = message
        self._chat = SimpleNamespace(id=chat_id)

    async def get_chat(self):
        return self._chat


def test_edited_message_is_reprocessed_for_monitored_channel():
    service = TelegramIngestionService(parser_service=None)
    service._running = True
    monitor = SimpleNamespace(chat_id=42, last_message_id=10)
    service.monitors = {42: monitor}

    calls = []

    async def fake_process(message, current_monitor):
        calls.append((message.id, current_monitor.chat_id))

    service._process_single_message = fake_process

    message = SimpleNamespace(id=7, text="edited", date=datetime(2026, 5, 18, 12, 0, 0))
    event = _FakeEvent(message, 42)

    asyncio.run(service._handle_edited_message(event))

    assert calls == [(7, 42)]
    assert monitor.last_message_id == 10


def test_edited_message_advances_last_message_id_when_needed():
    service = TelegramIngestionService(parser_service=None)
    service._running = True
    monitor = SimpleNamespace(chat_id=42, last_message_id=10)
    service.monitors = {42: monitor}

    async def fake_process(message, current_monitor):
        return None

    service._process_single_message = fake_process

    message = SimpleNamespace(id=11, text="edited", date=datetime(2026, 5, 18, 12, 0, 0))
    event = _FakeEvent(message, 42)

    asyncio.run(service._handle_edited_message(event))

    assert monitor.last_message_id == 11


def test_process_single_message_prefers_edit_date_for_timestamp():
    parsed_messages = []

    class _FakeParserService:
        async def parse_raw_message(self, raw_message):
            parsed_messages.append(raw_message)
            return []

    class _FakeMessage:
        def __init__(self):
            self.id = 99
            self.text = "updated iphone prices"
            self.date = datetime(2026, 1, 10, 7, 52, 45)
            self.edit_date = datetime(2026, 5, 18, 12, 53, 2)

        async def get_chat(self):
            return SimpleNamespace(username="top_resale", id=42)

    service = TelegramIngestionService(parser_service=_FakeParserService())
    monitor = SimpleNamespace(chat_id=42)

    asyncio.run(service._process_single_message(_FakeMessage(), monitor))

    assert len(parsed_messages) == 1
    assert parsed_messages[0].timestamp == datetime(2026, 5, 18, 12, 53, 2)
