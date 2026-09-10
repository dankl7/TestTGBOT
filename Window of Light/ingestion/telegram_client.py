"""Telegram MTProto ingestion service.

Streams messages from monitored channels and forwards them to the parser.
Streaming (vs. preloading the full history into memory) keeps memory usage
constant for channels with tens of thousands of posts and lets parsing happen
in parallel with downloading.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional, Set

import structlog
from telethon import TelegramClient, events

from common.config import settings
from common.models import RawMessage

logger = structlog.get_logger(__name__)


@dataclass
class _Monitor:
    chat_id: int
    username: str
    title: str
    last_message_id: int = 0
    processed_message_ids: Set[int] = field(default_factory=set)
    scan_complete: bool = False




async def _wait_for_file(path: str, label: str) -> str:
    """Block until *path* exists, then read & delete it, returning the content."""
    import os, asyncio as _aio
    logger.warning(
        f"Telegram {label} needed. Write the value to {path} inside the container."
    )
    while not os.path.exists(path):
        await _aio.sleep(2)
    with open(path, "r") as fh:
        value = fh.read().strip()
    try:
        os.remove(path)
    except OSError:
        pass
    return value


async def _file_code_callback() -> str:
    return await _wait_for_file("/tmp/tg_code", "login code")


async def _file_password_callback() -> str:
    return await _wait_for_file("/tmp/tg_password", "2FA password")


class TelegramIngestionService:
    def __init__(self, parser_service=None) -> None:
        self.parser_service = parser_service
        self.client: Optional[TelegramClient] = None
        self.monitors: dict[int, _Monitor] = {}
        self.messages_sent = 0
        self.messages_parsed = 0
        self._running = False
        self._scan_in_progress = False
        self._channel_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialise the Telethon client.  Idempotent."""
        if self.client is not None:
            return
        try:
            proxy = settings.telethon_proxy
            if proxy:
                logger.info(
                    "Telegram proxy enabled",
                    type=proxy[0], host=proxy[1], port=proxy[2],
                )
            self.client = TelegramClient(
                settings.TELEGRAM_SESSION,
                settings.TELEGRAM_API_ID,
                settings.TELEGRAM_API_HASH,
                proxy=proxy,
            )
            await self.client.start(
                phone=settings.TELEGRAM_PHONE,
                code_callback=_file_code_callback,
                password=_file_password_callback,
            )
            self.client.add_event_handler(self._handle_new_message, events.NewMessage())
            self.client.add_event_handler(self._handle_edited_message, events.MessageEdited())
            logger.info("Telegram client initialised")
        except Exception as exc:
            logger.error("Telegram init failed", error=str(exc))
            raise

    async def start_monitoring(self) -> None:
        """Start monitoring channels: full history scan, then live updates."""
        logger.info("Telegram ingestion: start monitoring")
        self._running = True
        await self.scan_history()
        if self.client is not None:
            await self.client.run_until_disconnected()

    async def scan_history(self) -> None:
        """Stream historical messages from each monitored channel.

        Messages are processed as they arrive, so memory stays bounded.  Each
        channel is scanned sequentially to respect the global flood-wait.
        """
        if self._scan_in_progress or self.client is None:
            return
        self._scan_in_progress = True
        logger.info("Full history scan starting", channels=len(self.monitors))
        try:
            for monitor in list(self.monitors.values()):
                await self._scan_one(monitor)
        finally:
            self._scan_in_progress = False

    async def _scan_one(self, monitor: _Monitor) -> None:
        processed = 0
        skipped = 0
        try:
            logger.info("Scanning channel", username=monitor.username)
            assert self.client is not None
            async for message in self.client.iter_messages(monitor.chat_id, limit=None):
                if message.id in monitor.processed_message_ids:
                    skipped += 1
                    continue
                await self._process_single_message(message, monitor)
                monitor.processed_message_ids.add(message.id)
                if message.id > monitor.last_message_id:
                    monitor.last_message_id = message.id
                processed += 1
            monitor.scan_complete = True
            # Free per-channel dedup memory after scan; no live handler path uses it.
            monitor.processed_message_ids.clear()
            logger.info(
                "Scan complete",
                username=monitor.username,
                processed=processed,
                skipped=skipped,
                sent=self.messages_sent,
                parsed=self.messages_parsed,
            )
        except Exception as exc:
            logger.error("Scan failed", username=monitor.username, error=str(exc))

    async def _process_single_message(self, message, monitor: _Monitor) -> None:
        if not message.text or len(message.text.strip()) < 5:
            return
        try:
            chat = await message.get_chat()
            channel_username = (
                getattr(chat, "username", None) or str(getattr(chat, "id", "unknown"))
            )
            message_link = f"https://t.me/{channel_username}/{message.id}"
            effective_timestamp = getattr(message, "edit_date", None) or message.date

            raw_message = RawMessage(
                id=f"msg_{message.id}",
                text=message.text,
                timestamp=effective_timestamp,
                channel_id=str(monitor.chat_id),
                message_link=message_link,
            )

            if self.parser_service is not None:
                products = await self.parser_service.parse_raw_message(raw_message)
                # Newer ParserService returns a list; older versions returned None.
                count = len(products) if products else 0
                self.messages_parsed += count
            self.messages_sent += 1
        except Exception as exc:
            logger.error("Error processing message", message_id=message.id, error=str(exc))

    async def _handle_new_message(self, event) -> None:
        if not self._running:
            return
        try:
            message = event.message
            if not message:
                return
            chat = await event.get_chat()
            chat_id = getattr(chat, "id", None)
            if chat_id is None:
                return
            monitor = self.monitors.get(chat_id)
            if monitor is None:
                return
            if message.id <= monitor.last_message_id:
                return

            await self._process_single_message(message, monitor)
            monitor.last_message_id = message.id
        except Exception as exc:
            logger.error("Live message handler failed", error=str(exc))

    async def _handle_edited_message(self, event) -> None:
        if not self._running:
            return
        try:
            message = event.message
            if not message:
                return
            chat = await event.get_chat()
            chat_id = getattr(chat, "id", None)
            if chat_id is None:
                return
            monitor = self.monitors.get(chat_id)
            if monitor is None:
                return

            await self._process_single_message(message, monitor)
            if message.id > monitor.last_message_id:
                monitor.last_message_id = message.id
        except Exception as exc:
            logger.error("Edited message handler failed", error=str(exc))

    async def add_channel(self, link: str, title: Optional[str] = None) -> bool:
        if self.client is None:
            return False
        async with self._channel_lock:
            try:
                entity = await self.client.get_entity(link)
                chat_id = entity.id
                username = getattr(entity, "username", None) or str(chat_id)
                if chat_id in self.monitors:
                    logger.info("Channel already monitored", username=username)
                    return False
                self.monitors[chat_id] = _Monitor(
                    chat_id=chat_id,
                    username=username,
                    title=title or username,
                )
                logger.info("Channel added", username=username, chat_id=chat_id)
                return True
            except Exception as exc:
                logger.error("Failed to add channel", link=link, error=str(exc))
                return False

    async def remove_channel(self, link: str) -> bool:
        if self.client is None:
            return False
        async with self._channel_lock:
            try:
                entity = await self.client.get_entity(link)
                if entity.id in self.monitors:
                    del self.monitors[entity.id]
                    logger.info("Channel removed", link=link)
                    return True
                logger.warning("Channel not monitored", link=link)
                return False
            except Exception as exc:
                logger.error("Failed to remove channel", link=link, error=str(exc))
                return False

    def get_monitored_channels(self):
        return [
            {
                "chat_id": m.chat_id,
                "id": m.chat_id,
                "username": m.username,
                "title": m.title,
                "link": f"https://t.me/{m.username}" if m.username and not m.username.startswith('+') else m.username,
                "last_message_id": m.last_message_id,
                "is_active": True,
                "scan_complete": m.scan_complete,
            }
            for m in self.monitors.values()
        ]

    async def stop(self) -> None:
        self._running = False
        if self.client is not None:
            await self.client.disconnect()
            self.client = None
        logger.info("Telegram monitoring stopped")
