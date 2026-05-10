import pytest
from unittest.mock import AsyncMock, MagicMock

from database.repositories.catalog import CatalogRepository


@pytest.fixture
def repo():
    return CatalogRepository()


@pytest.fixture
def session():
    return AsyncMock()


@pytest.mark.asyncio
async def test_browse_table_rejects_unknown_table(repo, session):
    with pytest.raises(ValueError):
        await repo.browse_table(session, "users")
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_get_table_schema_rejects_unknown_table(repo, session):
    with pytest.raises(ValueError):
        await repo.get_table_schema(session, "passwords")
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_browse_table_clamps_limit(repo, session):
    result = MagicMock()
    result.keys.return_value = []
    result.fetchall.return_value = []
    session.execute.return_value = result

    await repo.browse_table(session, "products", limit=999_999, offset=0)

    args, kwargs = session.execute.call_args
    bound_params = args[1]
    assert bound_params["limit"] <= 1000, (
        "browse_table должен ограничивать limit значением catalog_max_rows"
    )
    assert bound_params["offset"] == 0


@pytest.mark.asyncio
async def test_get_distinct_models_uses_valid_sql(repo, session):
    """Регрессия: SQL не должен содержать незавершённое `model !=`."""
    result = MagicMock()
    result.fetchall.return_value = []
    session.execute.return_value = result

    await repo.get_distinct_models(session, min_count=3)

    args, _ = session.execute.call_args
    sql = str(args[0])
    assert "model !=" in sql
    assert "model != ''" in sql or "model != \"\"" in sql, (
        "WHERE model != требует значения, иначе SQL невалиден"
    )
