"""MTProto Proxy Manager — monitors ProxyMTProto channel, tests & rotates proxies."""
from __future__ import annotations

import asyncio
import re
import structlog
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = structlog.get_logger(__name__)

PROXY_CHANNEL = "ProxyMTProto"

MTProto_Proxy = tuple  # (host, port, secret)


@dataclass
class ProxyEntry:
    host: str
    port: int
    secret: str
    alive: bool = True
    last_check: Optional[datetime] = None
    source: str = "init"

    @property
    def as_mtproto(self) -> MTProto_Proxy:
        return ("mtproto", self.host, self.port, self.secret)

    @property
    def as_dict(self) -> dict:
        return {
            "host": self.host, "port": self.port,
            "secret": self.secret, "alive": self.alive,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "source": self.source,
        }


# regex: proxy ip:port secret   OR   server:port:secret
_PROXY_RE = re.compile(
    r"(?:proxy\s+)?"
    r"([\w.\-]+)\s*[:\s]\s*(\d{2,5})\s*[:\s]\s*([0-9a-fA-F]{32,64})",
    re.IGNORECASE,
)

_DEFAULT_PROXIES = [
    ProxyEntry("proxy.chunkycorp.shop", 443,
               "ee3a3365be03d6bc13518d65e70a3146c2706574726f766963682e7275",
               source="init"),
]


class ProxyManager:
    def __init__(self) -> None:
        self.proxies: list[ProxyEntry] = list(_DEFAULT_PROXIES)
        self._current_idx = 0
        self._lock = asyncio.Lock()

    @property
    def current(self) -> Optional[ProxyEntry]:
        alive = [p for p in self.proxies if p.alive]
        if not alive:
            return None
        return alive[self._current_idx % len(alive)]

    @property
    def current_proxy(self) -> Optional[MTProto_Proxy]:
        c = self.current
        return c.as_mtproto if c else None

    async def rotate(self) -> Optional[MTProto_Proxy]:
        async with self._lock:
            alive = [p for p in self.proxies if p.alive]
            if not alive:
                logger.error("No alive proxies!")
                return None
            self._current_idx = (self._current_idx + 1) % len(alive)
            p = alive[self._current_idx]
            logger.info("Rotated proxy", host=p.host, port=p.port)
            return p.as_mtproto

    async def mark_dead(self, proxy: MTProto_Proxy) -> None:
        async with self._lock:
            for p in self.proxies:
                if p.host == proxy[1] and p.port == proxy[2]:
                    p.alive = False
                    logger.warning("Marked proxy dead", host=p.host, port=p.port)
                    break

    async def mark_alive(self, proxy: MTProto_Proxy) -> None:
        async with self._lock:
            for p in self.proxies:
                if p.host == proxy[1] and p.port == proxy[2]:
                    p.alive = True
                    p.last_check = datetime.utcnow()
                    break

    def _parse_proxies(self, text: str, source: str = "channel") -> list[ProxyEntry]:
        found = []
        for m in _PROXY_RE.finditer(text):
            host, port, secret = m.group(1), int(m.group(2)), m.group(3)
            if host.lower() in ("server", "proxy"):
                continue
            if not any(p.host == host and p.port == port for p in self.proxies):
                found.append(ProxyEntry(host, port, secret, source=source))
        return found

    async def ingest_message(self, text: str) -> int:
        new = self._parse_proxies(text)
        if new:
            async with self._lock:
                self.proxies.extend(new)
            for p in new:
                logger.info("New proxy discovered", host=p.host, port=p.port, source=p.source)
        return len(new)

    async def test_proxy(self, proxy: ProxyEntry, test_phone: str = None) -> bool:
        try:
            from telethon import TelegramClient
            client = TelegramClient(
                None, 0, 0,
                proxy=proxy.as_mtproto,
            )
            await asyncio.wait_for(client.connect(), timeout=10)
            ok = client.is_connected()
            await client.disconnect()
            return ok
        except Exception as e:
            logger.debug("Proxy test failed", host=proxy.host, error=str(e))
            return False

    async def health_check_all(self) -> None:
        logger.info("Starting proxy health check", count=len(self.proxies))
        for proxy in self.proxies:
            ok = await self.test_proxy(proxy)
            proxy.alive = ok
            proxy.last_check = datetime.utcnow()
            logger.info("Proxy check", host=proxy.host, alive=ok)

    def get_all(self) -> list[dict]:
        return [p.as_dict for p in self.proxies]


proxy_manager = ProxyManager()
