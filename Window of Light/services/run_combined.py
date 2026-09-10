"""
Window of Light - Combined Service
Запускает Ingestion + Parser + Storage в одном процессе
"""
import asyncio
import structlog
import sys
import io

# Fix Windows console encoding for UTF-8
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
from pathlib import Path
import os
import uvicorn
import hashlib
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import yaml
from sqlalchemy import text
from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator
from redis.asyncio import Redis

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from common.config import settings
from common.database import engine, Base, get_db, APIKey
from common.models import SearchCriteria
from common.api_security import (
    SecurityHeadersMiddleware,
    bootstrap_api_keys,
    get_cors_origins,
    hash_api_key,
    require_api_key,
)
from ingestion.telegram_client import TelegramIngestionService
from parser.parser_service import ParserService
from storage.repository import ProductRepository, CategoryRepository
from services.proxy_manager import proxy_manager

logger = structlog.get_logger(__name__)

# Global state
db_ready = False

# FastAPI приложение
app = FastAPI(title="Window of Light")

# Security headers on every response (HSTS-ready, frame-deny, no-sniff, ...).
app.add_middleware(SecurityHeadersMiddleware)

# CORS — explicit origin allow-list (never "*" with credentials).
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["X-API-Key", "Content-Type", "Authorization"],
    max_age=600,
)

# Global services
ingestion_service = None
parser_service = None
channels_file = Path("config/channels.yaml")
redis_client: Optional[Redis] = None

# Pydantic models for API
class ProductSearchRequest(BaseModel):
    category_id: Optional[str] = Field(default=None, max_length=64)
    brand: Optional[str] = Field(default=None, max_length=128)
    model: Optional[str] = Field(default=None, max_length=256)
    min_price: Optional[float] = Field(default=None, ge=0)
    max_price: Optional[float] = Field(default=None, ge=0)
    attributes: Optional[Dict[str, Any]] = Field(
        default=None,
        max_length=32,  # at most 32 distinct attribute keys per search
    )
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0, le=100_000)

    @field_validator("attributes")
    @classmethod
    def _validate_attribute_keys(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if v is None:
            return v
        for k, val in v.items():
            if not isinstance(k, str) or not k or len(k) > 64:
                raise ValueError("attribute keys must be 1..64 char strings")
            if val is not None and not isinstance(val, (str, int, float, bool)):
                raise ValueError(f"attribute value for {k!r} must be scalar")
            if isinstance(val, str) and len(val) > 256:
                raise ValueError(f"attribute value for {k!r} too long")
        return v


class ProductResponse(BaseModel):
    id: str
    category_id: str
    brand: str
    model: str
    price: float
    source_channel: str
    message_link: str
    timestamp: datetime
    attributes: Dict[str, Any]


async def _safe_read_json(request: Request, max_bytes: int = 4096) -> dict:
    """Read a JSON body with a hard size cap, returning an empty dict on error."""
    from common.api_security import MAX_BODY_BYTES
    cap = min(max_bytes, MAX_BODY_BYTES)
    try:
        body = await request.body()
    except Exception:
        return {}
    if len(body) > cap:
        raise HTTPException(status_code=413, detail="Request body too large")
    if not body:
        return {}
    try:
        import json as _json
        return _json.loads(body)
    except Exception:
        return {}


def _hash_api_key(raw_key: str) -> str:
    return hash_api_key(raw_key)


def _check_database_connection() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.warning(f"⚠️ Database probe failed: {e}")
        return False


def _check_session_file_permissions() -> None:
    """Refuse to start if Telethon session files are readable by others.

    These files contain an authenticated session key — anyone with read access
    can impersonate the Telegram account. If we lack permission to chmod them,
    we log a clear warning so the operator can run ``sudo chmod 600`` manually.
    """
    import os
    import stat as _stat

    session = os.environ.get("TELEGRAM_SESSION") or settings.TELEGRAM_SESSION
    candidates = [session]
    if not session.endswith(".session"):
        candidates.append(session + ".session")
    candidates.append(session + ".session-journal")

    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            mode = os.stat(path).st_mode
            if mode & 0o077:
                logger.warning(
                    "⚠️ Session file %s is readable by group/other (mode=%o). "
                    "Run: sudo chmod 600 %s",
                    path, _stat.S_IMODE(mode), path,
                )
                try:
                    os.chmod(path, 0o600)
                    logger.info("🔒 Tightened permissions on %s to 0600", path)
                except PermissionError:
                    logger.error(
                        "❌ Cannot chmod %s — file owned by another user. "
                        "Manual fix: sudo chmod 600 %s",
                        path, path,
                    )
            else:
                logger.info("🔒 Session file %s permissions OK (mode=%o)", path, _stat.S_IMODE(mode))
        except Exception as exc:
            logger.warning("Could not inspect session file %s: %s", path, exc)


def load_channels_from_file():
    """Загрузить каналы из файла"""
    try:
        if channels_file.exists():
            with open(channels_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                channels = config.get('channels', [])
                logger.info(f"📂 Loaded {len(channels)} channels from config")
                return channels
    except Exception as e:
        logger.error(f"⚠️ Error loading channels: {e}")
    return []


def save_channels_to_file(channels):
    """Сохранить каналы в файл"""
    try:
        config = {"channels": channels}
        with open(channels_file, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
        logger.info(f"💾 Saved {len(channels)} channels to file")
        return True
    except Exception as e:
        logger.error(f"⚠️ Error saving channels: {e}")
        return False


@app.get("/api/v1/channels/")
async def get_channels(_: APIKey = Depends(require_api_key)):
    """Получить список каналов"""
    if not ingestion_service:
        return JSONResponse({"error": "Service not ready"}, status_code=503)

    channels = ingestion_service.get_monitored_channels()
    return JSONResponse(channels)


@app.post("/api/v1/channels/add")
async def add_channel(request: Request, _: APIKey = Depends(require_api_key)):
    """Добавить канал"""
    if not ingestion_service:
        return JSONResponse({"error": "Service not ready"}, status_code=503)

    body = await _safe_read_json(request, max_bytes=4096)
    link = body.get("link") if isinstance(body, dict) else None
    title = body.get("title") if isinstance(body, dict) else None

    if not link or not isinstance(link, str) or len(link) > 256:
        return JSONResponse({"status": "error", "message": "Link required"}, status_code=400)
    if title is not None and (not isinstance(title, str) or len(title) > 256):
        return JSONResponse({"status": "error", "message": "Invalid title"}, status_code=400)

    success = await ingestion_service.add_channel(link, title)

    if success:
        channels = load_channels_from_file()
        exists = any(ch.get('link') == link or ch.get('username') == link for ch in channels)

        if not exists:
            channels.append({"link": link, "title": title or link, "is_active": True})
            save_channels_to_file(channels)

        return JSONResponse({"status": "success", "message": f"Channel {link} added"})
    else:
        return JSONResponse({"status": "error", "message": "Failed to add"}, status_code=400)


@app.post("/api/v1/channels/remove")
async def remove_channel(request: Request, _: APIKey = Depends(require_api_key)):
    """Удалить канал"""
    if not ingestion_service:
        return JSONResponse({"error": "Service not ready"}, status_code=503)

    body = await _safe_read_json(request, max_bytes=4096)
    link = body.get("link") if isinstance(body, dict) else None

    if not link or not isinstance(link, str) or len(link) > 256:
        return JSONResponse({"status": "error", "message": "Link required"}, status_code=400)

    success = await ingestion_service.remove_channel(link)

    if success:
        channels = load_channels_from_file()
        original_count = len(channels)
        channels = [ch for ch in channels if ch.get('link') != link and ch.get('username') != link]

        if len(channels) < original_count:
            save_channels_to_file(channels)

        return JSONResponse({"status": "success", "message": f"Channel {link} removed"})
    else:
        return JSONResponse({"status": "error", "message": "Not found"}, status_code=404)


@app.post("/api/v1/api-keys")
async def create_api_key(request: Request):
    """Create new API key.

    Note: this endpoint is intentionally unauthenticated so the operator can
    bootstrap the first key. After that, rotate/revoke via the database.
    The plaintext key is returned only ONCE — only its SHA-256 hash is stored.
    """
    body = await _safe_read_json(request, max_bytes=2048)
    if not isinstance(body, dict):
        body = {}

    name = body.get("name") or "API Key"
    if not isinstance(name, str) or not (1 <= len(name) <= 128):
        return JSONResponse({"status": "error", "message": "Invalid name"}, status_code=400)

    expires_days = body.get("expires_days", 365)
    try:
        expires_days = int(expires_days)
    except (TypeError, ValueError):
        return JSONResponse({"status": "error", "message": "Invalid expires_days"}, status_code=400)
    if not (0 <= expires_days <= 3650):
        return JSONResponse({"status": "error", "message": "expires_days out of range"}, status_code=400)

    import secrets as _secrets
    from datetime import datetime, timedelta

    new_key = f"wok_{_secrets.token_hex(32)}"
    key_hash = _hash_api_key(new_key)

    db = next(get_db())
    api_key = APIKey(
        id=_secrets.token_hex(16),
        key_hash=key_hash,
        name=name,
        is_active=True,
        created_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(days=expires_days) if expires_days else None,
    )

    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    return {
        "api_key": new_key,
        "name": name,
        "expires_at": api_key.expires_at.isoformat() if api_key.expires_at else None,
    }


@app.get("/status")
async def get_status():
    """Статус системы (без аутентификации — для health-мониторинга)."""
    if not ingestion_service:
        return {"status": "not_ready"}

    return {
        "status": "running",
        "channels_monitored": len(ingestion_service.monitors),
        "messages_sent": ingestion_service.messages_sent,
        "messages_parsed": ingestion_service.messages_parsed,
        "parser_products": parser_service.products_parsed if parser_service else 0,
    }


@app.get("/")
async def root():
    """Главная страница"""
    template_path = Path("templates/index.html")
    if template_path.exists():
        return FileResponse(str(template_path))
    return JSONResponse({"error": "Web UI not available"})


@app.get("/health")
async def health():
    """Health check"""
    health_status = {
        "status": "healthy",
        "service": "window-of-light-combined",
        "dependencies": {
            "database": "unknown",
            "redis": "unknown",
            "telegram": "unknown"
        }
    }

    # Check database
    if _check_database_connection():
        health_status["dependencies"]["database"] = "ok"
    else:
        health_status["dependencies"]["database"] = "error: database probe failed"
        health_status["status"] = "degraded"

    try:
        if redis_client is not None:
            await redis_client.ping()
            health_status["dependencies"]["redis"] = "ok"
        else:
            health_status["dependencies"]["redis"] = "not initialized"
    except Exception:
        health_status["dependencies"]["redis"] = "error"
        health_status["status"] = "degraded"

    # Check Telegram
    try:
        if ingestion_service and ingestion_service.client:
            health_status["dependencies"]["telegram"] = "ok"
        else:
            health_status["dependencies"]["telegram"] = "not initialized"
    except Exception:
        health_status["dependencies"]["telegram"] = "error"

    return health_status


async def check_database_ready() -> bool:
    """Проверка готовности БД с retry"""
    max_retries = 10
    retry_delay = 2
    
    for attempt in range(max_retries):
        if _check_database_connection():
            logger.info("✅ Database connection successful")
            return True
        if attempt < max_retries - 1:
            logger.warning(f"⚠️ Database not ready (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s...")
            await asyncio.sleep(retry_delay)
        else:
            logger.error(f"❌ Database connection failed after {max_retries} attempts")
    return False


async def _get_cached_search(cache_key: str) -> Optional[Dict[str, Any]]:
    if redis_client is None:
        return None
    try:
        cached = await redis_client.get(cache_key)
        if cached:
            import json
            return json.loads(cached)
    except Exception as e:
        logger.warning(f"⚠️ Redis cache read failed: {e}")
    return None


async def _set_cached_search(cache_key: str, payload: Dict[str, Any]) -> None:
    if redis_client is None:
        return
    try:
        import json
        await redis_client.set(cache_key, json.dumps(payload), ex=settings.CACHE_TTL)
    except Exception as e:
        logger.warning(f"⚠️ Redis cache write failed: {e}")


async def init_database():
    """Инициализация таблиц БД"""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Database tables created")
        return True
    except Exception as e:
        logger.error(f"❌ Database initialization error: {e}")
        return False


# === Cache Functions удалены - Redis не используется ===


# === API Endpoints - Products ===
@app.get("/api/v1/products/{product_id}")
async def get_product(
    product_id: str,
    _: APIKey = Depends(require_api_key),
):
    """Get current product data (кэш отключен)"""
    if not product_id or len(product_id) > 64:
        raise HTTPException(status_code=400, detail="Invalid product id")
    db = next(get_db())
    repo = ProductRepository(db)
    product = await repo.get(product_id)

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    return {
        "id": product.id,
        "category_id": product.category_id,
        "brand": product.brand,
        "model": product.model,
        "price": product.price,
        "source_channel": product.source_channel,
        "message_link": product.message_link,
        "timestamp": product.timestamp.isoformat(),
        "created_at": product.created_at.isoformat() if product.created_at else None,
        "attributes": product.attributes or {}
    }


@app.get("/api/v1/products/{product_id}/history")
async def get_price_history(
    product_id: str,
    limit: int = 100,
    offset: int = 0,
    _: APIKey = Depends(require_api_key),
):
    """Get price history with pagination (FR-4.1)"""
    if not product_id or len(product_id) > 64:
        raise HTTPException(status_code=400, detail="Invalid product id")
    limit = max(1, min(int(limit), 500))
    offset = max(0, min(int(offset), 100_000))
    db = next(get_db())
    repo = ProductRepository(db)
    history = await repo.get_price_history(product_id, limit, offset)

    return {
        "product_id": product_id,
        "count": len(history),
        "limit": limit,
        "offset": offset,
        "history": [
            {
                "id": h.id,
                "price": h.price,
                "timestamp": h.timestamp.isoformat(),
                "source_channel": h.source_channel
            }
            for h in history
        ]
    }


@app.post("/api/v1/products/search")
async def search_products(
    criteria: ProductSearchRequest,
    _: APIKey = Depends(require_api_key),
):
    """Search products by criteria (FR-4.1)"""
    search_criteria = SearchCriteria(
        category_id=criteria.category_id,
        brand=criteria.brand,
        model=criteria.model,
        min_price=criteria.min_price,
        max_price=criteria.max_price,
        attributes=criteria.attributes,
        limit=criteria.limit,
        offset=criteria.offset
    )

    cache_key = f"wol:search:{hashlib.md5(search_criteria.model_dump_json(exclude_none=True).encode('utf-8')).hexdigest()}"
    cached = await _get_cached_search(cache_key)
    if cached is not None:
        return cached

    db = next(get_db())
    repo = ProductRepository(db)
    products = await repo.search(search_criteria)

    response_payload = {
        "count": len(products),
        "offset": criteria.offset,
        "limit": criteria.limit,
        "products": [
            {
                "id": p.id,
                "category_id": p.category_id,
                "brand": p.brand,
                "model": p.model,
                "price": p.price,
                "source_channel": p.source_channel,
                "message_link": p.message_link,
                "timestamp": p.timestamp.isoformat(),
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "attributes": p.attributes or {}
            }
            for p in products
        ]
    }
    await _set_cached_search(cache_key, response_payload)
    return response_payload


@app.get("/api/v1/categories")
async def get_categories(_: APIKey = Depends(require_api_key)):
    """Get all categories with attributes (кэш отключен)"""
    db = next(get_db())
    repo = CategoryRepository(db)
    categories = await repo.get_all()

    return [
        {
            "id": c.id,
            "name": c.name,
            "parent_id": c.parent_id,
            "attributes": c.attributes or [],
            "keywords": c.keywords or [],
            "is_active": c.is_active
        }
        for c in categories
    ]


async def _proxy_channel_monitor():
    """Monitor ProxyMTProto channel for new proxies via Telethon."""
    await asyncio.sleep(30)
    while True:
        try:
            if ingestion_service and ingestion_service.client:
                try:
                    entity = await ingestion_service.client.get_entity(PROXY_CHANNEL)
                    async for msg in ingestion_service.client.iter_messages(entity, limit=5):
                        if msg.text:
                            await proxy_manager.ingest_message(msg.text)
                except Exception as e:
                    logger.debug("Proxy channel read failed", error=str(e))
        except Exception as e:
            logger.debug("Proxy monitor error", error=str(e))
        await asyncio.sleep(60)


async def _proxy_health_loop():
    """Periodic proxy health check."""
    await asyncio.sleep(60)
    while True:
        try:
            await proxy_manager.health_check_all()
        except Exception as e:
            logger.debug("Proxy health check error", error=str(e))
        await asyncio.sleep(300)


@app.get("/api/v1/proxy/current")
async def get_current_proxy(_: APIKey = Depends(require_api_key)):
    p = proxy_manager.current
    if p:
        return p.as_dict
    return JSONResponse({"error": "no proxy available"}, status_code=404)


@app.get("/api/v1/proxy/mtproto")
async def get_mtproto_proxy(_: APIKey = Depends(require_api_key)):
    proxy = proxy_manager.current_proxy
    if proxy:
        return {"type": proxy[0], "host": proxy[1], "port": proxy[2], "rdns": proxy[3]}
    return JSONResponse({"error": "no proxy"}, status_code=404)


@app.post("/api/v1/proxy/rotate")
async def rotate_proxy(_: APIKey = Depends(require_api_key)):
    proxy = await proxy_manager.rotate()
    if proxy:
        return {"type": proxy[0], "host": proxy[1], "port": proxy[2], "rdns": proxy[3]}
    return JSONResponse({"error": "no proxy to rotate"}, status_code=404)


@app.post("/api/v1/proxy/mark_dead")
async def mark_proxy_dead(request: Request, _: APIKey = Depends(require_api_key)):
    body = await _safe_read_json(request, max_bytes=2048)
    host = body.get("host") if isinstance(body, dict) else None
    port = body.get("port", 443) if isinstance(body, dict) else 443
    if not host or not isinstance(host, str) or len(host) > 256:
        return JSONResponse({"error": "invalid host"}, status_code=400)
    try:
        port = int(port)
    except (TypeError, ValueError):
        return JSONResponse({"error": "invalid port"}, status_code=400)
    if not (1 <= port <= 65535):
        return JSONResponse({"error": "port out of range"}, status_code=400)
    for p in proxy_manager.proxies:
        if p.host == host and p.port == port:
            p.alive = False
            return {"status": "marked_dead", "host": host}
    return JSONResponse({"error": "proxy not found"}, status_code=404)


@app.get("/api/v1/proxy/all")
async def get_all_proxies(_: APIKey = Depends(require_api_key)):
    return proxy_manager.get_all()


PROXY_CHANNEL = "ProxyMTProto"


async def _check_socks_proxy() -> bool:
    """Check if SOCKS5 proxy is accepting connections."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(5)
            return s.connect_ex((settings.TELEGRAM_PROXY_HOST or "127.0.0.1",
                                 settings.TELEGRAM_PROXY_PORT or 1080)) == 0
    except Exception:
        return False


async def _channel_activity_watchdog(channels_count: int) -> None:
    """
    Background watchdog: if ingestion has been running but no messages were
    processed for >10 minutes, force a client restart.
    Runs as a separate task alongside ingestion.
    """
    import time
    WATCHDOG_INTERVAL = 120   # check every 2 min
    SILENT_THRESHOLD = 600    # 10 min without messages → restart

    await asyncio.sleep(60)  # give ingestion time to start
    last_msg_count = -1
    silent_since = None

    while True:
        await asyncio.sleep(WATCHDOG_INTERVAL)
        if ingestion_service is None or not ingestion_service._running:
            continue

        current_count = ingestion_service.messages_sent
        if current_count == last_msg_count:
            # No new messages since last check
            if silent_since is None:
                silent_since = time.time()
            elif time.time() - silent_since > SILENT_THRESHOLD:
                logger.warning(
                    "⚠️ No messages for %ds — restarting Telegram client",
                    SILENT_THRESHOLD,
                )
                try:
                    await ingestion_service.stop()
                except Exception:
                    pass
                silent_since = None
        else:
            # Messages are flowing
            silent_since = None
            last_msg_count = current_count


async def _run_ingestion_forever(channels: list[dict]) -> None:
    """Keep ingestion alive without taking down the API on startup failures."""
    base_retry_delay = 15
    max_retry_delay = 120
    retry_delay = base_retry_delay

    while True:
        try:
            if ingestion_service is None:
                await asyncio.sleep(retry_delay)
                continue

            # Pre-flight: check SOCKS5 proxy before trying Telethon
            if not await _check_socks_proxy():
                logger.warning(
                    "⚠️ SOCKS5 proxy %s:%s unavailable, waiting %ds before retry...",
                    settings.TELEGRAM_PROXY_HOST or "127.0.0.1",
                    settings.TELEGRAM_PROXY_PORT or 1080,
                    retry_delay,
                )
                await asyncio.sleep(retry_delay)
                # Exponential backoff up to max
                retry_delay = min(retry_delay * 2, max_retry_delay)
                continue

            # Proxy is listening — reset backoff
            retry_delay = base_retry_delay

            if ingestion_service.client is None:
                logger.info("📱 Initializing Telegram ingestion...")
                await ingestion_service.initialize()
                logger.info("✅ Telegram connected")

                added_count = 0
                for channel_data in channels:
                    link = channel_data.get("link") or channel_data.get("username")
                    if link and await ingestion_service.add_channel(link, channel_data.get("title")):
                        added_count += 1

                logger.info("📺 Channels loaded", total=len(channels), added=added_count)

            logger.info("📱 Starting Telegram monitoring...")
            await ingestion_service.start_monitoring()
        except Exception as e:
            err_str = str(e).lower()
            # Classify error for logging
            if "proxy" in err_str or "socks" in err_str or "connection" in err_str:
                logger.warning(
                    "⚠️ Proxy/network error, will retry in %ss: %s",
                    retry_delay,
                    e,
                )
                retry_delay = min(retry_delay * 2, max_retry_delay)
            else:
                logger.warning(
                    "⚠️ Telegram ingestion error, will retry in %ss: %s",
                    retry_delay,
                    e,
                )
            if ingestion_service is not None:
                try:
                    await ingestion_service.stop()
                except Exception:
                    pass
            await asyncio.sleep(retry_delay)


async def main():
    global ingestion_service, parser_service, db_ready
    global redis_client

    logger.info("🚀 Starting Window of Light - Combined Service")

    # === ЭТАП 0: Hardening checks ===
    logger.info("📊 Step 0/6: Security checks...")
    _check_session_file_permissions()
    bootstrap_api_keys()

    # === ЭТАП 1: Проверка БД ===
    logger.info("📊 Step 1/6: Checking database connection...")
    db_ready = await check_database_ready()
    if not db_ready:
        logger.error("❌ Database is not available. Exiting.")
        return

    # Инициализация таблиц
    if not await init_database():
        logger.error("❌ Failed to initialize database tables. Exiting.")
        return

    # === ЭТАП 2: Redis ===
    logger.info("📊 Step 2/6: Initializing Redis cache...")
    try:
        redis_client = Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB, decode_responses=True)
        await redis_client.ping()
        logger.info("✅ Redis cache initialized")
    except Exception as e:
        redis_client = None
        logger.warning(f"⚠️ Redis unavailable, continuing without cache: {e}")

    # === ЭТАП 3: Загружаем каналы ===
    logger.info("📊 Step 3/6: Loading channels configuration...")
    channels = load_channels_from_file()
    logger.info(f"📂 Loaded {len(channels)} channels from config")

    # === ЭТАП 4: Инициализация Parser ===
    logger.info("📊 Step 4/6: Initializing Parser Service...")
    parser_service = ParserService()  # LLM отключен, используем только блочные парсеры
    logger.info("✅ Parser Service initialized")

    # === ЭТАП 5: Инициализация Telegram Ingestion ===
    logger.info("📊 Step 5/6: Preparing Telegram Ingestion...")
    ingestion_service = TelegramIngestionService(parser_service=parser_service)

    # === Все этапы пройдены - запускаем API и мониторинг ===
    logger.info("🎉 All initialization steps completed successfully!")
    logger.info("🌐 Starting API on http://0.0.0.0:8002")
    logger.info("📱 Telegram monitoring will connect in background")
    logger.info("="*80)
    logger.info("📊 SYSTEM READY - Waiting for new posts and price updates")
    logger.info("="*80)
    logger.info("💡 Parser Service will:")
    logger.info("   - Monitor channels for new messages")
    logger.info("   - Parse products from posts automatically")
    logger.info("   - Save raw posts for re-processing if needed")
    logger.info("   - Track price changes over time")
    logger.info("="*80)

    # Запускаем API и мониторинг параллельно
    config = uvicorn.Config(app, host="0.0.0.0", port=8002, log_level="info", access_log=True)
    server = uvicorn.Server(config)

    await asyncio.gather(
        server.serve(),
        _run_ingestion_forever(channels),
        _channel_activity_watchdog(len(channels)),
        _proxy_channel_monitor(),
        _proxy_health_loop(),
    )


async def shutdown():
    """Корректное завершение"""
    try:
        logger.info("🛑 Shutting down...")

        if ingestion_service:
            await ingestion_service.stop()
        if redis_client is not None:
            await redis_client.aclose()

        logger.info("✅ Shutdown complete")
    except Exception as e:
        logger.error(f"⚠️ Shutdown error: {e}")


if __name__ == "__main__":
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("⌨️ Interrupted by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
    finally:
        try:
            if loop:
                loop.run_until_complete(asyncio.wait_for(shutdown(), timeout=5.0))
        except Exception:
            pass
        finally:
            try:
                if loop:
                    pending = asyncio.all_tasks(loop)
                    for task in pending:
                        task.cancel()
                    if pending:
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    loop.close()
            except Exception:
                pass
