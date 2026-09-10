from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import run_combined  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    # Disable the X-API-Key dependency in the test client so the legacy
    # tests can hit protected endpoints without setting up a key.
    from common.api_security import require_api_key

    def _fake_require():
        return SimpleNamespace(id="test", key_hash="test", is_active=True, expires_at=None)

    app = run_combined.app
    # Override the dependency on the FastAPI app.
    app.dependency_overrides[require_api_key] = _fake_require
    return TestClient(app)


def test_health_endpoint_reports_degraded_database(client, monkeypatch):
    monkeypatch.setattr(run_combined, "_check_database_connection", lambda: False)
    monkeypatch.setattr(run_combined, "ingestion_service", None)
    monkeypatch.setattr(run_combined, "redis_client", None)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["dependencies"]["database"].startswith("error:")
    assert payload["dependencies"]["telegram"] == "not initialized"
    assert payload["dependencies"]["redis"] == "not initialized"


def test_status_endpoint_returns_not_ready_without_ingestion(client, monkeypatch):
    monkeypatch.setattr(run_combined, "ingestion_service", None)

    response = client.get("/status")

    assert response.status_code == 200
    assert response.json() == {"status": "not_ready"}


def test_protected_endpoints_reject_missing_api_key():
    """Without the X-API-Key header, protected endpoints return 401."""
    from common.api_security import require_api_key
    app = run_combined.app
    app.dependency_overrides.pop(require_api_key, None)
    raw_client = TestClient(app)

    for path, method in [
        ("/api/v1/channels/", "GET"),
        ("/api/v1/categories", "GET"),
        ("/api/v1/proxy/current", "GET"),
    ]:
        resp = raw_client.request(method, path)
        assert resp.status_code == 401, f"{method} {path} returned {resp.status_code}"


def test_security_headers_present_on_every_response():
    from common.api_security import require_api_key
    app = run_combined.app
    app.dependency_overrides.pop(require_api_key, None)
    raw_client = TestClient(app)

    for path in ["/health", "/status", "/"]:
        resp = raw_client.get(path)
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("Referrer-Policy") == "no-referrer"


@pytest.mark.asyncio
async def test_run_ingestion_forever_retries_after_initialize_failure(monkeypatch):
    events = []

    class FakeIngestion:
        def __init__(self):
            self.client = None
            self.initialize_calls = 0

        async def initialize(self):
            self.initialize_calls += 1
            events.append(f"initialize:{self.initialize_calls}")
            if self.initialize_calls == 1:
                raise RuntimeError("proxy down")
            self.client = object()

        async def add_channel(self, link, title):
            events.append(f"add:{link}:{title}")
            return True

        async def start_monitoring(self):
            events.append("start_monitoring")
            raise asyncio.CancelledError

        async def stop(self):
            events.append("stop")
            self.client = None

    async def fake_sleep(_seconds):
        events.append("sleep")

    monkeypatch.setattr(run_combined, "ingestion_service", FakeIngestion())
    monkeypatch.setattr(run_combined.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await run_combined._run_ingestion_forever([
            {"link": "channel_1", "title": "Channel 1"},
        ])

    assert events == [
        "initialize:1",
        "stop",
        "sleep",
        "initialize:2",
        "add:channel_1:Channel 1",
        "start_monitoring",
    ]


def test_status_endpoint_serializes_ingestion_counters(client, monkeypatch):
    fake_ingestion = SimpleNamespace(
        monitors={1: object(), 2: object()},
        messages_sent=12,
        messages_parsed=9,
    )
    fake_parser = SimpleNamespace(products_parsed=21)
    monkeypatch.setattr(run_combined, "ingestion_service", fake_ingestion)
    monkeypatch.setattr(run_combined, "parser_service", fake_parser)

    response = client.get("/status")

    assert response.status_code == 200
    assert response.json() == {
        "status": "running",
        "channels_monitored": 2,
        "messages_sent": 12,
        "messages_parsed": 9,
        "parser_products": 21,
    }


def test_channels_endpoint_returns_503_when_service_not_ready(client, monkeypatch):
    monkeypatch.setattr(run_combined, "ingestion_service", None)

    response = client.get("/api/v1/channels/")

    assert response.status_code == 503
    assert response.json()["error"] == "Service not ready"


def test_search_products_endpoint_serializes_results(client, monkeypatch):
    product = SimpleNamespace(
        id="p1",
        category_id="smartphones",
        brand="Apple",
        model="iPhone 17 Pro",
        price=99999.0,
        source_channel="best",
        message_link="https://t.me/test/1",
        timestamp=datetime(2025, 5, 1, 10, 0, 0),
        created_at=datetime(2025, 5, 1, 11, 0, 0),
        attributes={"storage": "256GB"},
    )

    class FakeProductRepository:
        def __init__(self, db):
            self.db = db

        async def search(self, criteria):
            assert criteria.brand == "Apple"
            assert criteria.model == "iPhone 17 Pro"
            return [product]

    monkeypatch.setattr(run_combined, "ProductRepository", FakeProductRepository)
    monkeypatch.setattr(run_combined, "get_db", lambda: iter([object()]))
    monkeypatch.setattr(run_combined, "redis_client", None)

    response = client.post(
        "/api/v1/products/search",
        json={"brand": "Apple", "model": "iPhone 17 Pro", "limit": 10, "offset": 0},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["products"][0]["id"] == "p1"
    assert payload["products"][0]["attributes"]["storage"] == "256GB"


def test_search_products_endpoint_returns_cached_payload_when_available(client, monkeypatch):
    cached_payload = {"count": 1, "offset": 0, "limit": 10, "products": [{"id": "cached"}]}

    async def fake_get_cached_search(cache_key):
        return cached_payload

    monkeypatch.setattr(run_combined, "_get_cached_search", fake_get_cached_search)
    monkeypatch.setattr(run_combined, "redis_client", object())

    response = client.post(
        "/api/v1/products/search",
        json={"brand": "Apple", "model": "iPhone 17 Pro", "limit": 10, "offset": 0},
    )

    assert response.status_code == 200
    assert response.json() == cached_payload


def test_get_product_endpoint_returns_404_for_missing_product(client, monkeypatch):
    class FakeProductRepository:
        def __init__(self, db):
            self.db = db

        async def get(self, product_id):
            return None

    monkeypatch.setattr(run_combined, "ProductRepository", FakeProductRepository)
    monkeypatch.setattr(run_combined, "get_db", lambda: iter([object()]))

    response = client.get("/api/v1/products/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "Product not found"


def test_get_product_history_endpoint_serializes_history(client, monkeypatch):
    history_item = SimpleNamespace(
        id="h1",
        price=98990.0,
        timestamp=datetime(2025, 5, 2, 9, 30, 0),
        source_channel="best",
    )

    class FakeProductRepository:
        def __init__(self, db):
            self.db = db

        async def get_price_history(self, product_id, limit, offset):
            assert product_id == "p1"
            assert limit == 5
            assert offset == 2
            return [history_item]

    monkeypatch.setattr(run_combined, "ProductRepository", FakeProductRepository)
    monkeypatch.setattr(run_combined, "get_db", lambda: iter([object()]))

    response = client.get("/api/v1/products/p1/history?limit=5&offset=2")

    assert response.status_code == 200
    payload = response.json()
    assert payload["product_id"] == "p1"
    assert payload["count"] == 1
    assert payload["history"][0]["id"] == "h1"
    assert payload["history"][0]["source_channel"] == "best"


def test_create_api_key_endpoint_returns_plain_key_but_stores_hash(client, monkeypatch):
    stored = {}

    class FakeAPIKey:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeSession:
        def add(self, obj):
            stored["obj"] = obj

        def commit(self):
            return None

        def refresh(self, obj):
            return None

    monkeypatch.setattr(run_combined, "get_db", lambda: iter([FakeSession()]))
    monkeypatch.setitem(sys.modules, "common.database", SimpleNamespace(APIKey=FakeAPIKey))

    response = client.post(
        "/api/v1/api-keys",
        json={"name": "Integration Key", "expires_days": 30},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["api_key"].startswith("wok_")
    assert payload["name"] == "Integration Key"
    assert stored["obj"].key_hash != payload["api_key"]
    assert stored["obj"].key_hash == run_combined._hash_api_key(payload["api_key"])
