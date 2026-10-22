"""Editor scenarios end to end: real use cases on the test DB and a fake tracker; no network."""

import pytest

from app.adapters.persistence.repository import CampaignRepository
from app.application.creator import CampaignCreator, CampaignDefaults
from app.application.editor import CampaignEditor
from app.application.offers import OfferCatalog
from app.domain.errors import ConflictError, InvalidInputError
from app.domain.models import Campaign, OfferShare
from tests.conftest import FakeTracker

pytestmark = pytest.mark.anyio


@pytest.fixture
def kt():
    return FakeTracker()


@pytest.fixture
def editor(session, kt):
    return CampaignEditor(session, CampaignRepository(session), kt, OfferCatalog(kt))


@pytest.fixture
def creator(kt, editor):
    return CampaignCreator(kt, editor, CampaignDefaults())


def shares(stream):
    return {o.offer_id: (o.state, o.share) for o in stream.offers}


def offers_stream(campaign: Campaign):
    return next(s for s in campaign.streams if s.offers)


def remote_offers(kt, stream):
    return {o.offer_id: o.share for o in kt.streams[stream.keitaro_id]["offers"]}


async def test_create_campaign(creator, kt):
    c = await creator.create(name="My test", geo="au, mx", offer_id=3,
                             group_id=10, traffic_source_id=20, domain_id=30)
    kc = kt.campaigns[c.keitaro_id]
    assert (kc.group_id, kc.traffic_source_id, kc.domain_id) == (10, 20, 30)
    flow1, flow2 = sorted(kt.streams.values(), key=lambda s: s["position"])
    assert (flow1["url"], flow1["countries"]) == ("https://google.com", ["AU", "MX"])
    assert flow2["offers"] == [OfferShare(offer_id=3, share=100)]
    assert c.id is not None and c.created_at is not None  # saved
    assert [len(s.offers) for s in c.streams] == [0, 1]
    assert offers_stream(c).offers[0].offer_name == "Offer 3"
    assert not offers_stream(c).is_dirty


async def test_invalid_geo(creator):
    with pytest.raises(InvalidInputError):
        await creator.create(name="x", geo="AUS", offer_id=1)


@pytest.fixture
async def stream(creator, editor):
    """The offers flow of a new campaign, with offers 1, 2, 3 published."""
    c = await creator.create(name="c", geo="AU", offer_id=1)
    stream = offers_stream(c)
    for oid in (2, 3):
        stream = await editor.add_offer(stream.id, oid)
    return await editor.publish_stream(stream.id)


async def test_add_offer_rebalances_and_publishes(editor, kt, stream):
    assert remote_offers(kt, stream) == {1: 34, 2: 33, 3: 33}

    stream = await editor.add_offer(stream.id, 4)
    assert [o.share for o in stream.offers] == [25, 25, 25, 25]
    assert stream.is_dirty
    assert remote_offers(kt, stream) == {1: 34, 2: 33, 3: 33}  # not pushed yet

    stream = await editor.publish_stream(stream.id)
    assert not stream.is_dirty
    assert remote_offers(kt, stream) == {1: 25, 2: 25, 3: 25, 4: 25}


async def test_cancel_drops_new_offers(editor, stream):
    stream = await editor.add_offer(stream.id, 4)
    stream = await editor.remove_offer(stream.offers[0].id)
    stream = await editor.cancel_stream(stream.id)
    assert shares(stream) == {1: ("active", 34), 2: ("active", 33), 3: ("active", 33)}
    assert not stream.is_dirty


async def test_remove_and_bring_back(editor, kt, stream):
    first = stream.offers[0]
    stream = await editor.remove_offer(first.id)
    assert shares(stream) == {1: ("removed", 0), 2: ("active", 50), 3: ("active", 50)}
    stream = await editor.publish_stream(stream.id)
    assert remote_offers(kt, stream) == {2: 50, 3: 50}
    assert first in stream.offers  # kept in the archive

    stream = await editor.bring_back_offer(first.id)
    assert stream.is_dirty
    stream = await editor.publish_stream(stream.id)
    assert remote_offers(kt, stream) == {1: 34, 2: 33, 3: 33}


async def test_offers_removed_in_keitaro_become_removed(editor, kt, stream):
    kt.streams[stream.keitaro_id]["offers"] = [OfferShare(offer_id=2, share=100)]
    campaign = await editor.import_campaign(kt.streams[stream.keitaro_id]["campaign_id"])
    stream = offers_stream(campaign)
    assert shares(stream) == {1: ("removed", 0), 2: ("active", 100), 3: ("removed", 0)}
    assert not stream.is_dirty

    stream = await editor.bring_back_offer(stream.offers[0].id)
    assert shares(stream)[1] == ("active", 50)


async def test_pinned_share_is_kept(editor, stream):
    stream = await editor.add_offer(stream.id, 4)  # 25 x 4
    stream = await editor.pin_offer(stream.offers[0].id, True)
    stream = await editor.remove_offer(stream.offers[1].id)
    assert shares(stream) == {1: ("active", 25), 2: ("removed", 0), 3: ("active", 38), 4: ("active", 37)}
    stream = await editor.bring_back_offer(stream.offers[1].id)
    assert shares(stream) == {1: ("active", 25), 2: ("active", 25), 3: ("active", 25), 4: ("active", 25)}
    stream = await editor.add_offer(stream.id, 5)
    assert stream.offers[0].share == 25
    assert sum(o.share for o in stream.offers) == 100


async def test_only_pinned_offers_left(editor, stream):
    stream = await editor.pin_offer(stream.offers[0].id, True)
    stream = await editor.remove_offer(stream.offers[1].id)
    stream = await editor.remove_offer(stream.offers[2].id)
    assert shares(stream)[1] == ("active", 100)
    await editor.publish_stream(stream.id)


async def test_cannot_add_same_offer_twice(editor, stream):
    with pytest.raises(ConflictError):
        await editor.add_offer(stream.id, 1)


async def test_state_survives_a_new_session(session_factory, editor, stream):
    await editor.add_offer(stream.id, 4)
    async with session_factory() as fresh:
        reloaded = await CampaignRepository(fresh).get_stream(stream.id)
    assert [(o.offer_id, o.share, o.is_new) for o in reloaded.offers] == [
        (1, 25, False), (2, 25, False), (3, 25, False), (4, 25, True)
    ]
