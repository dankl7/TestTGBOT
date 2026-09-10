"""Async service that turns raw Telegram posts into persisted products."""
from __future__ import annotations

from typing import List, Optional

import structlog

from common.models import ParsedProduct, RawMessage

from .universal_parser import parse_products

logger = structlog.get_logger(__name__)


async def _invalidate_search_cache(db: Optional["Database"]) -> None:
    """Fresh Telegram posts should not wait for search-cache TTL expiry."""
    if db is None:
        return
    redis_client = getattr(db, "redis", None)
    if redis_client is None:
        return
    try:
        keys = await redis_client.keys("wol:search:*")
        if keys:
            await redis_client.delete(*keys)
    except Exception as exc:
        logger.warning("search cache invalidation failed", error=str(exc))


class ParserService:
    """Coordinates parsing + persistence for raw Telegram messages."""

    def __init__(self) -> None:
        self.products_parsed = 0

    async def parse_raw_message(self, raw_message: RawMessage) -> List[ParsedProduct]:
        """Parse one raw post and persist every product found.

        Returns the list of products extracted (may be empty).  The function
        never raises: persistence errors are logged but do not abort the batch.
        """
        if not raw_message.text or len(raw_message.text.strip()) < 5:
            return []

        products = parse_products(raw_message)
        if not products:
            return []

        await self._save_batch(products)
        self.products_parsed += len(products)
        return products

    async def _save_batch(self, products: List[ParsedProduct]) -> None:
        """Persist a batch of products through the normaliser + DB layer."""
        try:
            from common.database import Database
            from services.normalizer import NormalizerService
        except ImportError as exc:  # pragma: no cover - DB optional in tests
            logger.warning("storage layer unavailable", error=str(exc))
            return

        try:
            db = Database()
        except Exception as exc:  # pragma: no cover - DB optional in tests
            logger.warning("DB connection failed, skipping save", error=str(exc))
            return

        try:
            changed = False
            for product in products:
                normalized = NormalizerService.normalize_product(product)
                try:
                    saved_id = await db.save_product(
                        product_id=normalized.id,
                        category_id=normalized.category_id,
                        brand=normalized.brand,
                        model=normalized.model,
                        price=normalized.price,
                        attributes=normalized.attributes,
                        source_channel=normalized.source_channel,
                        message_link=normalized.message_link,
                        timestamp=normalized.timestamp,
                    )
                    if saved_id:
                        changed = True
                except Exception as exc:
                    logger.error(
                        "failed to save product",
                        brand=normalized.brand,
                        model=normalized.model,
                        error=str(exc),
                    )
            if changed:
                await _invalidate_search_cache(db)
        finally:
            try:
                await db.close()
            except Exception:
                pass
