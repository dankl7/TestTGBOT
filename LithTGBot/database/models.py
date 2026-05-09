import uuid
from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    Integer,
    BigInteger,
    Boolean,
    Numeric,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Category(Base):
    __tablename__ = "categories"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    parent_id = Column(String, ForeignKey("categories.id"))
    attributes = Column(JSONB, default=list)
    keywords = Column(JSONB, default=list)
    is_active = Column(Boolean, default=True)


class Channel(Base):
    __tablename__ = "channels"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_id = Column(String, unique=True, nullable=False)
    username = Column(String)
    title = Column(String)
    is_active = Column(Boolean, default=True)
    last_message_id = Column(Integer)


class RawPost(Base):
    __tablename__ = "raw_posts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_id = Column(String, nullable=False)
    message_id = Column(Integer, nullable=False)
    post_id = Column(String, nullable=False, unique=True)
    text = Column(String)
    message_link = Column(String)
    date = Column(DateTime(timezone=True))
    parsed_count = Column(Integer, default=0)
    is_processed = Column(Boolean, default=False)


class Product(Base):
    __tablename__ = "products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category_id = Column(String, ForeignKey("categories.id"))
    brand = Column(String)
    model = Column(String)
    price = Column(Numeric(12, 2))
    source_channel = Column(String)
    message_link = Column(String)
    raw_post_id = Column(UUID(as_uuid=True), ForeignKey("raw_posts.id"))
    attributes = Column(JSONB, default=dict)
    timestamp = Column(DateTime(timezone=True), default=datetime.utcnow)

    storage = Column(String)
    ram = Column(String)
    color = Column(String)
    sim_type = Column(String)
    screen_size = Column(String)
    chip = Column(String)
    connectivity = Column(String)
    country_flag = Column(String)
    sku = Column(String)

    # Relationships (optional, for convenience)
    raw_post = relationship("RawPost")
    category = relationship("Category")


class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"))
    price = Column(Numeric(12, 2))
    timestamp = Column(DateTime(timezone=True), default=datetime.utcnow)
    source_channel = Column(String)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(String, unique=True, nullable=False)
    description = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


# --- New tables for LithTGBot ---

class TrackedProduct(Base):
    __tablename__ = "tracked_products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    last_seen_price = Column(Numeric(12, 2))
    last_notified_price = Column(Numeric(12, 2))
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_tracked_user_product"),
        Index("idx_tracked_products_user_id", "user_id"),
        Index("idx_tracked_products_product_id", "product_id"),
        Index("idx_tracked_products_active", "is_active"),
    )


class UserSearchHistory(Base):
    __tablename__ = "user_search_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False)
    query = Column(String(500), nullable=False)
    normalized_query = Column(String(500))
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"))
    final_price = Column(Numeric(12, 2))
    results_count = Column(Integer, nullable=False, default=0)
    metadata_json = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_user_search_history_user_created", "user_id", "created_at", postgresql_ops={"created_at": "DESC"}),
        Index("idx_user_search_history_query_created", "query", "created_at", postgresql_ops={"created_at": "DESC"}),
        Index("idx_user_search_history_product_id", "product_id"),
        Index("idx_user_search_history_query_count", "query", "results_count", postgresql_ops={"results_count": "DESC"}),
    )
