"""Read-only lookups in the tracker for the UI."""

import asyncio
from collections.abc import Awaitable, Callable

from app.application.creator import CampaignDefaults
from app.application.ports import NamedItem, Tracker, TrackerCampaign, TrackerError
from app.domain.models import ValueObject


class CampaignFormOptions(ValueObject):
    groups: list[NamedItem]
    traffic_sources: list[NamedItem]
    domains: list[NamedItem]
    defaults: CampaignDefaults


class TrackerDirectory:
    def __init__(self, tracker: Tracker, defaults: CampaignDefaults):
        self._tracker = tracker
        self._defaults = defaults

    async def campaigns(self) -> list[TrackerCampaign]:
        items = await self._tracker.list_campaigns()
        return sorted(items, key=lambda c: c.id, reverse=True)

    async def campaign_form_options(self) -> CampaignFormOptions:
        """Groups, traffic sources and domains for the "new campaign" form."""
        async def safe(fn: Callable[[], Awaitable[list[NamedItem]]]) -> list[NamedItem]:
            try:
                return await fn()
            except TrackerError:
                return []

        groups, sources, domains = await asyncio.gather(
            safe(self._tracker.list_groups),
            safe(self._tracker.list_traffic_sources),
            safe(self._tracker.list_domains),
        )
        return CampaignFormOptions(groups=groups, traffic_sources=sources, domains=domains, defaults=self._defaults)
