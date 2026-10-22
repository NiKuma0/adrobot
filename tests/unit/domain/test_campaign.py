"""Campaign aggregate: sync of the local copy with Keitaro flows."""

from datetime import datetime

import pytest

from app.domain.models import (
    Campaign,
    OfferShare,
    OfferState,
    Stream,
    StreamOffer,
    StreamSnapshot,
)


def snap(keitaro_id, *offer_ids, position=None, name=None, schema="landings"):
    return StreamSnapshot(
        keitaro_id=keitaro_id,
        name=name or f"Flow {keitaro_id}",
        position=keitaro_id if position is None else position,
        schema=schema,
        offers=[OfferShare(offer_id=i, share=100 // len(offer_ids)) for i in offer_ids],
    )


def campaign(*streams: dict[int, list[int]]) -> Campaign:
    """campaign({10: [1, 2]}, {20: []}) -> flows 10 and 20 with offers 1, 2 bound to flow 10."""
    c = Campaign(keitaro_id=1, name="c")
    for spec in streams:
        for keitaro_id, offer_ids in spec.items():
            offers = [StreamOffer(offer_id=i, published_state=OfferState.ACTIVE) for i in offer_ids]
            c.streams.append(Stream(keitaro_id=keitaro_id, position=keitaro_id, offers=offers))
    return c


@pytest.mark.parametrize(
    ("local", "snapshots", "expected"),
    [
        pytest.param([], [snap(10, 1, 2), snap(20, 3)], {1, 2, 3}, id="fresh-campaign"),
        pytest.param([{10: [1]}], [snap(10, 1, 2)], {2}, id="new-in-known-flow"),
        pytest.param([{10: [1]}], [snap(10, 1)], set(), id="nothing-new"),
        pytest.param([{10: [1]}], [snap(20, 1)], {1}, id="known-offer-in-new-flow"),
        pytest.param([{10: [1]}, {20: [2]}], [snap(10, 2), snap(20, 1)], {1, 2}, id="offers-swapped-flows"),
        pytest.param([{10: [1]}], [snap(10), snap(20)], set(), id="flows-without-offers"),
        pytest.param([{10: [1]}], [], set(), id="no-flows"),
    ],
)
def test_new_offer_ids(local, snapshots, expected):
    assert campaign(*local).new_offer_ids(snapshots) == expected


def test_new_offer_ids_accepts_an_iterator():
    assert campaign().new_offer_ids(iter([snap(10, 1)])) == {1}


def test_sync_creates_flows_sorted_by_position():
    c = campaign()
    synced_at = datetime(2026, 10, 21, 12, 0)
    c.sync([snap(20, 2, position=2, schema="landings"), snap(10, position=1, name="Geo", schema="redirect")],
           {2: "Offer 2"}, synced_at)

    assert [(s.keitaro_id, s.name, s.position, s.schema_) for s in c.streams] == [
        (10, "Geo", 1, "redirect"),
        (20, "Flow 20", 2, "landings"),
    ]
    assert [(o.offer_id, o.offer_name, o.share) for o in c.streams[1].offers] == [(2, "Offer 2", 100)]
    assert c.synced_at == synced_at
    assert not any(s.is_dirty for s in c.streams)


def test_sync_updates_known_flows_in_place():
    c = campaign({10: [1]})
    known = c.streams[0]
    c.sync([snap(10, 1, 2, name="Renamed", position=5, schema="redirect")], {2: "Offer 2"}, datetime.now())

    assert c.streams == [known]
    assert (known.name, known.position, known.schema_) == ("Renamed", 5, "redirect")
    assert [(o.offer_id, o.share) for o in known.offers] == [(1, 50), (2, 50)]


def test_sync_drops_flows_gone_from_keitaro():
    c = campaign({10: [1]}, {20: [2]})
    kept = c.streams[1]
    c.sync([snap(20, 2)], {}, datetime.now())
    assert c.streams == [kept]


def test_sync_reorders_flows():
    c = campaign({10: []}, {20: []})
    c.sync([snap(10, position=2), snap(20, position=1)], {}, datetime.now())
    assert [s.keitaro_id for s in c.streams] == [20, 10]
