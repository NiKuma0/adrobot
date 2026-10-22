"""CampaignEditor use cases over mocked ports: what is loaded, called and committed."""

from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from app.application.editor import CampaignEditor
from app.application.ports import TrackerCampaign, TrackerError
from app.domain.errors import ConflictError, DomainError, NotFoundError
from app.domain.models import (
    Campaign,
    OfferShare,
    OfferState,
    Stream,
    StreamOffer,
    StreamSnapshot,
)

pytestmark = pytest.mark.anyio

ACTIVE, REMOVED = OfferState.ACTIVE, OfferState.REMOVED


@pytest.fixture
def editor(session, campaigns, tracker, offers):
    return CampaignEditor(session, campaigns, tracker, offers)


def published_stream(*shares: tuple[int, int, str]) -> Stream:
    """Stream (keitaro_id 77) with offers given as (offer_id, share, state); stream offer id = 100 + offer_id."""
    offers = []
    for offer_id, share, state in shares:
        so = StreamOffer(offer_id=offer_id, state=state, share=share, published_state=state, published_share=share)
        so.id = 100 + offer_id
        offers.append(so)
    stream = Stream(keitaro_id=77, offers=offers)
    stream.id = 7
    return stream


@pytest.fixture
def stream(campaigns):
    s = published_stream((1, 50, ACTIVE), (2, 50, ACTIVE), (3, 0, REMOVED))
    campaigns.get_stream.return_value = s
    campaigns.get_stream_by_offer.return_value = s
    return s


def state(stream: Stream) -> dict[int, tuple[str, int]]:
    return {o.offer_id: (o.state, o.share) for o in stream.offers}


# --- campaigns -------------------------------------------------------------------------


async def test_get_campaign(editor, campaigns):
    c = Campaign(keitaro_id=5, name="c")
    campaigns.get_by_keitaro_id.return_value = c
    assert await editor.get_campaign(5) is c
    campaigns.get_by_keitaro_id.assert_awaited_once_with(5)


async def test_get_campaign_not_imported(editor):
    with pytest.raises(NotFoundError, match="fetch streams first"):
        await editor.get_campaign(5)


async def test_import_new_campaign(editor, campaigns, tracker, session):
    tracker.get_campaign.return_value = TrackerCampaign(id=5, name="From Keitaro", alias="alias-5")
    tracker.get_campaign_streams.return_value = []

    c = await editor.import_campaign(5)

    tracker.get_campaign.assert_awaited_once_with(5)
    campaigns.save.assert_awaited_once_with(c)
    assert (c.id, c.keitaro_id, c.name, c.alias) == (None, 5, "From Keitaro", "alias-5")
    tracker.get_campaign_streams.assert_awaited_once_with(5)
    session.commit.assert_awaited_once()


async def test_import_known_campaign_only_syncs(editor, campaigns, tracker, session):
    known = Campaign(keitaro_id=5, name="c")
    campaigns.get_by_keitaro_id.return_value = known
    tracker.get_campaign_streams.return_value = []

    assert await editor.import_campaign(5) is known

    tracker.get_campaign.assert_not_awaited()
    campaigns.save.assert_awaited_once_with(known)
    session.commit.assert_awaited_once()


async def test_import_unknown_in_keitaro(editor, campaigns, tracker, session):
    tracker.get_campaign.side_effect = TrackerError(404, "not found")
    with pytest.raises(TrackerError):
        await editor.import_campaign(5)
    campaigns.save.assert_not_awaited()
    session.commit.assert_not_awaited()


async def test_sync_campaign_looks_up_names_of_new_offers_only(editor, campaigns, tracker, offers, session):
    c = Campaign(keitaro_id=5, name="c", streams=[published_stream((1, 100, ACTIVE))])
    tracker.get_campaign_streams.return_value = [
        StreamSnapshot(keitaro_id=77, name="Flow", position=1, schema="landings", offers=[
            OfferShare(offer_id=1, share=50), OfferShare(offer_id=3, share=25), OfferShare(offer_id=2, share=25)
        ]),
    ]
    now = datetime(2026, 10, 21, 12, 30)

    with patch("app.application.editor.datetime") as dt:
        dt.now.return_value = now
        assert await editor.sync_campaign(c) is c

    campaigns.save.assert_awaited_once_with(c)
    assert [call.args for call in offers.name_of.await_args_list] == [(2,), (3,)]
    assert [(o.offer_id, o.offer_name, o.share) for o in c.streams[0].offers] == [
        (1, "", 50), (3, "Offer 3", 25), (2, "Offer 2", 25)
    ]
    assert c.synced_at == now
    session.commit.assert_awaited_once()


async def test_sync_campaign_tracker_failure(editor, campaigns, tracker, session):
    c = Campaign(keitaro_id=5, name="c")
    tracker.get_campaign_streams.side_effect = TrackerError(502, "down")
    with pytest.raises(TrackerError):
        await editor.sync_campaign(c)
    assert c.synced_at is None
    campaigns.save.assert_not_awaited()
    session.commit.assert_not_awaited()


# --- stream editing --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "args", "lookup"),
    [
        ("add_offer", (7, 4), "get_stream"),
        ("publish_stream", (7,), "get_stream"),
        ("cancel_stream", (7,), "get_stream"),
        ("remove_offer", (101,), "get_stream_by_offer"),
        ("bring_back_offer", (103,), "get_stream_by_offer"),
        ("pin_offer", (101, True), "get_stream_by_offer"),
    ],
)
async def test_stream_not_found(editor, campaigns, tracker, session, action, args, lookup):
    with pytest.raises(NotFoundError):
        await getattr(editor, action)(*args)
    getattr(campaigns, lookup).assert_awaited_once_with(args[0])
    tracker.update_stream_offers.assert_not_awaited()
    campaigns.save_stream.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.parametrize(
    ("action", "args", "expected"),
    [
        pytest.param("add_offer", (7, 4), {1: (ACTIVE, 34), 2: (ACTIVE, 33), 3: (REMOVED, 0), 4: (ACTIVE, 33)},
                     id="add"),
        pytest.param("add_offer", (7, 3), {1: (ACTIVE, 34), 2: (ACTIVE, 33), 3: (ACTIVE, 33)},
                     id="add-removed"),
        pytest.param("remove_offer", (101,), {1: (REMOVED, 0), 2: (ACTIVE, 100), 3: (REMOVED, 0)}, id="remove"),
        pytest.param("bring_back_offer", (103,), {1: (ACTIVE, 34), 2: (ACTIVE, 33), 3: (ACTIVE, 33)},
                     id="bring-back"),
        pytest.param("pin_offer", (101, True), {1: (ACTIVE, 50), 2: (ACTIVE, 50), 3: (REMOVED, 0)}, id="pin"),
    ],
)
async def test_edit_stream(editor, stream, campaigns, tracker, session, action, args, expected):
    assert await getattr(editor, action)(*args) is stream
    assert state(stream) == expected
    assert stream.is_dirty is (action != "pin_offer")
    tracker.update_stream_offers.assert_not_awaited()  # nothing goes to Keitaro until publish
    campaigns.save_stream.assert_awaited_once_with(stream)
    session.commit.assert_awaited_once()


async def test_edit_returns_the_saved_stream(editor, stream, campaigns):
    saved = published_stream((1, 50, ACTIVE), (2, 50, ACTIVE))
    campaigns.save_stream.side_effect = None
    campaigns.save_stream.return_value = saved
    assert await editor.pin_offer(101, True) is saved


@pytest.mark.parametrize(
    ("action", "args"),
    [
        ("add_offer", (7, 1)),
        ("remove_offer", (103,)),
        ("bring_back_offer", (101,)),
        ("pin_offer", (103, True)),
    ],
)
async def test_edit_conflict_is_not_saved(editor, stream, campaigns, session, action, args):
    with pytest.raises(ConflictError):
        await getattr(editor, action)(*args)
    campaigns.save_stream.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.parametrize(
    ("offer_id", "looked_up"),
    [
        pytest.param(4, True, id="new-offer"),
        pytest.param(3, False, id="removed-offer-keeps-its-name"),
    ],
)
async def test_add_offer_name_lookup(editor, stream, offers, offer_id, looked_up):
    await editor.add_offer(7, offer_id)
    if looked_up:
        offers.name_of.assert_awaited_once_with(offer_id)
        assert stream.find_offer(offer_id).offer_name == f"Offer {offer_id}"
    else:
        offers.name_of.assert_not_awaited()


async def test_pin_offer_sets_the_flag(editor, stream):
    await editor.pin_offer(101, True)
    assert stream.get_offer(101).pinned
    await editor.pin_offer(101, False)
    assert not stream.get_offer(101).pinned


# --- publish / cancel ------------------------------------------------------------------


async def test_publish_pushes_then_saves(editor, stream, campaigns, tracker, session):
    stream.add_offer(4)
    order = Mock()
    order.attach_mock(tracker.update_stream_offers, "push")
    order.attach_mock(campaigns.save_stream, "save")
    order.attach_mock(session.commit, "commit")

    assert await editor.publish_stream(7) is stream

    tracker.update_stream_offers.assert_awaited_once_with(
        77, [OfferShare(offer_id=1, share=34), OfferShare(offer_id=2, share=33), OfferShare(offer_id=4, share=33)],
    )
    assert [c[0] for c in order.mock_calls] == ["push", "save", "commit"]
    assert not stream.is_dirty


async def test_publish_rejected_by_keitaro_keeps_changes(editor, stream, campaigns, tracker, session):
    stream.add_offer(4)
    tracker.update_stream_offers.side_effect = TrackerError(400, "bad offers")
    with pytest.raises(TrackerError):
        await editor.publish_stream(7)
    assert stream.is_dirty
    campaigns.save_stream.assert_not_awaited()
    session.commit.assert_not_awaited()


async def test_publish_invalid_stream_is_not_sent(editor, campaigns, tracker, session):
    campaigns.get_stream.return_value = published_stream((1, 0, REMOVED))
    with pytest.raises(DomainError, match="at least one active offer"):
        await editor.publish_stream(7)
    tracker.update_stream_offers.assert_not_awaited()
    session.commit.assert_not_awaited()


async def test_cancel_stream(editor, stream, session):
    stream.add_offer(4)
    stream.remove_offer(101)
    assert await editor.cancel_stream(7) is stream
    assert state(stream) == {1: (ACTIVE, 50), 2: (ACTIVE, 50), 3: (REMOVED, 0)}
    session.commit.assert_awaited_once()
