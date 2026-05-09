import json
import logging
import hashlib
from typing import Optional, Dict, Any

from redis.asyncio import Redis

from config import settings
from services.normalizer import normalizer
from services.query_router import query_router
from integrations.wol_api import wol_api_client
from database.session import async_session_maker
from database.repositories.history import history_repository
from schemas.product import SearchResultDTO, ProductDTO

logger = logging.getLogger(__name__)

class SearchService:
    def __init__(self):
        self.redis = Redis.from_url(settings.redis_url, decode_responses=True)

    async def _get_cached_search(self, cache_key: str) -> Optional[Dict[str, Any]]:
        try:
            cached = await self.redis.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception as e:
            logger.error(f"Redis cache read error: {e}")
        return None

    async def _set_cached_search(self, cache_key: str, data: Dict[str, Any]) -> None:
        try:
            await self.redis.set(
                cache_key,
                json.dumps(data),
                ex=settings.search_cache_ttl_seconds
            )
        except Exception as e:
            logger.error(f"Redis cache write error: {e}")

    async def search(self, query: str, user_id: int, page: int = 0) -> SearchResultDTO:
        # 1. Normalize query
        norm_result = normalizer.normalize(query)
        normalized_text = norm_result.normalized_query

        # 2. Build request for WOL API
        # Fetch page_size + 1 to determine if there is a next page
        limit = settings.search_page_size + 1
        offset = page * settings.search_page_size

        search_req = query_router.route(normalized_text, limit=limit, offset=offset)
        req_dict = search_req.model_dump(exclude_none=True)

        # 3. Check cache
        # Sort keys to ensure stable hash for identical requests
        req_hash = hashlib.md5(json.dumps(req_dict, sort_keys=True).encode()).hexdigest()
        cache_key = f"search:{req_hash}:{page}"

        raw_result = await self._get_cached_search(cache_key)

        if not raw_result:
            # 4. Call WOL API
            raw_result = await wol_api_client.search_products(req_dict)
            if raw_result is None:
                # API unavailable or error
                logger.warning(f"WOL API returned None for query '{query}'")
                raw_result = {"products": [], "count": 0}
            else:
                await self._set_cached_search(cache_key, raw_result)

        # 5. Process results
        products_data = raw_result.get("products", [])

        # Check if we have a next page
        has_next_page = len(products_data) > settings.search_page_size

        # Trim the extra item requested for pagination check
        if has_next_page:
            products_data = products_data[:settings.search_page_size]

        products = []
        for p in products_data:
            # Construct a reasonable title
            brand = p.get("brand") or ""
            model = p.get("model") or ""
            title = f"{brand} {model}".strip()

            products.append(ProductDTO(
                id=p.get("id"),
                title=title,
                brand=brand,
                model=model,
                category_id=p.get("category_id"),
                source_channel=p.get("source_channel"),
                price=p.get("price"),
                attributes=p.get("attributes", {}),
                raw_post_id=p.get("raw_post_id"),
                message_link=p.get("message_link"),
            ))

        # 6. Save history
        try:
            async with async_session_maker() as session:
                await history_repository.add_record(
                    session=session,
                    user_id=user_id,
                    query=query,
                    normalized_query=normalized_text,
                    results_count=len(products),
                    metadata={"page": page, "has_next_page": has_next_page}
                )
        except Exception as e:
            logger.error(f"Error saving search history: {e}")

        # Calculate a pseudo-total to aid frontend pagination logic if API count is localized
        total_items = raw_result.get("count", len(products))
        if has_next_page and total_items <= len(products):
            total_items = offset + len(products) + 1

        return SearchResultDTO(
            query=query,
            normalized_query=normalized_text,
            items=products,
            total=total_items,
            page=page,
            page_size=settings.search_page_size
        )

search_service = SearchService()
