from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "Window of Light"
    DEBUG: bool = False

    # Database
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "window_of_light"
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "postgres"

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    # Telegram (MTProto)
    TELEGRAM_API_ID: str = ""
    TELEGRAM_API_HASH: str = ""
    TELEGRAM_PHONE: str = ""
    TELEGRAM_SESSION: str = "wol_session"

    # Telegram proxy (optional; HTTP/SOCKS5)
    TELEGRAM_PROXY_HOST: Optional[str] = None
    TELEGRAM_PROXY_PORT: Optional[int] = None
    TELEGRAM_PROXY_USER: Optional[str] = None
    TELEGRAM_PROXY_PASS: Optional[str] = None
    TELEGRAM_PROXY_TYPE: Optional[str] = None  # "HTTP" | "SOCKS5"

    # Redis channels
    RAW_MESSAGES_CHANNEL: str = "raw_messages"
    PARSED_PRODUCTS_CHANNEL: str = "parsed_products"

    # API
    API_V1_PREFIX: str = "/api/v1"
    API_KEY_HEADER: str = "X-API-Key"

    # Comma-separated CORS allow-list. "*" is intentionally NOT accepted at
    # runtime — the security middleware enforces an explicit list.
    CORS_ALLOWED_ORIGINS: str = "http://localhost:8002,http://127.0.0.1:8002"

    # Comma-separated plaintext API keys inserted on first start (hashed in DB).
    API_BOOTSTRAP_KEYS: str = ""

    # Rate limit (per key, sliding window).
    RATE_LIMIT_REQUESTS: int = 60
    RATE_LIMIT_WINDOW_S: int = 60

    # Cache TTL (seconds)
    CACHE_TTL: int = 600

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def telethon_proxy(self):
        """Return a 6-tuple proxy spec for Telethon, or None."""
        if not (self.TELEGRAM_PROXY_HOST and self.TELEGRAM_PROXY_PORT):
            return None
        import socks
        ptype = (self.TELEGRAM_PROXY_TYPE or "HTTP").upper()
        proxy_type = socks.SOCKS5 if ptype == "SOCKS5" else socks.HTTP
        return (
            proxy_type,
            self.TELEGRAM_PROXY_HOST,
            int(self.TELEGRAM_PROXY_PORT),
            True,  # rdns
            self.TELEGRAM_PROXY_USER or None,
            self.TELEGRAM_PROXY_PASS or None,
        )


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
