import logging
from typing import Any, Dict, List, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings

logger = logging.getLogger(__name__)

class CatalogRepository:
    """
    Безопасный read-only доступ к данным.
    Обеспечивает доступ только к разрешенным таблицам (allowlist).
    Всегда использует параметризованные запросы и лимиты.
    """

    ALLOWED_TABLES = {
        "products",
        "raw_posts",
        "price_history",
        "categories",
        "channels"
    }

    async def get_table_schema(self, session: AsyncSession, table_name: str) -> List[Dict[str, Any]]:
        """
        Возвращает схему (колонки и их типы) для разрешенной таблицы.
        """
        if table_name not in self.ALLOWED_TABLES:
            raise ValueError(f"Доступ к таблице {table_name} запрещен.")

        stmt = text(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = :table_name
            ORDER BY ordinal_position;
            """
        )
        result = await session.execute(stmt, {"table_name": table_name})
        return [{"column_name": row[0], "data_type": row[1]} for row in result.fetchall()]

    async def browse_table(
        self,
        session: AsyncSession,
        table_name: str,
        limit: int = settings.catalog_max_rows,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Возвращает строки из разрешенной таблицы.
        """
        if table_name not in self.ALLOWED_TABLES:
            raise ValueError(f"Доступ к таблице {table_name} запрещен.")

        actual_limit = min(limit, settings.catalog_max_rows)
        stmt = text(f"SELECT * FROM {table_name} LIMIT :limit OFFSET :offset")
        result = await session.execute(stmt, {"limit": actual_limit, "offset": offset})

        keys = result.keys()
        rows = []

        for row in result.fetchall():
            row_dict = {}
            for idx, key in enumerate(keys):
                val = row[idx]
                if isinstance(val, str) and len(val) > 200:
                    val = val[:197] + "..."
                row_dict[key] = val
            rows.append(row_dict)

        return rows

    async def get_distinct_models(
        self,
        session: AsyncSession,
        min_count: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Возвращает список уникальных моделей товаров из БД,
        отсортированных по количеству доступных позиций (от большего к меньшему).
        Используется для генерации панели моделей на стартовом экране.
        """
        stmt = text(
            """
            SELECT brand, model, category_id, COUNT(*) as cnt
            FROM products
            WHERE brand IS NOT NULL
              AND model IS NOT NULL
              AND model != 
            GROUP BY brand, model, category_id
            HAVING COUNT(*) >= :min_count
            ORDER BY brand, cnt DESC
            """
        )
        result = await session.execute(stmt, {"min_count": min_count})
        return [
            {
                "brand": row[0],
                "model": row[1],
                "category_id": row[2],
                "count": row[3],
            }
            for row in result.fetchall()
        ]


catalog_repository = CatalogRepository()
