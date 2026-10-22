"""Alembic migrations build exactly the schema the models describe."""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy.ext.asyncio import create_async_engine

from app.adapters.persistence.orm import Base
from tests.integration.conftest import alembic


async def schema_diff(url: str) -> list:
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        diff = await conn.run_sync(lambda c: compare_metadata(MigrationContext.configure(c), Base.metadata))
    await engine.dispose()
    return diff


@pytest.mark.anyio
async def test_migrations_match_models(database_url):
    assert await schema_diff(database_url) == []


def test_downgrade_and_upgrade_again(database_url):
    alembic(database_url, "downgrade", "base")
    alembic(database_url, "upgrade", "head")
