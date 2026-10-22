"""Ports: what the use cases need from the outside world. Adapters implement them."""

from typing import Any, Protocol

from app.domain.models import Campaign, OfferShare, Stream, StreamSnapshot, ValueObject


class TrackerError(Exception):
    def __init__(self, status: int, detail: Any):
        super().__init__(f"Tracker API error {status}: {detail}")
        self.status = status
        self.detail = detail


class TrackerCampaign(ValueObject):
    id: int
    name: str
    alias: str = ""
    state: str | None = None


class TrackerOffer(ValueObject):
    id: int
    name: str
    state: str | None = None


class NamedItem(ValueObject):
    id: int
    name: str


class NewCampaign(ValueObject):
    name: str
    alias: str
    group_id: int | None = None
    traffic_source_id: int | None = None
    domain_id: int | None = None


class Tracker(Protocol):
    """Traffic tracker (Keitaro). Raises TrackerError when the call fails."""

    async def list_campaigns(self) -> list[TrackerCampaign]: ...

    async def get_campaign(self, campaign_id: int) -> TrackerCampaign: ...

    async def create_campaign(self, campaign: NewCampaign) -> TrackerCampaign: ...

    async def delete_campaign(self, campaign_id: int) -> None: ...

    async def get_campaign_streams(self, campaign_id: int) -> list[StreamSnapshot]: ...

    async def create_redirect_stream(
        self, campaign_id: int, *, name: str, position: int, url: str, countries: list[str]
    ) -> int:
        """Flow that redirects visitors from `countries` to `url`; returns its id."""
        ...

    async def create_offers_stream(
        self, campaign_id: int, *, name: str, position: int, offers: list[OfferShare]
    ) -> int:
        """Catch-all flow that sends visitors to `offers`; returns its id."""
        ...

    async def update_stream_offers(self, stream_id: int, offers: list[OfferShare]) -> None: ...

    async def list_offers(self) -> list[TrackerOffer]: ...

    async def get_offer(self, offer_id: int) -> TrackerOffer: ...

    async def list_groups(self) -> list[NamedItem]: ...

    async def list_traffic_sources(self) -> list[NamedItem]: ...

    async def list_domains(self) -> list[NamedItem]: ...


class CampaignRepository(Protocol):
    """Loaded campaigns and streams come with their streams/offers.

    Entities are detached copies: changes are stored only by `save`/`save_stream`, which
    return the stored version (with ids of the new streams/offers filled in).
    """

    async def save(self, campaign: Campaign) -> Campaign: ...

    async def save_stream(self, stream: Stream) -> Stream: ...

    async def get_by_keitaro_id(self, keitaro_id: int) -> Campaign | None: ...

    async def get_stream(self, stream_id: int) -> Stream | None: ...

    async def get_stream_by_offer(self, stream_offer_id: int) -> Stream | None:
        """The stream the given StreamOffer belongs to."""
        ...

