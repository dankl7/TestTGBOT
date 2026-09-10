from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.database import Database  # noqa: E402
from common.models import SearchCriteria  # noqa: E402
from storage.repository import ProductRepository  # noqa: E402


class _FakeResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _FakeSession:
    def __init__(self):
        self.query = None

    def execute(self, query):
        self.query = query
        return _FakeResult()


def test_product_repository_search_keeps_zero_price_bounds():
    session = _FakeSession()
    repo = ProductRepository(session)
    criteria = SearchCriteria(
        category_id=None,
        brand=None,
        model=None,
        min_price=0,
        max_price=0,
        attributes={},
        limit=10,
        offset=0,
    )

    asyncio.run(repo.search(criteria))

    sql = str(session.query)
    assert "products.price >=" in sql
    assert "products.price <=" in sql


def test_product_repository_search_clamps_negative_pagination():
    session = _FakeSession()
    repo = ProductRepository(session)
    criteria = SearchCriteria(
        category_id=None,
        brand=None,
        model=None,
        min_price=None,
        max_price=None,
        attributes={},
        limit=-5,
        offset=-7,
    )

    asyncio.run(repo.search(criteria))

    compiled = str(session.query)
    assert "LIMIT" in compiled
    assert "OFFSET" in compiled


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        return self

    def first(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value


class _FakeDBSession:
    def __init__(self, existing=None):
        self.existing = existing
        self.added = []
        self.committed = False

    def execute(self, query):
        return _FakeScalarResult(self.existing)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed = True

    def rollback(self):
        raise AssertionError("rollback should not be called")

    def close(self):
        return None


def test_database_save_product_updates_existing_product_by_message_link():
    existing = SimpleNamespace(
        id="prod_existing",
        category_id="smartphones",
        brand="Apple",
        model="iPhone 17 Pro",
        price=90000.0,
        attributes={"storage": "256GB"},
        source_channel="best",
        timestamp=datetime(2026, 5, 1, 10, 0, 0),
        raw_message_id=None,
    )
    fake_session = _FakeDBSession(existing=existing)
    db = Database.__new__(Database)
    db.session = fake_session
    db.redis = None

    saved_id = asyncio.run(
        db.save_product(
            product_id="prod_new",
            category_id="smartphones",
            brand="Apple",
            model="iPhone 17 Pro",
            price=87500.0,
            attributes={"storage": "256GB", "color": "Black"},
            source_channel="best",
            message_link="https://t.me/test/1#p=1",
            timestamp=datetime(2026, 5, 18, 12, 0, 0),
        )
    )

    assert saved_id == "prod_existing"
    assert existing.price == 87500.0
    assert existing.attributes == {"storage": "256GB", "color": "Black"}
    assert existing.timestamp == datetime(2026, 5, 18, 12, 0, 0)
    assert fake_session.committed is True
    assert len(fake_session.added) == 1
    assert fake_session.added[0].product_id == "prod_existing"
