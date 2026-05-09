from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ReplacementDTO(BaseModel):
    from_str: str = Field(alias="from")
    to_str: str = Field(alias="to")


class NormalizedQueryDTO(BaseModel):
    original_query: str
    normalized_query: str
    tokens: List[str]
    applied_replacements: List[Dict[str, str]]
    confidence: float


class ProductSearchRequest(BaseModel):
    category_id: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    attributes: Optional[Dict[str, Any]] = None
    limit: int = 10
    offset: int = 0
