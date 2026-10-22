"""Database tables. Only the repository works with these rows; the rest of the app sees domain entities."""

from datetime import datetime

from sqlalchemy import ForeignKey, MetaData, String, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    })


class StreamOfferORM(Base):
    __tablename__ = "stream_offer"
    __table_args__ = (UniqueConstraint("stream_id", "offer_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("stream.id", ondelete="CASCADE"))
    offer_id: Mapped[int]
    offer_name: Mapped[str] = mapped_column(String(512))
    state: Mapped[str] = mapped_column(String(16))
    share: Mapped[int]
    pinned: Mapped[bool]
    published_state: Mapped[str | None] = mapped_column(String(16))
    published_share: Mapped[int | None]


class StreamORM(Base):
    __tablename__ = "stream"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaign.id", ondelete="CASCADE"))
    keitaro_id: Mapped[int] = mapped_column(unique=True)
    name: Mapped[str] = mapped_column(String(255))
    position: Mapped[int]
    schema: Mapped[str] = mapped_column(String(32))
    # collections load eagerly: lazy loading doesn't work with an async session
    offers: Mapped[list[StreamOfferORM]] = relationship(
        cascade="all, delete-orphan", order_by=StreamOfferORM.id, lazy="selectin"
    )


class CampaignORM(Base):
    __tablename__ = "campaign"
    # created_at comes from the DB; fetch it on INSERT so the row converts to an entity without a lazy load
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[int] = mapped_column(primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(unique=True)
    name: Mapped[str] = mapped_column(String(255))
    alias: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    synced_at: Mapped[datetime | None]
    streams: Mapped[list[StreamORM]] = relationship(
        cascade="all, delete-orphan", order_by=StreamORM.position, lazy="selectin"
    )
