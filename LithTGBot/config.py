from typing import List, Set
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
            if self.telegram_proxy_user and self.telegram_proxy_pass:
                return f"http://{self.telegram_proxy_user}:{self.telegram_proxy_pass}@{self.telegram_proxy_host}:{self.telegram_proxy_port}"
            return f"http://{self.telegram_proxy_host}:{self.telegram_proxy_port}"
        return None

    # Window of Light API
    wol_api_base_url: str = "http://192.168.1.220:8002"
    wol_api_timeout_seconds: int = 10

    # Database
    db_host: str
    db_port: int = 5432
    db_name: str
    db_user: str
    db_password: str
    db_readonly_mode: bool = True

    # Redis
    redis_host: str
    redis_port: int = 6379
    redis_db: int = 0

    # Celery
    celery_broker_url: str
    celery_result_backend: str

    # Admin
    admin_user_ids: Set[int] | str | list = Field(default_factory=set)

    @field_validator("admin_user_ids", mode="before")
    def parse_admin_ids(cls, v):
        if isinstance(v, str):
            if not v.strip():
                return set()
            return {int(x.strip()) for x in v.split(",") if x.strip().isdigit()}
        return v

    # Rate limiting
    rate_limit_per_minute: int = 10

    # Search
    search_page_size: int = 10
    search_cache_ttl_seconds: int = 300

    # Cleanup
    max_search_messages_per_chat: int = 3

    # Catalog / DB browser
    catalog_max_rows: int = 20
    db_browser_admin_only: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


settings = Settings()
