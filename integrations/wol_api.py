import logging
from typing import Any, Dict, List, Optional
import httpx

from config import settings

logger = logging.getLogger(__name__)


class WolApiClient:
    def __init__(self):
        self.base_url = settings.wol_api_base_url
        self.timeout = settings.wol_api_timeout_seconds

    async def _request(self, method: str, endpoint: str, **kwargs) -> Optional[Any]:
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.request(method, url, **kwargs)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTPStatusError {e.response.status_code} for {url}: {e.response.text}")
            except httpx.RequestError as e:
                logger.error(f"RequestError while requesting {url}: {str(e)}")
            except Exception as e:
                logger.error(f"Unexpected error while requesting {url}: {str(e)}")

        return None

    async def check_health(self) -> bool:
        """Check API availability."""
        url = f"{self.base_url.rstrip('/')}/health"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(url)
                return response.status_code == 200
            except Exception as e:
                logger.error(f"Health check failed: {str(e)}")
                return False

    async def get_status(self) -> Optional[Dict]:
        return await self._request("GET", "/status")

    async def search_products(self, payload: Dict[str, Any]) -> Optional[Dict]:
        """
        Search products with structured criteria.
        Payload example:
        {
            "category_id": "smartphones",
            "brand": "Apple",
            "model": "iPhone 17 Pro Max",
            "min_price": null,
            "max_price": null,
            "attributes": {
                "storage": "256GB"
            },
            "limit": 10,
            "offset": 0
        }
        """
        return await self._request("POST", "/api/v1/products/search", json=payload)

    async def get_product(self, product_id: str) -> Optional[Dict]:
        return await self._request("GET", f"/api/v1/products/{product_id}")

    async def get_product_history(self, product_id: str) -> Optional[Dict]:
        return await self._request("GET", f"/api/v1/products/{product_id}/history")

    async def get_raw_post(self, post_id: str) -> Optional[Dict]:
        return await self._request("GET", f"/api/v1/raw-posts/{post_id}")

    async def get_categories(self) -> Optional[List[Dict]]:
        return await self._request("GET", "/api/v1/categories")


wol_api_client = WolApiClient()
