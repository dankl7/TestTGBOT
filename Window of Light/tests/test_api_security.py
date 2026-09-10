"""Security-focused tests for ``common.api_security``.

Covers the security primitives that the API endpoints rely on:
  * API key hashing (no plaintext at rest, deterministic SHA-256)
  * CORS origin filtering (wildcards are never returned, defaults to loopback)
  * Rate limiter behaviour
  * Body-size cap enforcement
  * Security headers middleware output
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import api_security  # noqa: E402


# ─── API key hashing ───────────────────────────────────────────────────────


def test_hash_api_key_matches_sha256():
    raw = "wok_deadbeef"
    assert api_security.hash_api_key(raw) == hashlib.sha256(raw.encode()).hexdigest()


def test_hash_api_key_changes_with_input():
    assert api_security.hash_api_key("a") != api_security.hash_api_key("b")


def test_hash_api_key_length_is_64_hex():
    h = api_security.hash_api_key("wok_test")
    assert len(h) == 64
    int(h, 16)  # raises if not hex


# ─── CORS origin filtering ─────────────────────────────────────────────────


def test_cors_default_is_loopback(monkeypatch):
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    origins = sorted(api_security.get_cors_origins())
    assert origins == sorted(["http://localhost:8002", "http://127.0.0.1:8002"])


def test_cors_strips_wildcard(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")
    assert "*" not in api_security.get_cors_origins()


def test_cors_filters_wildcard_among_real_origins(monkeypatch):
    monkeypatch.setenv(
        "CORS_ALLOWED_ORIGINS", "https://app.example.com, *, http://127.0.0.1:3000"
    )
    assert api_security.get_cors_origins() == [
        "https://app.example.com",
        "http://127.0.0.1:3000",
    ]


# ─── Rate limiter ───────────────────────────────────────────────────────────


def test_rate_limiter_enforces_max_requests():
    rl = api_security._SlidingWindow(max_requests=2, window_s=60)
    assert rl.hit("k1") is True
    assert rl.hit("k1") is True
    assert rl.hit("k1") is False  # 3rd over the cap


def test_rate_limiter_is_per_key():
    rl = api_security._SlidingWindow(max_requests=1, window_s=60)
    assert rl.hit("k1") is True
    assert rl.hit("k2") is True
    assert rl.hit("k1") is False  # k1 already at cap


# ─── Body size cap ─────────────────────────────────────────────────────────


def test_max_body_bytes_is_one_mib():
    assert api_security.MAX_BODY_BYTES == 1024 * 1024


# ─── Security headers middleware ──────────────────────────────────────────


def _app_with_security_headers() -> FastAPI:
    app = FastAPI()
    app.add_middleware(api_security.SecurityHeadersMiddleware)

    @app.get("/")
    def root():
        return {"ok": True}

    return app


def test_security_headers_present_on_get():
    client = TestClient(_app_with_security_headers())
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    # Permissions-Policy should at least disable the dangerous features.
    pp = resp.headers.get("Permissions-Policy", "")
    assert "geolocation=()" in pp
    assert "camera=()" in pp


# ─── require_api_key behaviour ─────────────────────────────────────────────


def test_require_api_key_rejects_missing_header():
    """When no X-API-Key is sent, FastAPI should respond 401/403."""
    from services import run_combined  # imported late to avoid DB at import

    app = run_combined.app
    # Ensure no override is active
    app.dependency_overrides.pop(api_security.require_api_key, None)
    client = TestClient(app)
    resp = client.get("/api/v1/channels/")
    assert resp.status_code in (401, 403)
