"""Composition root: picks the adapters for the ports."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.adapters.keitaro import KeitaroTracker
from app.application.creator import CampaignDefaults
from app.application.offers import OfferCatalog
from app.config import CampaignSettings, DatabaseSettings, KeitaroSettings


@dataclass
class Container:
    tracker: KeitaroTracker
    offers: OfferCatalog
    defaults: CampaignDefaults
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]

    @classmethod
    def from_settings(cls, keitaro: KeitaroSettings, db: DatabaseSettings, campaign: CampaignSettings) -> "Container":
        tracker = KeitaroTracker(keitaro.url, keitaro.api_key)
        engine = create_async_engine(db.url, pool_pre_ping=True)
        return cls(
            tracker=tracker,
            offers=OfferCatalog(tracker),
            defaults=CampaignDefaults(
                group_id=campaign.group_id,
                traffic_source_id=campaign.traffic_source_id,
                domain_id=campaign.domain_id,
                geo_redirect_url=campaign.geo_redirect_url,
            ),
            engine=engine,
            session_factory=async_sessionmaker(engine, expire_on_commit=False),
        )

    async def aclose(self) -> None:
        await self.tracker.aclose()
        await self.engine.dispose()
