import uuid
from typing import Optional, Sequence, Any, Dict
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import UserSearchHistory


class HistoryRepository:
    async def add_record(
        self,
        session: AsyncSession,
        user_id: int,
        query: str,
        normalized_query: Optional[str] = None,
        product_id: Optional[uuid.UUID | str] = None,
        final_price: Optional[float] = None,
        results_count: int = 0,
        metadata: Optional[Dict[str, Any]] = None
    ) -> UserSearchHistory:
        """
        Добавляет новую запись в историю поиска пользователя.
        """
        if metadata is None:
            metadata = {}

        if isinstance(product_id, str):
            product_id = uuid.UUID(product_id)

        record = UserSearchHistory(
            user_id=user_id,
            query=query,
            normalized_query=normalized_query,
            product_id=product_id,
            final_price=final_price,
            results_count=results_count,
            metadata_json=metadata
        )

        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record

    async def get_user_history(
        self,
        session: AsyncSession,
        user_id: int,
        limit: int = 20
    ) -> Sequence[UserSearchHistory]:
        """
        Возвращает последние поисковые запросы пользователя (по умолчанию 20).
        """
        stmt = (
            select(UserSearchHistory)
            .where(UserSearchHistory.user_id == user_id)
            .order_by(UserSearchHistory.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_record(
        self,
        session: AsyncSession,
        history_id: int
    ) -> Optional[UserSearchHistory]:
        """
        Получает конкретную запись из истории поиска по её ID.
        """
        stmt = select(UserSearchHistory).where(UserSearchHistory.id == history_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_record(
        self,
        session: AsyncSession,
        history_id: int,
        user_id: int
    ) -> bool:
        """
        Удаляет запись из истории поиска, проверяя принадлежность пользователю.
        Возвращает True, если запись была удалена.
        """
        stmt = (
            delete(UserSearchHistory)
            .where(UserSearchHistory.id == history_id)
            .where(UserSearchHistory.user_id == user_id)
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount > 0


history_repository = HistoryRepository()
