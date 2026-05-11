import pytest
from unittest.mock import AsyncMock, MagicMock

from database.repositories.catalog import CatalogRepository
from bot.catalog_categories import (
    CATEGORIES,
    CATEGORY_BY_KEY,
    build_where_clause,
)
from bot.handlers.search import canonical_channel


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


def test_catalog_keys_are_unique_and_short():
    """callback_data в Telegram ограничено 64 байтами — 'cat:<key>' влезает с запасом."""
    keys = [c["key"] for c in CATEGORIES]
    assert len(keys) == len(set(keys)), "Дубль ключей в CATEGORIES"
    for c in CATEGORIES:
        cb = f"cat:{c['key']}"
        assert len(cb.encode("utf-8")) <= 32, f"callback_data слишком длинная: {cb}"


def test_category_by_key_index_matches_list():
    assert CATEGORY_BY_KEY == {c["key"]: c for c in CATEGORIES}


def test_build_where_clause_brand_only():
    sql, params = build_where_clause({"key": "x", "label": "x", "brand": "Apple"})
    assert sql == "brand ILIKE :brand"
    assert params == {"brand": "Apple"}


def test_build_where_clause_brand_and_model_like():
    sql, params = build_where_clause(
        {"key": "x", "label": "x", "brand": "Apple", "model_like": "iPhone 17%"}
    )
    assert sql == "brand ILIKE :brand AND model ILIKE :model_like"
    assert params == {"brand": "Apple", "model_like": "iPhone 17%"}


def test_build_where_clause_uses_regex_operator():
    sql, params = build_where_clause(
        {"key": "x", "label": "x", "brand": "Apple", "model_regex": "^iPad (Mini|[0-9])"}
    )
    assert "model ~* :model_regex" in sql
    assert params["model_regex"] == "^iPad (Mini|[0-9])"


def test_build_where_clause_empty_falls_back_to_true():
    sql, _ = build_where_clause({"key": "x", "label": "x"})  # type: ignore[arg-type]
    assert sql == "TRUE"


def test_canonical_channel_strips_long_format_prefix():
    assert canonical_channel("-1001887497207") == "1887497207"
    assert canonical_channel("-1001963407298") == "1963407298"
    assert canonical_channel("1887497207") == "1887497207"
    assert canonical_channel("") == ""
    # safety: чужие ID не уродуем
    assert canonical_channel("-100abc") == "-100abc"


@pytest.mark.asyncio
async def test_get_products_by_filter_passes_params(repo, session):
    """Все категорийные фильтры должны идти как именованные параметры."""
    result = MagicMock()
    result.fetchall.return_value = []
    session.execute.return_value = result

    await repo.get_products_by_filter(
        session,
        where_clause="brand ILIKE :brand AND model ILIKE :model_like",
        params={"brand": "Apple", "model_like": "iPhone 17%"},
    )
    args, _ = session.execute.call_args
    params = args[1]
    assert params["brand"] == "Apple"
    assert params["model_like"] == "iPhone 17%"
    assert "limit" in params
