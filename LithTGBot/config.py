from typing import Set
import os
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEDIA_DIR = os.path.join(BASE_DIR, "media")
SESSIONS_DIR = os.path.join(BASE_DIR, "sessions")
os.makedirs(MEDIA_DIR, exist_ok=True)
os.makedirs(SESSIONS_DIR, exist_ok=True)


class Settings(BaseSettings):
    # Telegram
    telegram_bot_token: str

    telegram_proxy_host: str | None = None
    telegram_proxy_port: int | None = None
    telegram_proxy_user: str | None = None
    telegram_proxy_pass: str | None = None
    telegram_proxy_type: str | None = None

    @field_validator(
        "telegram_proxy_host",
        "telegram_proxy_port",
        "telegram_proxy_user",
        "telegram_proxy_pass",
        "telegram_proxy_type",
        mode="before",
    )
    def _empty_string_as_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @property
    def telegram_proxy_url(self) -> str | None:
        if self.telegram_proxy_host and self.telegram_proxy_port:
            ptype = (self.telegram_proxy_type or "HTTP").lower()
            scheme = "socks5" if ptype in ("socks5", "socks") else "http"
            if self.telegram_proxy_user and self.telegram_proxy_pass:
                return f"{scheme}://{self.telegram_proxy_user}:{self.telegram_proxy_pass}@{self.telegram_proxy_host}:{self.telegram_proxy_port}"
            return f"{scheme}://{self.telegram_proxy_host}:{self.telegram_proxy_port}"
        return None

    # Database
    db_host: str
    db_port: int = 5432
    db_name: str
    db_user: str
    db_password: str

    # Redis
    redis_host: str
    redis_port: int = 6379
    redis_db: int = 0

    # Encryption
    encryption_key: str

    # Admin
    admin_user_ids: Set[int] = Field(default_factory=set)

    @field_validator("admin_user_ids", mode="before")
    def parse_admin_ids(cls, v):
        if isinstance(v, str):
            if not v.strip():
                return set()
            return {int(x.strip()) for x in v.split(",") if x.strip().isdigit()}
        if isinstance(v, int):
            return {v}
        if isinstance(v, (list, set)):
            return set(int(x) for x in v)
        return v

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


settings = Settings()