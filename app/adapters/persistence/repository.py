"""Campaign repository: loads rows into domain entities and writes entities back to rows.

The session stays the unit of work: `save*` only flushes, the use case commits.
"""

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.persistence.orm import CampaignORM, StreamOfferORM, StreamORM
from app.domain.errors import NotFoundError
from app.domain.models import Campaign, Entity, Stream, StreamOffer


class CampaignRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_keitaro_id(self, keitaro_id: int) -> Campaign | None:
        row = await self._session.scalar(select(CampaignORM).where(CampaignORM.keitaro_id == keitaro_id))
        return Campaign.from_orm(row) if row else None

    async def get_stream(self, stream_id: int) -> Stream | None:
        row = await self._session.get(StreamORM, stream_id)
        return Stream.from_orm(row) if row else None

    async def get_stream_by_offer(self, stream_offer_id: int) -> Stream | None:
        row = await self._session.scalar(
            select(StreamORM).join(StreamORM.offers).where(StreamOfferORM.id == stream_offer_id)
        )
        return Stream.from_orm(row) if row else None

    async def save(self, campaign: Campaign) -> Campaign:
        """Insert or update the campaign with its streams and offers; returns it with the ids filled in."""
        if campaign.id is None:
            row = CampaignORM()
            self._session.add(row)
        else:
            row = await self._row(CampaignORM, campaign.id)
        _write_campaign(row, campaign)
        await self._session.flush()
        return Campaign.from_orm(row)

    async def save_stream(self, stream: Stream) -> Stream:
        """Update an existing stream with its offers; returns it with the ids filled in."""
        if stream.id is None:
            raise ValueError("A new stream is saved together with its campaign")
        row = await self._row(StreamORM, stream.id)
        _write_stream(row, stream)
        await self._session.flush()
        return Stream.from_orm(row)

    async def _row[T](self, model: type[T], id_: int) -> T:
        row = await self._session.get(model, id_)
        if row is None:
            raise NotFoundError(f"{model.__tablename__} #{id_} doesn't exist")
        return row


def _write_campaign(row: CampaignORM, campaign: Campaign) -> None:
    row.keitaro_id = campaign.keitaro_id
    row.name = campaign.name
    row.alias = campaign.alias
    row.synced_at = campaign.synced_at
    row.streams = _merge(row.streams, campaign.streams, StreamORM, _write_stream)


def _write_stream(row: StreamORM, stream: Stream) -> None:
    row.keitaro_id = stream.keitaro_id
    row.name = stream.name
    row.position = stream.position
    row.schema = stream.schema_
    row.offers = _merge(row.offers, stream.offers, StreamOfferORM, _write_offer)


def _write_offer(row: StreamOfferORM, offer: StreamOffer) -> None:
    row.offer_id = offer.offer_id
    row.offer_name = offer.offer_name
    row.state = offer.state
    row.share = offer.share
    row.pinned = offer.pinned
    row.published_state = offer.published_state
    row.published_share = offer.published_share


def _merge[R, E: Entity](rows: list[R], entities: list[E], new_row: Callable[[], R], write: Callable[[R, E], None]) -> list[R]:
    """Rows for the entities in their order: known ids update their row, the rest get a new one.

    Rows left out of the result are orphans, and the relationship cascade deletes them.
    """
    by_id = {r.id: r for r in rows}
    result = []
    for entity in entities:
        row = by_id.get(entity.id) or new_row()
        write(row, entity)
        result.append(row)
    return result
