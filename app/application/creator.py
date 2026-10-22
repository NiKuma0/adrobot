from contextlib import suppress

from app.application.editor import CampaignEditor
from app.application.ports import NewCampaign, Tracker, TrackerError
from app.domain.creation import make_alias, parse_geo
from app.domain.models import Campaign, OfferShare, ValueObject


class CampaignDefaults(ValueObject):
    group_id: int | None = None
    traffic_source_id: int | None = None
    domain_id: int | None = None
    # Where the first flow sends visitors from the selected countries
    geo_redirect_url: str = "https://google.com"


class CampaignCreator:
    def __init__(self, tracker: Tracker, editor: CampaignEditor, defaults: CampaignDefaults):
        self._tracker = tracker
        self._editor = editor
        self._defaults = defaults

    async def create(
        self,
        *,
        name: str,
        geo: str,
        offer_id: int,
        group_id: int | None = None,
        traffic_source_id: int | None = None,
        domain_id: int | None = None,
    ) -> Campaign:
        """Create a campaign with two flows:
        1. visitors from `geo` -> redirect to google.com
        2. everyone else -> the selected offer
        """
        countries = parse_geo(geo)
        tc = await self._tracker.create_campaign(NewCampaign(
            name=name,
            alias=make_alias(name),
            group_id=group_id or self._defaults.group_id,
            traffic_source_id=traffic_source_id or self._defaults.traffic_source_id,
            domain_id=domain_id or self._defaults.domain_id,
        ))

        try:
            await self._tracker.create_redirect_stream(
                tc.id, name="Flow 1", position=1, url=self._defaults.geo_redirect_url, countries=countries
            )
            await self._tracker.create_offers_stream(
                tc.id, name="Flow 2", position=2, offers=[OfferShare(offer_id=offer_id, share=100)]
            )
        except TrackerError:
            # don't leave a half-configured campaign in the tracker
            with suppress(TrackerError):
                await self._tracker.delete_campaign(tc.id)
            raise

        campaign = Campaign(keitaro_id=tc.id, name=tc.name, alias=tc.alias)
        return await self._editor.sync_campaign(campaign)
