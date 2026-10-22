"""Settings: plain DB URLs get an async driver."""

import pytest

from app.config import DatabaseSettings


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("sqlite:///./adrobot.db", "sqlite+aiosqlite:///./adrobot.db"),
        ("sqlite://", "sqlite+aiosqlite://"),
        ("postgresql://u:p@db:5432/adrobot", "postgresql+psycopg://u:p@db:5432/adrobot"),
        ("sqlite+aiosqlite:///x.db", "sqlite+aiosqlite:///x.db"),
        ("postgresql+asyncpg://db/adrobot", "postgresql+asyncpg://db/adrobot"),
        ("mysql+aiomysql://db/adrobot", "mysql+aiomysql://db/adrobot"),
    ],
)
def test_database_url_gets_async_driver(url, expected):
    assert DatabaseSettings(url=url).url == expected


def test_database_url_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://db/from-env")
    assert DatabaseSettings().url == "postgresql+psycopg://db/from-env"
