"""Domain and tracker errors are mapped to HTTP statuses."""

import httpx
import pytest
from fastapi import FastAPI

from app.adapters.web.errors import install_error_handlers
from app.application.ports import TrackerError
from app.domain.errors import (
    ConflictError,
    DomainError,
    InvalidInputError,
    NotFoundError,
)

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    ("error", "status", "detail"),
    [
        (NotFoundError("no such stream"), 404, "no such stream"),
        (ConflictError("already there"), 409, "already there"),
        (InvalidInputError("bad geo"), 422, "bad geo"),
        (DomainError("shares must sum up to 100%"), 400, "shares must sum up to 100%"),
        (TrackerError(403, {"error": "forbidden"}), 502, "Keitaro: {'error': 'forbidden'}"),
        (TrackerError(500, "down"), 502, "Keitaro: down"),
    ],
    ids=lambda v: type(v).__name__ if isinstance(v, Exception) else None,
)
async def test_error_mapping(error, status, detail):
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/boom")
    async def boom():
        raise error

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/boom")
    assert (resp.status_code, resp.json()) == (status, {"detail": detail})
