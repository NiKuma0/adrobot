"""CampaignRepository on the test database: domain entities in, domain entities out."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.adapters.persistence.orm import CampaignORM, StreamOfferORM, StreamORM
from app.adapters.persistence.repository import CampaignRepository
from app.domain.errors import NotFoundError
from app.domain.models import Campaign, OfferState, Stream, StreamOffer

pytestmark = pytest.mark.anyio


def new_campaign(keitaro_id=1) -> Campaign:
    """Flows are listed out of order: 20 (pos 2, offers 4, 3) and 10 (pos 1, offer 2)."""
    return Campaign(keitaro_id=keitaro_id, name="Spring", alias="spring-1", streams=[
        Stream(keitaro_id=keitaro_id * 100 + 20, name="Offers", position=2, schema="landings", offers=[
            StreamOffer(offer_id=4, offer_name="Four", share=60, pinned=True,
                        published_state=OfferState.ACTIVE, published_share=60),
            StreamOffer(offer_id=3, offer_name="Three", state=OfferState.REMOVED),
        ]),
        Stream(keitaro_id=keitaro_id * 100 + 10, name="Geo", position=1, schema="redirect"),
    ])


def flow(c: Campaign, keitaro_id: int) -> Stream:
    return next(s for s in c.streams if s.keitaro_id == keitaro_id)


@pytest.fixture
def repo(session):
    return CampaignRepository(session)


@pytest.fixture
def fresh_repo(session_factory):
    """A repository on its own session: reads go to the database, not the identity map."""
    async def get(method, *args):
        async with session_factory() as fresh:
            return await getattr(CampaignRepository(fresh), method)(*args)
    return get


@pytest.fixture
async def saved(repo, session) -> Campaign:
    c = await repo.save(new_campaign())
    await session.commit()
    return c


async def counts(session) -> tuple[int, int, int]:
    return tuple([await session.scalar(select(func.count()).select_from(m))
                  for m in (CampaignORM, StreamORM, StreamOfferORM)])


# --- save a new campaign ---------------------------------------------------------------


async def test_save_returns_a_new_entity_with_ids(repo):
    draft = new_campaign()
    saved = await repo.save(draft)

    assert saved is not draft
    assert draft.id is None  # the draft is left as it was
    assert isinstance(saved, Campaign)
    assert saved.id is not None and saved.created_at is not None
    assert all(s.id for s in saved.streams)
    assert all(o.id for s in saved.streams for o in s.offers)


async def test_save_keeps_the_order_it_was_given(repo):
    saved = await repo.save(new_campaign())
    assert [s.keitaro_id for s in saved.streams] == [120, 110]
    assert [o.offer_id for o in saved.streams[0].offers] == [4, 3]


async def test_saved_campaign_loads_back(fresh_repo, saved):
    loaded = await fresh_repo("get_by_keitaro_id", 1)

    assert isinstance(loaded, Campaign)
    assert loaded == saved and loaded is not saved
    assert (loaded.keitaro_id, loaded.name, loaded.alias, loaded.created_at, loaded.synced_at) == (
        1, "Spring", "spring-1", saved.created_at, None
    )
    # loaded in DB order: flows by position, offers by id
    assert [(s.keitaro_id, s.name, s.position, s.schema_) for s in loaded.streams] == [
        (110, "Geo", 1, "redirect"), (120, "Offers", 2, "landings")
    ]
    assert [o.model_dump(exclude={"id"}) for o in flow(loaded, 120).offers] == [
        {"offer_id": 4, "offer_name": "Four", "state": "active", "share": 60, "pinned": True,
         "published_state": "active", "published_share": 60},
        {"offer_id": 3, "offer_name": "Three", "state": "removed", "share": 0, "pinned": False,
         "published_state": None, "published_share": None},
    ]


# --- lookups ---------------------------------------------------------------------------


@pytest.mark.parametrize("lookup", ["get_by_keitaro_id", "get_stream", "get_stream_by_offer"])
async def test_lookup_misses(fresh_repo, saved, lookup):
    assert await fresh_repo(lookup, 999) is None


async def test_get_stream(fresh_repo, saved):
    geo = flow(saved, 110)
    loaded = await fresh_repo("get_stream", geo.id)
    assert isinstance(loaded, Stream)
    assert (loaded.id, loaded.keitaro_id, loaded.offers) == (geo.id, 110, [])


@pytest.mark.parametrize("offer_index", [0, 1])
async def test_get_stream_by_offer(fresh_repo, saved, offer_index):
    stream = flow(saved, 120)
    loaded = await fresh_repo("get_stream_by_offer", stream.offers[offer_index].id)
    assert loaded == stream
    assert loaded.offers == stream.offers  # all offers, not only the matched one


async def test_lookups_ignore_other_campaigns(fresh_repo, repo, session, saved):
    other = await repo.save(new_campaign(keitaro_id=2))
    await session.commit()
    assert await fresh_repo("get_by_keitaro_id", 2) == other
    assert await fresh_repo("get_stream_by_offer", other.streams[0].offers[0].id) == other.streams[0]


async def test_loaded_entities_are_detached(repo, fresh_repo, session, saved):
    stream = await repo.get_stream(flow(saved, 120).id)
    stream.offers[0].share = 1
    stream.name = "changed"
    await session.commit()  # nothing was saved
    loaded = await fresh_repo("get_stream", stream.id)
    assert (loaded.name, loaded.offers[0].share) == ("Offers", 60)


# --- save changes ----------------------------------------------------------------------


async def test_save_stream(repo, fresh_repo, session, saved):
    stream = await repo.get_stream(flow(saved, 120).id)
    stream.add_offer(5, "Five")
    stream.remove_offer(stream.offers[0].id)

    result = await repo.save_stream(stream)
    await session.commit()

    assert result.offers[-1].id is not None  # the new offer got its id
    loaded = await fresh_repo("get_stream", stream.id)
    assert loaded.offers == result.offers
    assert [(o.offer_id, o.state, o.share, o.is_new) for o in loaded.offers] == [
        (4, "removed", 0, False), (3, "removed", 0, True), (5, "active", 100, True)
    ]


async def test_save_stream_updates_rows_in_place(repo, session, saved):
    stream = await repo.get_stream(flow(saved, 120).id)
    ids = [o.id for o in stream.offers]
    stream.pin_offer(ids[0], False)
    result = await repo.save_stream(stream)
    assert [o.id for o in result.offers] == ids
    assert await counts(session) == (1, 2, 2)


async def test_save_campaign_changes(repo, fresh_repo, session, saved):
    c = await repo.get_by_keitaro_id(1)
    c.name = "Renamed"
    c.streams.remove(flow(c, 110))
    flow(c, 120).offers.pop()
    c.streams.append(Stream(keitaro_id=130, position=3, offers=[StreamOffer(offer_id=9, share=100)]))

    await repo.save(c)
    await session.commit()

    loaded = await fresh_repo("get_by_keitaro_id", 1)
    assert loaded.name == "Renamed"
    assert [(s.keitaro_id, [o.offer_id for o in s.offers]) for s in loaded.streams] == [(120, [4]), (130, [9])]
    assert flow(loaded, 120) == flow(saved, 120)  # same row, updated
    assert await counts(session) == (1, 2, 2)  # dropped flow and offer are deleted


async def test_save_empty_campaign_deletes_everything_below(repo, session, saved):
    saved.streams.clear()
    await repo.save(saved)
    await session.commit()
    assert await counts(session) == (1, 0, 0)


@pytest.mark.parametrize(
    ("method", "entity"),
    [
        pytest.param("save", Campaign(id=999, keitaro_id=9, name="gone"), id="campaign"),
        pytest.param("save_stream", Stream(id=999, keitaro_id=9), id="stream"),
    ],
)
async def test_save_unknown_id(repo, method, entity):
    with pytest.raises(NotFoundError):
        await getattr(repo, method)(entity)


async def test_save_stream_needs_an_id(repo):
    with pytest.raises(ValueError, match="together with its campaign"):
        await repo.save_stream(Stream(keitaro_id=9))


@pytest.mark.parametrize(
    "duplicate",
    [
        pytest.param(lambda c: Campaign(keitaro_id=c.keitaro_id, name="dup"), id="campaign-keitaro-id"),
        pytest.param(lambda c: Campaign(keitaro_id=2, name="dup", streams=[Stream(keitaro_id=110)]),
                     id="stream-keitaro-id"),
        pytest.param(lambda c: c.model_copy(update={"streams": [
            flow(c, 120).model_copy(update={"offers": [*flow(c, 120).offers, StreamOffer(offer_id=4)]}),
        ]}), id="offer-in-stream"),
    ],
)
async def test_unique_constraints(repo, session, saved, duplicate):
    with pytest.raises(IntegrityError):
        await repo.save(duplicate(saved))
        await session.commit()
