import asyncio
import time

from app.application.ports import Tracker, TrackerError, TrackerOffer


class OfferCatalog:
    """Tracker offers, cached for a while: autocomplete asks for them on every keystroke."""

    def __init__(self, tracker: Tracker, ttl: float = 60):
        self._tracker = tracker
        self._ttl = ttl
        self._cache: tuple[float, list[TrackerOffer]] | None = None
        self._lock = asyncio.Lock()

    async def all(self) -> list[TrackerOffer]:
        async with self._lock:
            if self._cache is None or time.monotonic() - self._cache[0] > self._ttl:
                self._cache = (time.monotonic(), await self._tracker.list_offers())
            return self._cache[1]

    async def search(self, q: str, limit: int = 20) -> list[TrackerOffer]:
        q = q.strip().lower()
        result = [o for o in await self.all() if not q or q in str(o.id) or q in o.name.lower()]
        return result[:limit]

    async def name_of(self, offer_id: int) -> str:
        for o in await self.all():
            if o.id == offer_id:
                return o.name
        # archived offers are not in the list but can still be bound to a flow
        try:
            return (await self._tracker.get_offer(offer_id)).name
        except TrackerError:
            return f"Offer #{offer_id}"
