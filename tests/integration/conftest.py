"""Integration tests run against a dedicated test database.

By default it is a throwaway SQLite file; set TEST_DATABASE_URL to run them on another
instance (e.g. a Postgres container). The schema is built by the Alembic migrations, so
they are tested too, and every table is emptied before each test.
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.persistence.orm import Base
from app.config import DatabaseSettings

ROOT = Path(__file__).parents[2]


def pytest_collection_modifyitems(items):
    here = Path(__file__).parent
    for item in items:
        if here in item.path.parents:
            item.add_marker(pytest.mark.integration)


def alembic(url: str, *args: str) -> None:
    """Runs `alembic <command> <revision>` on the given database."""
    # migrations/env.py takes the URL from DatabaseSettings, i.e. from DATABASE_URL
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL", url)
        name, revision = args
        getattr(command, name)(Config(ROOT / "alembic.ini"), revision)


@pytest.fixture(scope="session")
def database_url(tmp_path_factory) -> str:
    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path_factory.mktemp('db') / 'test.db'}"
    url = DatabaseSettings(url=url).url
    if url == DatabaseSettings().url:
        pytest.exit(f"TEST_DATABASE_URL points to the app database ({url}), refusing to wipe it", 2)
    alembic(url, "upgrade", "head")
    return url


@pytest.fixture
async def engine(database_url):
    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def session(session_factory):
    async with session_factory() as session:
        yield session
