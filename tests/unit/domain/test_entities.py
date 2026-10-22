"""Entities: built from table rows by `from_orm`, compared by identity (id)."""

from datetime import datetime
from types import SimpleNamespace as Row

import pytest

from app.domain.models import Campaign, OfferState, Stream, StreamOffer

# rows only need the attributes: the domain doesn't know the ORM classes
OFFER_ROW = Row(id=11, offer_id=3, offer_name="Three", state="removed", share=0, pinned=False,
                published_state="active", published_share=40, stream_id=5)
STREAM_ROW = Row(id=5, keitaro_id=50, name="Offers", position=2, schema="landings", offers=[OFFER_ROW], campaign_id=1)
CAMPAIGN_ROW = Row(id=1, keitaro_id=10, name="Spring", alias="spring-1", created_at=datetime(2026, 10, 1),
                   synced_at=None, streams=[STREAM_ROW])


def test_offer_from_orm():
    o = StreamOffer.from_orm(OFFER_ROW)
    assert o.model_dump() == {
        "id": 11, "offer_id": 3, "offer_name": "Three", "state": OfferState.REMOVED, "share": 0, "pinned": False,
        "published_state": OfferState.ACTIVE, "published_share": 40,
    }
    assert type(o.state) is OfferState


def test_stream_from_orm():
    s = Stream.from_orm(STREAM_ROW)
    assert (s.id, s.keitaro_id, s.name, s.position, s.schema_) == (5, 50, "Offers", 2, "landings")
    assert [type(o) for o in s.offers] == [StreamOffer]
    assert s.offers[0].id == 11


def test_campaign_from_orm():
    c = Campaign.from_orm(CAMPAIGN_ROW)
    assert (c.id, c.keitaro_id, c.name, c.alias, c.created_at, c.synced_at) == (
        1, 10, "Spring", "spring-1", datetime(2026, 10, 1), None
    )
    assert [s.id for s in c.streams] == [5]
    assert [o.id for o in c.streams[0].offers] == [11]


def test_from_orm_copies():
    c = Campaign.from_orm(CAMPAIGN_ROW)
    c.streams[0].offers[0].share = 99
    c.streams.clear()
    assert (OFFER_ROW.share, len(CAMPAIGN_ROW.streams)) == (0, 1)


def test_from_orm_rejects_bad_rows():
    with pytest.raises(ValueError):
        StreamOffer.from_orm(Row(**{**vars(OFFER_ROW), "state": "deleted"}))


@pytest.mark.parametrize(
    ("a", "b", "equal"),
    [
        pytest.param(StreamOffer(id=1, offer_id=1), StreamOffer(id=1, offer_id=2, share=50), True, id="same-id"),
        pytest.param(StreamOffer(id=1, offer_id=1), StreamOffer(id=2, offer_id=1), False, id="other-id"),
        pytest.param(StreamOffer(offer_id=1), StreamOffer(offer_id=1), False, id="unsaved-lookalikes"),
        pytest.param(Stream(id=1, keitaro_id=1), Campaign(id=1, keitaro_id=1, name="c"), False, id="other-type"),
    ],
)
def test_identity(a, b, equal):
    assert (a == b) is equal
    assert a == a  # noqa: PLR0124 -- an entity always equals itself


def test_entities_are_mutable_and_unhashable():
    o = StreamOffer(offer_id=1)
    o.share = 40
    assert o.share == 40
    with pytest.raises(TypeError):
        hash(o)
