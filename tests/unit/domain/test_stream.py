"""Stream rules: share rebalancing, offer editing, publish/cancel and sync with Keitaro.

Pure domain: entities are built in memory, no session.
"""

import pytest

from app.domain.errors import ConflictError, DomainError, NotFoundError
from app.domain.models import OfferShare, OfferState, Stream, StreamOffer

ACTIVE, REMOVED = OfferState.ACTIVE, OfferState.REMOVED


def so(offer_id, share=0, state=ACTIVE, *, pinned=False, new=False, published=None, name=""):
    """StreamOffer with id = 100 + offer_id; published as is unless `new` or `published` says otherwise."""
    o = StreamOffer(offer_id=offer_id, offer_name=name or f"Offer {offer_id}", state=state, share=share, pinned=pinned)
    if not new:
        o.published_state, o.published_share = published or (state, share)
    o.id = 100 + offer_id
    return o


def stream(*offers: StreamOffer) -> Stream:
    s = Stream(keitaro_id=1, offers=list(offers))
    s.id = 1
    return s


def rows(s: Stream) -> list[tuple]:
    return [(o.offer_id, o.state, o.share, o.pinned) for o in s.offers]


# --- rebalance -------------------------------------------------------------------------

# offer spec: (state, share before, pinned) -> share after
A, P, R = (ACTIVE, False), (ACTIVE, True), (REMOVED, True)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        pytest.param([(A, 0)], [100], id="single"),
        pytest.param([(A, 0)] * 2, [50, 50], id="two"),
        pytest.param([(A, 0)] * 3, [34, 33, 33], id="remainder-to-first"),
        pytest.param([(A, 0)] * 4, [25] * 4, id="four"),
        pytest.param([(A, 0)] * 6, [17, 17, 17, 17, 16, 16], id="six"),
        pytest.param([(A, 0)] * 7, [15, 15, 14, 14, 14, 14, 14], id="seven"),
        pytest.param([(A, 10), (R, 40), (A, 50)], [50, 0, 50], id="removed-get-zero"),
        pytest.param([(P, 40), (A, 0), (A, 0)], [40, 30, 30], id="pinned-keeps-share"),
        pytest.param([(P, 25), (A, 0), (A, 0)], [25, 38, 37], id="pinned-and-remainder"),
        pytest.param([(P, 10), (P, 20), (A, 0)], [10, 20, 70], id="several-pinned"),
        pytest.param([(P, 70), (P, 10)], [50, 50], id="all-pinned-split-evenly"),
        pytest.param([(P, 100), (A, 0)], [100, 0], id="pinned-takes-everything"),
        pytest.param([(R, 30), (R, 70)], [0, 0], id="nothing-active"),
        pytest.param([], [], id="empty"),
    ],
)
def test_rebalance(before, after):
    s = stream(*(so(i, share, state, pinned=pinned) for i, ((state, pinned), share) in enumerate(before, 1)))
    s.rebalance()
    assert [o.share for o in s.offers] == after
    if any(o.is_active for o in s.offers):
        assert sum(o.share for o in s.offers) == 100


def test_rebalance_unpins_removed_offers_only():
    s = stream(so(1, 50, pinned=True), so(2, 50, REMOVED, pinned=True), so(3))
    s.rebalance()
    assert [o.pinned for o in s.offers] == [True, False, False]


def test_rebalance_keeps_pins_when_all_active_are_pinned():
    s = stream(so(1, 70, pinned=True), so(2, 10, pinned=True))
    s.rebalance()
    assert [o.pinned for o in s.offers] == [True, True]


# --- offer state -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("offer", "dirty"),
    [
        pytest.param(so(1, 50, new=True), True, id="never-published"),
        pytest.param(so(1, 50), False, id="as-published"),
        pytest.param(so(1, 50, published=(ACTIVE, 40)), True, id="share-changed"),
        pytest.param(so(1, 0, REMOVED, published=(ACTIVE, 40)), True, id="removed-locally"),
        pytest.param(so(1, 50, published=(REMOVED, 0)), True, id="brought-back-locally"),
        pytest.param(so(1, 0, REMOVED, published=(REMOVED, 30)), False, id="removed-share-ignored"),
    ],
)
def test_offer_is_dirty(offer, dirty):
    assert offer.is_dirty is dirty
    assert stream(so(2, 50), offer).is_dirty is dirty


@pytest.mark.parametrize(("state", "active"), [(ACTIVE, True), (REMOVED, False)])
def test_offer_is_active(state, active):
    assert so(1, state=state).is_active is active


def test_new_offer_defaults():
    o = StreamOffer(offer_id=7)
    assert (o.state, o.share, o.pinned, o.is_new, o.offer_name) == (ACTIVE, 0, False, True, "")


def test_find_and_get_offer():
    first, second = so(1), so(2)
    s = stream(first, second)
    assert s.find_offer(2) is second
    assert s.find_offer(3) is None
    assert s.get_offer(101) is first
    with pytest.raises(NotFoundError):
        s.get_offer(1)  # that's an offer id, not a stream offer id


# --- editing ---------------------------------------------------------------------------


def test_add_offer():
    s = stream(so(1, 50), so(2, 50))
    s.add_offer(3, "Third")
    assert rows(s) == [(1, ACTIVE, 34, False), (2, ACTIVE, 33, False), (3, ACTIVE, 33, False)]
    added = s.offers[-1]
    assert (added.offer_name, added.is_new) == ("Third", True)
    assert s.is_dirty


def test_add_offer_brings_back_a_removed_one():
    removed = so(2, 0, REMOVED, name="Kept name")
    s = stream(so(1, 100), removed)
    s.add_offer(2, "ignored")
    assert rows(s) == [(1, ACTIVE, 50, False), (2, ACTIVE, 50, False)]
    assert s.offers[1] is removed
    assert removed.offer_name == "Kept name"


def test_add_offer_already_active():
    s = stream(so(1, 100))
    with pytest.raises(ConflictError):
        s.add_offer(1)
    assert rows(s) == [(1, ACTIVE, 100, False)]


def test_remove_offer():
    s = stream(so(1, 34, pinned=True), so(2, 33), so(3, 33))
    s.remove_offer(101)
    assert rows(s) == [(1, REMOVED, 0, False), (2, ACTIVE, 50, False), (3, ACTIVE, 50, False)]


def test_bring_back_offer():
    s = stream(so(1, 0, REMOVED), so(2, 100))
    s.bring_back_offer(101)
    assert rows(s) == [(1, ACTIVE, 50, False), (2, ACTIVE, 50, False)]


@pytest.mark.parametrize(
    ("action", "state", "error"),
    [
        ("remove_offer", REMOVED, ConflictError),
        ("bring_back_offer", ACTIVE, ConflictError),
    ],
)
def test_state_change_conflicts(action, state, error):
    s = stream(so(1, 100 if state == ACTIVE else 0, state), so(2, 100 if state == REMOVED else 0))
    before = rows(s)
    with pytest.raises(error):
        getattr(s, action)(101)
    assert rows(s) == before


@pytest.mark.parametrize("action", ["remove_offer", "bring_back_offer", "pin_offer"])
def test_unknown_stream_offer(action):
    s = stream(so(1, 100))
    args = (999, True) if action == "pin_offer" else (999,)
    with pytest.raises(NotFoundError):
        getattr(s, action)(*args)


@pytest.mark.parametrize(
    ("state", "pinned", "error"),
    [
        (ACTIVE, True, None),
        (ACTIVE, False, None),
        (REMOVED, False, None),
        (REMOVED, True, ConflictError),
    ],
)
def test_pin_offer(state, pinned, error):
    o = so(1, 60 if state == ACTIVE else 0, state, pinned=not pinned and state == ACTIVE)
    s = stream(o, so(2, 40 if state == ACTIVE else 100))
    shares = [x.share for x in s.offers]
    if error:
        with pytest.raises(error):
            s.pin_offer(101, pinned)
    else:
        s.pin_offer(101, pinned)
        assert o.pinned is pinned
    assert [x.share for x in s.offers] == shares  # pinning doesn't rebalance


# --- publish / cancel ------------------------------------------------------------------


def test_offers_to_publish_skips_removed():
    s = stream(so(1, 60), so(2, 0, REMOVED), so(3, 40, new=True))
    assert s.offers_to_publish() == [OfferShare(offer_id=1, share=60), OfferShare(offer_id=3, share=40)]


@pytest.mark.parametrize(
    ("offers", "message"),
    [
        pytest.param([], "at least one active offer", id="empty"),
        pytest.param([so(1, 0, REMOVED)], "at least one active offer", id="all-removed"),
        pytest.param([so(1, 50), so(2, 49)], "got 99%", id="under-100"),
        pytest.param([so(1, 50), so(2, 51)], "got 101%", id="over-100"),
    ],
)
def test_offers_to_publish_invalid(offers, message):
    with pytest.raises(DomainError, match=message) as e:
        stream(*offers).offers_to_publish()
    assert type(e.value) is DomainError


def test_mark_published():
    s = stream(so(1, 50, published=(ACTIVE, 100)), so(2, 50, new=True), so(3, 0, REMOVED, published=(ACTIVE, 0)))
    s.mark_published()
    assert [(o.published_state, o.published_share) for o in s.offers] == [(ACTIVE, 50), (ACTIVE, 50), (REMOVED, 0)]
    assert not s.is_dirty


def test_cancel_changes():
    s = stream(
        so(1, 40, pinned=True, published=(ACTIVE, 50)),  # share changed -> restored, pin kept
        so(2, 0, REMOVED, published=(ACTIVE, 50)),  # removed locally -> active again
        so(3, 30, ACTIVE, pinned=True, published=(REMOVED, 0)),  # brought back locally -> removed, unpinned
        so(4, 30, new=True),  # never published -> dropped
    )
    s.cancel_changes()
    assert rows(s) == [(1, ACTIVE, 50, True), (2, ACTIVE, 50, False), (3, REMOVED, 0, False)]
    assert not s.is_dirty


def test_cancel_without_changes_is_noop():
    s = stream(so(1, 50), so(2, 50))
    before = rows(s)
    s.cancel_changes()
    assert rows(s) == before


# --- sync with Keitaro -----------------------------------------------------------------


def test_sync_offers():
    s = stream(
        so(1, 50, pinned=True),  # still in Keitaro, share changed there
        so(2, 0, REMOVED, published=(REMOVED, 0)),  # back in Keitaro
        so(3, 50, pinned=True),  # gone from Keitaro -> archived
        so(4, 20, new=True),  # local only -> dropped
    )
    remote = [OfferShare(offer_id=1, share=30), OfferShare(offer_id=2, share=20), OfferShare(offer_id=5, share=50)]
    s.sync_offers(remote, {5: "Fresh"})
    assert rows(s) == [
        (1, ACTIVE, 30, True),
        (2, ACTIVE, 20, False),
        (3, REMOVED, 0, False),
        (5, ACTIVE, 50, False),
    ]
    assert s.offers[-1].offer_name == "Fresh"
    assert [(o.published_state, o.published_share) for o in s.offers] == [
        (ACTIVE, 30), (ACTIVE, 20), (REMOVED, 0), (ACTIVE, 50)
    ]
    assert not s.is_dirty


def test_sync_offers_discards_local_changes():
    s = stream(so(1, 70, published=(ACTIVE, 50)), so(2, 0, REMOVED, published=(ACTIVE, 50)))
    s.sync_offers([OfferShare(offer_id=1, share=50), OfferShare(offer_id=2, share=50)], {})
    assert rows(s) == [(1, ACTIVE, 50, False), (2, ACTIVE, 50, False)]
    assert not s.is_dirty


def test_sync_offers_without_a_name():
    s = stream()
    s.sync_offers([OfferShare(offer_id=9, share=100)], {})
    assert s.offers[0].offer_name == ""


def test_sync_offers_with_empty_remote_archives_everything():
    s = stream(so(1, 50), so(2, 50))
    s.sync_offers([], {})
    assert rows(s) == [(1, REMOVED, 0, False), (2, REMOVED, 0, False)]
