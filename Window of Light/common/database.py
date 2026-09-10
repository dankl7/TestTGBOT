from sqlalchemy import create_engine, Column, String, Float, DateTime, ForeignKey, Boolean, BigInteger, select, or_
from sqlalchemy.orm import sessionmaker, relationship, declarative_base, Session
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime
import uuid
from redis.asyncio import Redis
from .config import settings

DATABASE_URL = f"postgresql://{settings.DB_USER}:{settings.DB_PASSWORD}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=20)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# Export all models for easy import
__all__ = [
    'engine', 'SessionLocal', 'Base', 'get_db', 'Database',
    'Category', 'Product', 'PriceHistory', 'Channel', 'APIKey', 'RawPost'
]


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class Category(Base):
    """Dynamic category table (FR-3.4, FR-3.5)"""
    __tablename__ = "categories"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    parent_id = Column(String, ForeignKey('categories.id'), nullable=True)
    attributes = Column(JSONB, default=list)
    keywords = Column(JSONB, default=list)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Product(Base):
    """Product table with dynamic attributes"""
    __tablename__ = "products"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    category_id = Column(String, ForeignKey('categories.id'), nullable=False, index=True)
    brand = Column(String, nullable=False, index=True)
    model = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    source_channel = Column(String, nullable=False)
    message_link = Column(String, nullable=False, unique=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    attributes = Column(JSONB, default=dict)
    raw_message_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    category = relationship("Category")
    price_history = relationship("PriceHistory", back_populates="product", cascade="all, delete-orphan")


class PriceHistory(Base):
    """Price history for products (FR-3.3)"""
    __tablename__ = "price_history"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    product_id = Column(String, ForeignKey('products.id'), nullable=False, index=True)
    price = Column(Float, nullable=False)
    timestamp = Column(DateTime, nullable=False, index=True)
    source_channel = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="price_history")


class Channel(Base):
    """Telegram channels to monitor (FR-1.2)"""
    __tablename__ = "channels"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    channel_id = Column(BigInteger, nullable=True)
    username = Column(String, nullable=True)
    title = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    last_message_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class APIKey(Base):
    """API keys for authentication (FR-4.3)"""
    __tablename__ = "api_keys"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    key_hash = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)


class RawPost(Base):
    """Raw Telegram posts for storage and re-processing"""
    __tablename__ = "raw_posts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    channel_id = Column(String, nullable=False, index=True)  # Telegram channel ID
    message_id = Column(BigInteger, nullable=False, index=True)  # Telegram message ID
    post_id = Column(String, nullable=False, unique=True, index=True)  # Unique: f"{channel_id}_{message_id}"

    text = Column(String, nullable=False)  # Full post text
    has_text = Column(Boolean, default=True)
    text_length = Column(BigInteger, default=0)

    # Metadata
    date = Column(DateTime, nullable=False)  # Post date from Telegram
    parsed_count = Column(BigInteger, default=0)  # How many products parsed from this post
    is_processed = Column(Boolean, default=False, index=True)  # Already parsed?

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Database:
    """Database wrapper for product operations"""
    
    def __init__(self):
        self.session = SessionLocal()
        self.redis = None
        try:
            self.redis = Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                decode_responses=True,
            )
        except Exception:
            self.redis = None
    
    async def save_product(
        self,
        product_id: str,
        category_id: str,
        brand: str,
        model: str,
        price: float,
        attributes: dict,
        source_channel: str,
        message_link: str,
        timestamp: datetime
    ):
        """Save product to database, updating edited Telegram posts in place."""
        try:
            existing = self.session.execute(
                select(Product).where(
                    or_(Product.id == product_id, Product.message_link == message_link)
                )
            ).scalars().first()

            if existing is None:
                product = Product(
                    id=product_id,
                    category_id=category_id,
                    brand=brand,
                    model=model,
                    price=price,
                    attributes=attributes,
                    source_channel=source_channel,
                    message_link=message_link,
                    timestamp=timestamp,
                    raw_message_id=None,
                )
                self.session.add(product)
            else:
                price_changed = existing.price != price
                timestamp_changed = existing.timestamp != timestamp

                existing.category_id = category_id
                existing.brand = brand
                existing.model = model
                existing.price = price
                existing.attributes = attributes
                existing.source_channel = source_channel
                existing.timestamp = timestamp
                existing.raw_message_id = None

                if price_changed or timestamp_changed:
                    self.session.add(
                        PriceHistory(
                            id=str(uuid.uuid4()),
                            product_id=existing.id,
                            price=price,
                            timestamp=timestamp,
                            source_channel=source_channel,
                        )
                    )

            self.session.commit()
            return existing.id if existing is not None else product_id
        except Exception as e:
            self.session.rollback()
            raise e
    
    async def close(self):
        self.session.close()
        if self.redis is not None:
            await self.redis.aclose()
