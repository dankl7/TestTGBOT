from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import run_combined  # noqa: E402


def test_hash_api_key_is_not_plaintext():
    raw_key = "wok_test_key"
    hashed = run_combined._hash_api_key(raw_key)

    assert hashed != raw_key
    assert hashed == hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def test_check_database_connection_returns_false_on_error(monkeypatch):
    class BrokenConnection:
        def __enter__(self):
            raise RuntimeError("db down")

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_engine = MagicMock()
    fake_engine.connect.return_value = BrokenConnection()
    monkeypatch.setattr(run_combined, "engine", fake_engine)

    assert run_combined._check_database_connection() is False


def test_check_database_connection_executes_probe(monkeypatch):
    executed = []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, stmt):
            executed.append(str(stmt))

    fake_engine = MagicMock()
    fake_engine.connect.return_value = FakeConnection()
    monkeypatch.setattr(run_combined, "engine", fake_engine)

    assert run_combined._check_database_connection() is True
    assert executed == ["SELECT 1"]
