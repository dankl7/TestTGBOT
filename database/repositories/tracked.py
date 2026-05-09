import uuid
from typing import Optional, Sequence, Tuple
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import TrackedProduct, Product


class TrackedRepository:
    async def add_or_update_tracking(
        self,
        session: AsyncSession,
        user_id: int,
        product_id: uuid.UUID | str,
        current_price: float
    ) -> TrackedProduct:
        """
        Добавляет товар в отслеживание или активирует существующую запись.
        """
        if isinstance(product_id, str):
            product_id = uuid.UUID(product_id)

        stmt = select(TrackedProduct).where(
            TrackedProduct.user_id == user_id,
            TrackedProduct.product_id == product_id
        )
        result = await session.execute(stmt)
        tracked = result.scalar_one_or_none()

        if tracked:
            tracked.is_active = True
            tracked.last_seen_price = current_price
            # Сбрасываем last_notified_price до текущей цены при повторной активации
            tracked.last_notified_price = current_price
        else:
            tracked = TrackedProduct(
                user_id=user_id,
                product_id=product_id,
                last_seen_price=current_price,
                last_notified_price=current_price,
                is_active=True
            )
            session.add(tracked)

        await session.commit()
        await session.refresh(tracked)
        return tracked

    async def deactivate_tracking(
        self,
        session: AsyncSession,
        user_id: int,
        tracked_id: int
    ) -> bool:
        """
        Деактивирует отслеживание товара пользователем.
        """
        stmt = (
            update(TrackedProduct)
            .where(TrackedProduct.id == tracked_id, TrackedProduct.user_id == user_id)
            .values(is_active=False)
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount > 0

    async def get_user_tracked_products(
        self,
        session: AsyncSession,
        user_id: int
    ) -> Sequence[Tuple[TrackedProduct, Product]]:
        """
        Возвращает активные отслеживания пользователя вместе с данными о товаре.
        """
        stmt = (
            select(TrackedProduct, Product)
            .join(Product, TrackedProduct.product_id == Product.id)
            .where(TrackedProduct.user_id == user_id, TrackedProduct.is_active == True)
            .order_by(TrackedProduct.created_at.desc())
        )
        result = await session.execute(stmt)
        return result.all()

    async def get_all_active_trackings(
        self,
        session: AsyncSession
    ) -> Sequence[TrackedProduct]:
        """
        Возвращает все активные отслеживания для проверки цен в Celery.
        """
        stmt = select(TrackedProduct).where(TrackedProduct.is_active == True)
        result = await session.execute(stmt)
        return result.scalars().all()

    async def update_prices(
        self,
        session: AsyncSession,
        tracked_id: int,
        last_seen_price: float,
        last_notified_price: float
    ) -> None:
        """
        Обновляет цены в записи об отслеживании после проверки.
        """
        stmt = (
            update(TrackedProduct)
            .where(TrackedProduct.id == tracked_id)
            .values(
                last_seen_price=last_seen_price,
                last_notified_price=last_notified_price
            )
        )
        await session.execute(stmt)
        await session.commit()


tracked_repository = TrackedRepository()
