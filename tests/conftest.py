import pytest

from app.application.ports import (
    NewCampaign,
    TrackerCampaign,
    TrackerError,
    TrackerOffer,
)
from app.domain.models import StreamSnapshot


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeTracker:
    def __init__(self):
        self.offers = [TrackerOffer(id=i, name=f"Offer {i}", state="active") for i in (1, 2, 3, 4, 5)]
        self.campaigns: dict[int, NewCampaign] = {}
        self.streams: dict[int, dict] = {}
        self._next = 100

    def _id(self):
        self._next += 1
        return self._next

    async def list_offers(self):
        return self.offers

    async def get_offer(self, offer_id):
        raise TrackerError(404, "not found")

    async def get_campaign(self, cid):
        c = self.campaigns[cid]
        return TrackerCampaign(id=cid, name=c.name, alias=c.alias)

    async def create_campaign(self, campaign):
        cid = self._id()
        self.campaigns[cid] = campaign
        return TrackerCampaign(id=cid, name=campaign.name, alias=campaign.alias)

    async def delete_campaign(self, cid):
        self.campaigns.pop(cid)

    async def create_redirect_stream(self, campaign_id, *, name, position, url, countries):
        return self._add_stream(campaign_id, name, position, "redirect", url=url, countries=countries)

    async def create_offers_stream(self, campaign_id, *, name, position, offers):
        return self._add_stream(campaign_id, name, position, "landings", offers=list(offers))

    def _add_stream(self, campaign_id, name, position, schema, **extra):
        sid = self._id()
        self.streams[sid] = {"campaign_id": campaign_id, "name": name, "position": position,
                             "schema": schema, "offers": [], **extra}
        return sid

    async def update_stream_offers(self, sid, offers):
        self.streams[sid]["offers"] = list(offers)

    async def get_campaign_streams(self, cid):
        return [StreamSnapshot(keitaro_id=sid, name=s["name"], position=s["position"], schema=s["schema"],
                               offers=list(s["offers"]))
                for sid, s in self.streams.items() if s["campaign_id"] == cid]
