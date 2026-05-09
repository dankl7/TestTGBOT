from datetime import datetime
from decimal import Decimal
from typing import Any, Dict
from uuid import UUID

from pydantic import BaseModel, Field


class ProductDTO(BaseModel):
    id: UUID | str
    title: str = ""
    brand: str | None = None
    model: str | None = None
    category_id: str | None = None
    source_channel: str | None = None
    price: int | float | Decimal | None = None
    currency: str = "RUB"
    attributes: Dict[str, Any] = Field(default_factory=dict)
    raw_post_id: UUID | str | None = None
    message_link: str | None = None
    updated_at: datetime | None = None


class SearchResultDTO(BaseModel):
    query: str
    normalized_query: str
    items: list[ProductDTO]
    total: int
    page: int
    page_size: int


class PriceHistoryItemDTO(BaseModel):
    product_id: UUID | str
    price: int | float | Decimal
    timestamp: datetime
