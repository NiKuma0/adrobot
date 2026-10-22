"""HTTP layer over the real app: dependencies overridden with the test DB and a fake tracker."""

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.adapters.web.dependencies import get_container
from app.application.creator import CampaignDefaults
from app.application.offers import OfferCatalog
from app.container import Container
from app.main import app
from tests.conftest import FakeTracker

pytestmark = pytest.mark.anyio


@pytest.fixture
async def client(engine):
    kt = FakeTracker()
    container = Container(
        tracker=kt,
        offers=OfferCatalog(kt),
        defaults=CampaignDefaults(),
        engine=engine,
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
    )
    app.dependency_overrides[get_container] = lambda: container
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


async def test_create_and_edit_campaign(client):
    resp = await client.post("/api/campaigns", json={"name": "c", "geo": "AU", "offer_id": 1})
    assert resp.status_code == 200, resp.text
    campaign = resp.json()
    assert campaign["synced_at"] is not None and len(campaign["synced_at"]) == 19
    flow2 = campaign["streams"][1]
    assert flow2["schema"] == "landings"
    assert flow2["offers"][0] | {"id": None} == {
        "id": None, "offer_id": 1, "offer_name": "Offer 1", "state": "active",
        "share": 100, "pinned": False, "is_new": False, "is_dirty": False,
    }

    resp = await client.post(f"/api/streams/{flow2['id']}/offers", json={"offer_id": 2})
    assert [(o["share"], o["is_new"]) for o in resp.json()["offers"]] == [(50, False), (50, True)]
    assert resp.json()["is_dirty"]

    resp = await client.get(f"/api/campaigns/{campaign['keitaro_id']}")
    assert resp.json()["streams"][1]["is_dirty"]


async def test_offers_and_errors(client):
    assert (await client.get("/api/offers", params={"q": "3"})).json() == [
        {"id": 3, "name": "Offer 3", "state": "active"}
    ]
    assert (await client.get("/api/campaigns/999")).status_code == 404
    assert (await client.post("/api/campaigns", json={"name": "c", "geo": "AUS", "offer_id": 1})).status_code == 422
