from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    geo: str = Field(min_length=2, description="Comma-separated country codes, e.g. MX,AU,RO")
    offer_id: int
    group_id: int | None = None
    traffic_source_id: int | None = None
    domain_id: int | None = None


class OfferAdd(BaseModel):
    offer_id: int


class PinRequest(BaseModel):
    pinned: bool


class OutModel(BaseModel):
    """Response built from domain objects / ORM rows."""

    model_config = ConfigDict(from_attributes=True)


class OfferOut(OutModel):
    id: int
    name: str
    state: str | None


class NamedItemOut(OutModel):
    id: int
    name: str


class DefaultsOut(OutModel):
    group_id: int | None
    traffic_source_id: int | None
    domain_id: int | None


class FormOptionsOut(OutModel):
    groups: list[NamedItemOut]
    traffic_sources: list[NamedItemOut]
    domains: list[NamedItemOut]
    defaults: DefaultsOut


class TrackerCampaignOut(OutModel):
    id: int
    name: str
    alias: str
    state: str | None


class StreamOfferOut(OutModel):
    id: int
    offer_id: int
    offer_name: str
    state: str
    share: int
    pinned: bool
    is_new: bool
    is_dirty: bool


class StreamOut(OutModel):
    id: int
    keitaro_id: int
    name: str
    position: int
    # read from the entity's `schema_`: `schema` shadows a BaseModel attribute
    schema_: str = Field(serialization_alias="schema")
    is_dirty: bool
    offers: list[StreamOfferOut]


class CampaignOut(OutModel):
    id: int
    keitaro_id: int
    name: str
    alias: str
    synced_at: datetime | None
    streams: list[StreamOut]

    @field_serializer("synced_at")
    def _seconds(self, value: datetime | None) -> str | None:
        return value.isoformat(timespec="seconds") if value else None
