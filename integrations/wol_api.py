import logging
from typing import Any, Dict, List, Optional
import httpx

from config import settings

logger = logging.getLogger(__name__)


class WolApiClient:
    """
    Async-клиент Window of Light API.

    Использует shared httpx.AsyncClient для переиспользования TCP-соединений
    между запросами. Клиент создаётся лениво при первом обращении и должен
    быть закрыт через aclose() при остановке приложения.
    """

    def __init__(self):
        self.base_url = settings.wol_api_base_url.rstrip("/")
        self.timeout = settings.wol_api_timeout_seconds
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def _request(self, method: str, endpoint: str, **kwargs) -> Optional[Any]:
        path = "/" + endpoint.lstrip("/")
        try:
            response = await self.client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTPStatusError {e.response.status_code} for {path}: {e.response.text}")
        except httpx.RequestError as e:
            logger.error(f"RequestError while requesting {path}: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error while requesting {path}: {str(e)}")

        return None

    async def check_health(self) -> bool:
        """Check API availability."""
        try:
            response = await self.client.get("/health")
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
