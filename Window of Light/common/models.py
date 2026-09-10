from pydantic import BaseModel, ConfigDict, Field
from typing import Dict, List, Optional, Any
from datetime import datetime


class RawMessage(BaseModel):
    """Raw message from Telegram (FR-1.4)"""
    id: str
    text: str
    timestamp: datetime
    channel_id: str
    channel_username: Optional[str] = None
    message_link: str
    chat_id: Optional[int] = None
    message_id: Optional[int] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "msg_123456",
                "text": "iPhone 15 Pro 256GB Black - 89990₽",
                "timestamp": "2024-01-15T10:30:00Z",
                "channel_id": "tech_deals",
                "channel_username": "tech_deals",
                "message_link": "https://t.me/tech_deals/123",
                "chat_id": -1001234567890,
                "message_id": 123,
            }
        }
    )


class ParsedProduct(BaseModel):
    """Parsed product data (FR-2.6)"""
    id: Optional[str] = None
    category_id: str
    brand: str
    model: str
    price: float
    source_channel: str
    message_link: str
    timestamp: datetime
    attributes: Dict[str, Any] = Field(default_factory=dict)
    raw_message_id: Optional[str] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "category_id": "smartphones",
                "brand": "Apple",
                "model": "iPhone 15 Pro",
                "price": 89990.0,
                "source_channel": "tech_deals",
                "message_link": "https://t.me/tech_deals/123",
                "timestamp": "2024-01-15T10:30:00Z",
                "attributes": {
                    "storage": "256GB",
                    "color": "Black",
                },
            }
        }
    )


class SearchCriteria(BaseModel):
    """Search criteria for products"""
    category_id: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    attributes: Optional[Dict[str, Any]] = None
    limit: int = 100
    offset: int = 0
