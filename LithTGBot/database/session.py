from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    pool_pre_ping=True,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

async def get_db_session():
    """Yields an async database session."""
    async with async_session_maker() as session:
        yield session
