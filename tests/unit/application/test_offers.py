"""OfferCatalog: TTL cache over the tracker, search and name lookup."""

import asyncio
from unittest.mock import patch

import pytest

from app.application.offers import OfferCatalog
from app.application.ports import TrackerError, TrackerOffer

pytestmark = pytest.mark.anyio

OFFERS = [
    TrackerOffer(id=1, name="Alpha"),
    TrackerOffer(id=12, name="Beta"),
    TrackerOffer(id=3, name="alphabet soup"),
    TrackerOffer(id=21, name="Gamma"),
]


@pytest.fixture
def tracker(tracker):
    tracker.list_offers.return_value = OFFERS
    return tracker


@pytest.fixture
def catalog(tracker):
    return OfferCatalog(tracker, ttl=60)


@pytest.fixture
def clock():
    with patch("app.application.offers.time") as time:
        time.monotonic.return_value = 1000.0
        yield time


@pytest.mark.parametrize(
    ("elapsed", "fetches"),
    [
        pytest.param(0, 1, id="same-moment"),
        pytest.param(60, 1, id="at-ttl"),
        pytest.param(60.1, 2, id="expired"),
    ],
)
async def test_all_is_cached_for_ttl(catalog, tracker, clock, elapsed, fetches):
    assert await catalog.all() == OFFERS
    clock.monotonic.return_value += elapsed
    assert await catalog.all() == OFFERS
    assert tracker.list_offers.await_count == fetches


async def test_concurrent_calls_fetch_once(catalog, tracker):
    async def slow():
        await asyncio.sleep(0.01)
        return OFFERS

    tracker.list_offers.side_effect = slow
    results = await asyncio.gather(*(catalog.all() for _ in range(5)))
    assert results == [OFFERS] * 5
    tracker.list_offers.assert_awaited_once()


async def test_failure_is_not_cached(catalog, tracker):
    tracker.list_offers.side_effect = [TrackerError(502, "down"), OFFERS]
    with pytest.raises(TrackerError):
        await catalog.all()
    assert await catalog.all() == OFFERS


@pytest.mark.parametrize(
    ("q", "ids"),
    [
        ("", [1, 12, 3, 21]),
        ("   ", [1, 12, 3, 21]),
        ("alpha", [1, 3]),
        ("ALPHA", [1, 3]),
        ("  beta ", [12]),
        ("soup", [3]),
        ("1", [1, 12, 21]),  # by id substring
        ("21", [21]),
        ("zzz", []),
    ],
)
async def test_search(catalog, q, ids):
    assert [o.id for o in await catalog.search(q)] == ids


@pytest.mark.parametrize(("limit", "ids"), [(0, []), (2, [1, 12]), (10, [1, 12, 3, 21])])
async def test_search_limit(catalog, limit, ids):
    assert [o.id for o in await catalog.search("", limit=limit)] == ids


async def test_name_of_listed_offer(catalog, tracker):
    assert await catalog.name_of(12) == "Beta"
    tracker.get_offer.assert_not_awaited()


async def test_name_of_archived_offer(catalog, tracker):
    tracker.get_offer.return_value = TrackerOffer(id=99, name="Archived", state="archived")
    assert await catalog.name_of(99) == "Archived"
    tracker.get_offer.assert_awaited_once_with(99)


async def test_name_of_unknown_offer(catalog, tracker):
    tracker.get_offer.side_effect = TrackerError(404, "not found")
    assert await catalog.name_of(99) == "Offer #99"
