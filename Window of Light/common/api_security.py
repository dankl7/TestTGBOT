"""API authentication and request-hardening for the Window of Light API.

Implements:
- API-key based authentication via the ``X-API-Key`` header.
- Per-key rate limiting (in-memory sliding window; replace with Redis in prod).
- A request-size guardrail that rejects bodies larger than ``MAX_BODY_BYTES``.
- Optional CORS origin allow-list (configured via env, not ``*``).
- Security headers (HSTS-ready, frame-deny, no-sniff, referrer policy).

Keys are stored as SHA-256 hashes in the ``api_keys`` table; the bootstrap
keys (if any) are loaded from the ``API_BOOTSTRAP_KEYS`` env var and auto-inserted
on first start so that the bot can authenticate immediately.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from collections import deque
from threading import Lock
from typing import Iterable, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from common.config import settings
from common.database import APIKey, SessionLocal

logger = logging.getLogger(__name__)

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

MAX_BODY_BYTES = 1 * 1024 * 1024  # 1 MiB hard cap on request bodies

# Per-key sliding-window rate limit. Defaults to 60 req / 60 s.
RATE_LIMIT_REQUESTS = int(os.getenv("WOL_RATE_LIMIT_REQUESTS", "60"))
RATE_LIMIT_WINDOW_S = int(os.getenv("WOL_RATE_LIMIT_WINDOW_S", "60"))


# ─── Helpers ────────────────────────────────────────────────────────────────


def hash_api_key(raw_key: str) -> str:
    """Return a SHA-256 hex digest of the raw key."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _lookup_key_hash(session: Session, raw_key: str) -> Optional[APIKey]:
    if not raw_key:
        return None
    digest = hash_api_key(raw_key)
    return (
        session.query(APIKey)
        .filter(APIKey.key_hash == digest, APIKey.is_active == True)  # noqa: E712
        .first()
    )


# ─── Rate limiter ───────────────────────────────────────────────────────────


class _SlidingWindow:
    """Thread-safe in-memory sliding-window limiter, keyed by API key hash."""

    def __init__(self, max_requests: int, window_s: int) -> None:
        self.max_requests = max_requests
        self.window_s = window_s
        self._buckets: dict[str, deque[float]] = {}
        self._lock = Lock()

    def hit(self, key: str) -> bool:
        """Return True if the request is allowed, False if it should be rejected."""
        now = time.monotonic()
        cutoff = now - self.window_s
        with self._lock:
            bucket = self._buckets.setdefault(key, deque())
            # Drop expired entries from the left.
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.max_requests:
                return False
            bucket.append(now)
            return True


_rate_limiter = _SlidingWindow(RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW_S)


# ─── Bootstrap keys ─────────────────────────────────────────────────────────


def _split_origins(raw: str) -> list[str]:
    return [o.strip() for o in (raw or "").split(",") if o.strip()]


def get_cors_origins() -> list[str]:
    """Return the configured CORS origin list (never ``*``).

    Wildcards are explicitly dropped because the API supports
    ``allow_credentials=True`` and that combo is blocked by the CORS spec.
    """
    explicit = _split_origins(os.getenv("CORS_ALLOWED_ORIGINS", ""))
    if explicit:
        return [o for o in explicit if o != "*"]
    # Back-compat with the previous env var name.
    legacy = _split_origins(getattr(settings, "CORS_ALLOWED_ORIGINS", ""))
    if legacy:
        return [o for o in legacy if o != "*"]
    return ["http://localhost:8002", "http://127.0.0.1:8002"]


def bootstrap_api_keys() -> None:
    """Insert any plaintext keys from ``API_BOOTSTRAP_KEYS`` so the bot can auth.

    Each key is stored as a SHA-256 hash. If the key already exists (by hash) it
    is left untouched. The plaintext is never persisted.
    """
    raw = os.getenv("API_BOOTSTRAP_KEYS", "") or getattr(settings, "API_BOOTSTRAP_KEYS", "")
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        return

    session = SessionLocal()
    try:
        for raw_key in keys:
            digest = hash_api_key(raw_key)
            existing = (
                session.query(APIKey).filter(APIKey.key_hash == digest).first()
            )
            if existing:
                if not existing.is_active:
                    existing.is_active = True
                continue
            session.add(
                APIKey(
                    key_hash=digest,
                    name="bootstrap",
                    is_active=True,
                )
            )
            logger.info("Inserted bootstrap API key (hash=%s...)", digest[:12])
        session.commit()
    except Exception as exc:  # pragma: no cover - best-effort bootstrap
        session.rollback()
        logger.warning("API key bootstrap failed: %s", exc)
    finally:
        session.close()


# ─── FastAPI dependencies ───────────────────────────────────────────────────


def require_api_key(
    request: Request,
    api_key_header: Optional[str] = Depends(API_KEY_HEADER),
) -> APIKey:
    """Validate ``X-API-Key`` and apply per-key rate limiting."""
    # Body size guard — reject early before doing any DB work.
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_BODY_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Request body too large",
                )
        except ValueError:
            pass

    raw_key = api_key_header or request.query_params.get("api_key")
    if not raw_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
        )

    if not hmac.compare_digest(raw_key, raw_key):
        # Defensive: if compare_digest ever misbehaves on a non-str type.
        raise HTTPException(status_code=401, detail="Invalid API key")

    key_hash = hash_api_key(raw_key)
    if not _rate_limiter.hit(key_hash):
        logger.warning("Rate limit exceeded for api_key=%s...", key_hash[:12])
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
        )

    session = SessionLocal()
    try:
        record = _lookup_key_hash(session, raw_key)
        if record is None:
            logger.warning("Rejected unknown API key (hash=%s...)", key_hash[:12])
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )
        if record.expires_at is not None and record.expires_at < _now_utc():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key expired",
            )
        return record
    finally:
        session.close()


def _now_utc():
    from datetime import datetime
    return datetime.utcnow()


# ─── Security headers middleware ───────────────────────────────────────────


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


class SecurityHeadersMiddleware:
    """ASGI middleware that adds basic security headers to every response."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers", []))
                for name, value in SECURITY_HEADERS.items():
                    headers.append((name.lower().encode("latin-1"), value.encode("latin-1")))
                # Remove the Server header if Starlette added one.
                headers = [(n, v) for (n, v) in headers if n.lower() != b"server"]
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


# ─── Trusted-proxies helper (for future use) ───────────────────────────────


def trusted_proxies() -> Iterable[str]:
    """Return the list of CIDR/IP addresses allowed to set ``X-Forwarded-For``."""
    raw = os.getenv("TRUSTED_PROXIES", "127.0.0.1,::1")
    return [p.strip() for p in raw.split(",") if p.strip()]
