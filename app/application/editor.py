"""Campaign editor: local copy of flows/offers with publish/cancel on top of the tracker."""

import asyncio
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.offers import OfferCatalog
from app.application.ports import CampaignRepository, Tracker
from app.domain.errors import NotFoundError
from app.domain.models import Campaign, Stream


class CampaignEditor:
    def __init__(self, session: AsyncSession, campaigns: CampaignRepository, tracker: Tracker, offers: OfferCatalog):
        self._session = session
        self._campaigns = campaigns
        self._tracker = tracker
        self._offers = offers

    async def get_campaign(self, keitaro_id: int) -> Campaign:
        campaign = await self._campaigns.get_by_keitaro_id(keitaro_id)
        if campaign is None:
            raise NotFoundError("Campaign is not imported yet, fetch streams first")
        return campaign

    async def import_campaign(self, keitaro_id: int) -> Campaign:
        campaign = await self._campaigns.get_by_keitaro_id(keitaro_id)
        if campaign is None:
            tc = await self._tracker.get_campaign(keitaro_id)
            campaign = Campaign(keitaro_id=tc.id, name=tc.name, alias=tc.alias)
        return await self.sync_campaign(campaign)

    async def sync_campaign(self, campaign: Campaign) -> Campaign:
        """Make the campaign match Keitaro and save it; returns the saved campaign."""
        snapshots = await self._tracker.get_campaign_streams(campaign.keitaro_id)
        new_ids = sorted(campaign.new_offer_ids(snapshots))
        names = await asyncio.gather(*(self._offers.name_of(i) for i in new_ids))
        campaign.sync(snapshots, dict(zip(new_ids, names)), synced_at=datetime.now())
        campaign = await self._campaigns.save(campaign)
        await self._session.commit()
        return campaign

    async def add_offer(self, stream_id: int, offer_id: int) -> Stream:
        stream = await self._stream(stream_id)
        name = await self._offers.name_of(offer_id) if stream.find_offer(offer_id) is None else ""
        stream.add_offer(offer_id, name)
        return await self._save(stream)

    async def remove_offer(self, stream_offer_id: int) -> Stream:
        stream = await self._stream_of_offer(stream_offer_id)
        stream.remove_offer(stream_offer_id)
        return await self._save(stream)

    async def bring_back_offer(self, stream_offer_id: int) -> Stream:
        stream = await self._stream_of_offer(stream_offer_id)
        stream.bring_back_offer(stream_offer_id)
        return await self._save(stream)

    async def pin_offer(self, stream_offer_id: int, pinned: bool) -> Stream:
        stream = await self._stream_of_offer(stream_offer_id)
        stream.pin_offer(stream_offer_id, pinned)
        return await self._save(stream)

    async def publish_stream(self, stream_id: int) -> Stream:
        stream = await self._stream(stream_id)
        await self._tracker.update_stream_offers(stream.keitaro_id, stream.offers_to_publish())
        stream.mark_published()
        return await self._save(stream)

    async def cancel_stream(self, stream_id: int) -> Stream:
        stream = await self._stream(stream_id)
        stream.cancel_changes()
        return await self._save(stream)

    async def _save(self, stream: Stream) -> Stream:
        stream = await self._campaigns.save_stream(stream)
        await self._session.commit()
        return stream

    async def _stream(self, stream_id: int) -> Stream:
        stream = await self._campaigns.get_stream(stream_id)
        if stream is None:
            raise NotFoundError("Stream not found")
        return stream

    async def _stream_of_offer(self, stream_offer_id: int) -> Stream:
        stream = await self._campaigns.get_stream_by_offer(stream_offer_id)
        if stream is None:
            raise NotFoundError("Offer is not bound to the stream")
        return stream
