"""Campaign aggregate: local copy of Keitaro flows and their offers.

Offers are edited locally and published to Keitaro per flow. `StreamOffer.published_*`
is a snapshot of what Keitaro has, so a flow knows whether it has unpublished changes
and can roll them back.

Entities are plain Pydantic models and know nothing about the database: the repository
builds them from table rows with `from_orm` and writes them back on save.
"""

from collections.abc import Iterable, Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field

from app.domain.errors import ConflictError, DomainError, NotFoundError


class Entity(BaseModel):
    """Mutable, has an identity: `id` is None until the entity is saved.

    Two objects are the same entity when they have the same id, whatever their fields say;
    unsaved ones are only equal to themselves.
    """

    id: int | None = None

    def __eq__(self, other: object) -> bool:
        if self is other:
            return True
        return type(self) is type(other) and self.id is not None and self.id == other.id


class ValueObject(BaseModel):
    """Immutable, compares by value; unlike the entities it is never stored."""

    model_config = ConfigDict(frozen=True)


class OfferState(StrEnum):
    ACTIVE = "active"
    REMOVED = "removed"


class OfferShare(ValueObject):
    offer_id: int
    share: int


class StreamSnapshot(ValueObject):
    """A flow as the tracker has it."""

    keitaro_id: int
    name: str
    position: int
    # `schema` shadows a BaseModel attribute
    schema_: str = Field(alias="schema")
    offers: list[OfferShare]


class StreamOffer(Entity):
    """Offer bound to a flow.

    `state`/`share` are the local (editable) values, `published_*` is a snapshot of what
    Keitaro has. `published_state` is None for offers added locally and never published.
    """

    offer_id: int
    offer_name: str = ""
    state: OfferState = OfferState.ACTIVE
    share: int = 0
    pinned: bool = False
    published_state: OfferState | None = None
    published_share: int | None = None

    @classmethod
    def from_orm(cls, row: Any) -> Self:
        return cls(
            id=row.id,
            offer_id=row.offer_id,
            offer_name=row.offer_name,
            state=row.state,
            share=row.share,
            pinned=row.pinned,
            published_state=row.published_state,
            published_share=row.published_share,
        )

    @property
    def is_active(self) -> bool:
        return self.state == OfferState.ACTIVE

    @property
    def is_new(self) -> bool:
        return self.published_state is None

    @property
    def is_dirty(self) -> bool:
        if self.state != self.published_state:
            return True
        return self.is_active and self.share != self.published_share


class Stream(Entity):
    keitaro_id: int
    name: str = ""
    position: int = 0
    # `schema` shadows a BaseModel attribute
    schema_: str = Field(default="", alias="schema")
    offers: list[StreamOffer] = Field(default_factory=list)

    @classmethod
    def from_orm(cls, row: Any) -> Self:
        return cls(
            id=row.id,
            keitaro_id=row.keitaro_id,
            name=row.name,
            position=row.position,
            schema=row.schema,
            offers=[StreamOffer.from_orm(o) for o in row.offers],
        )

    @property
    def is_dirty(self) -> bool:
        """True when the local offer set differs from what was last published to Keitaro."""
        return any(o.is_dirty for o in self.offers)

    def find_offer(self, offer_id: int) -> StreamOffer | None:
        return next((o for o in self.offers if o.offer_id == offer_id), None)

    def get_offer(self, stream_offer_id: int) -> StreamOffer:
        so = next((o for o in self.offers if o.id == stream_offer_id), None)
        if so is None:
            raise NotFoundError("Offer is not bound to the stream")
        return so

    def add_offer(self, offer_id: int, offer_name: str = "") -> None:
        existing = self.find_offer(offer_id)
        if existing is not None:
            if existing.is_active:
                raise ConflictError("Offer is already in the stream")
            existing.state = OfferState.ACTIVE
        else:
            self.offers.append(StreamOffer(offer_id=offer_id, offer_name=offer_name))
        self.rebalance()

    def remove_offer(self, stream_offer_id: int) -> None:
        so = self.get_offer(stream_offer_id)
        if not so.is_active:
            raise ConflictError("Offer is already removed")
        so.state = OfferState.REMOVED
        self.rebalance()

    def bring_back_offer(self, stream_offer_id: int) -> None:
        so = self.get_offer(stream_offer_id)
        if so.is_active:
            raise ConflictError("Offer is already active")
        so.state = OfferState.ACTIVE
        self.rebalance()

    def pin_offer(self, stream_offer_id: int, pinned: bool) -> None:
        so = self.get_offer(stream_offer_id)
        if pinned and not so.is_active:
            raise ConflictError("Only active offers can be pinned")
        so.pinned = pinned

    def offers_to_publish(self) -> list[OfferShare]:
        active = [o for o in self.offers if o.is_active]
        if not active:
            raise DomainError("Stream must have at least one active offer")
        total = sum(o.share for o in active)
        if total != 100:
            raise DomainError(f"Offer shares must sum up to 100%, got {total}%")
        return [OfferShare(offer_id=o.offer_id, share=o.share) for o in active]

    def mark_published(self) -> None:
        for o in self.offers:
            o.published_state = o.state
            o.published_share = o.share

    def cancel_changes(self) -> None:
        """Drop unpublished changes: new offers are deleted, everything else goes back to the snapshot."""
        for o in list(self.offers):
            if o.is_new:
                self.offers.remove(o)
                continue
            o.state = o.published_state
            o.share = o.published_share or 0
            if not o.is_active:
                o.pinned = False

    def sync_offers(self, remote: Iterable[OfferShare], offer_names: Mapping[int, str]) -> None:
        """Make the offers match Keitaro; `offer_names` must cover offers new to this flow."""
        local = {o.offer_id: o for o in self.offers}
        remote_ids = set()

        for ro in remote:
            remote_ids.add(ro.offer_id)
            so = local.get(ro.offer_id)
            if so is None:
                so = StreamOffer(offer_id=ro.offer_id, offer_name=offer_names.get(ro.offer_id, ""))
                self.offers.append(so)
            so.state = OfferState.ACTIVE
            so.share = ro.share
            so.published_state = OfferState.ACTIVE
            so.published_share = so.share

        for offer_id, so in local.items():
            if offer_id in remote_ids:
                continue
            if so.is_new:
                # added locally and never published -> nothing to keep
                self.offers.remove(so)
                continue
            so.state = OfferState.REMOVED
            so.share = 0
            so.pinned = False
            so.published_state = OfferState.REMOVED
            so.published_share = 0

    def rebalance(self) -> None:
        """Recalculate shares in place so that active offers sum up to 100%.

        Removed offers get 0%. Pinned active offers keep their share; the rest of the
        100% is split evenly between unpinned active offers (Keitaro wants integers,
        so the remainder goes to the first ones: 34/33/33). If every active offer is
        pinned, pins are ignored and the 100% is split evenly between them.
        """
        active = [o for o in self.offers if o.is_active]
        for o in self.offers:
            if not o.is_active:
                o.share = 0
                o.pinned = False

        free = [o for o in active if not o.pinned]
        if not free:
            # only pinned offers left: they can't keep their shares and still sum up to 100%
            free = active
            if not free:
                return
        pinned_total = sum(o.share for o in active if o not in free)
        rest = max(0, 100 - pinned_total)
        base, remainder = divmod(rest, len(free))
        for i, o in enumerate(free):
            o.share = base + (1 if i < remainder else 0)


class Campaign(Entity):
    keitaro_id: int
    name: str
    alias: str = ""
    # set by the database when the campaign is first saved
    created_at: datetime | None = None
    synced_at: datetime | None = None
    streams: list[Stream] = Field(default_factory=list)

    @classmethod
    def from_orm(cls, row: Any) -> Self:
        return cls(
            id=row.id,
            keitaro_id=row.keitaro_id,
            name=row.name,
            alias=row.alias,
            created_at=row.created_at,
            synced_at=row.synced_at,
            streams=[Stream.from_orm(s) for s in row.streams],
        )

    def new_offer_ids(self, snapshots: Iterable[StreamSnapshot]) -> set[int]:
        """Offers that the snapshots bind to flows which don't have them locally yet."""
        local = {s.keitaro_id: {o.offer_id for o in s.offers} for s in self.streams}
        return {
            o.offer_id
            for snap in snapshots
            for o in snap.offers
            if o.offer_id not in local.get(snap.keitaro_id, ())
        }

    def sync(self, snapshots: Iterable[StreamSnapshot], offer_names: Mapping[int, str], synced_at: datetime) -> None:
        """"Fetch streams": make the local copy match Keitaro.

        Keitaro is the source of truth: unpublished local changes are discarded, offers
        that disappeared from Keitaro stay locally as `removed` (they can be brought back).
        """
        local = {s.keitaro_id: s for s in self.streams}
        seen = set()

        for snap in snapshots:
            seen.add(snap.keitaro_id)
            stream = local.get(snap.keitaro_id)
            if stream is None:
                stream = Stream(keitaro_id=snap.keitaro_id)
                self.streams.append(stream)
            stream.name = snap.name
            stream.position = snap.position
            stream.schema_ = snap.schema_
            stream.sync_offers(snap.offers, offer_names)

        for keitaro_id, stream in local.items():
            if keitaro_id not in seen:
                self.streams.remove(stream)

        self.streams.sort(key=lambda s: s.position)
        self.synced_at = synced_at
