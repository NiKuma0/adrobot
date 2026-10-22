"""Tracker port over Keitaro Admin API (see openapi.yaml)."""

from typing import Any

import httpx

from app.application.ports import (
    NamedItem,
    NewCampaign,
    TrackerCampaign,
    TrackerError,
    TrackerOffer,
)
from app.domain.models import OfferShare, StreamSnapshot


class KeitaroTracker:
    def __init__(self, base_url: str, api_key: str, transport: httpx.AsyncBaseTransport | None = None):
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/admin_api/v1",
            headers={"Api-Key": api_key},
            timeout=30,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        try:
            resp = await self._http.request(method, path, **kwargs)
        except httpx.HTTPError as e:
            raise TrackerError(502, str(e)) from e
        if resp.status_code >= 400:
            try:
                detail = resp.json()
            except ValueError:
                detail = resp.text[:500]
            raise TrackerError(resp.status_code, detail)
        return resp.json() if resp.content else None

    # campaigns
    async def list_campaigns(self) -> list[TrackerCampaign]:
        return [_campaign(c) for c in await self._request("GET", "/campaigns")]

    async def get_campaign(self, campaign_id: int) -> TrackerCampaign:
        return _campaign(await self._request("GET", f"/campaigns/{campaign_id}"))

    async def create_campaign(self, campaign: NewCampaign) -> TrackerCampaign:
        payload = {
            "name": campaign.name,
            "alias": campaign.alias,
            "type": "position",
            "group_id": campaign.group_id,
            "traffic_source_id": campaign.traffic_source_id,
            "domain_id": campaign.domain_id,
        }
        data = {k: v for k, v in payload.items() if v is not None}
        return _campaign(await self._request("POST", "/campaigns", json=data))

    async def delete_campaign(self, campaign_id: int) -> None:
        await self._request("DELETE", f"/campaigns/{campaign_id}")

    # streams (flows)
    async def get_campaign_streams(self, campaign_id: int) -> list[StreamSnapshot]:
        return [_stream(s) for s in await self._request("GET", f"/campaigns/{campaign_id}/streams")]

    async def create_redirect_stream(
        self, campaign_id: int, *, name: str, position: int, url: str, countries: list[str]
    ) -> int:
        stream = await self._request("POST", "/streams", json={
            "campaign_id": campaign_id,
            "type": "regular",
            "name": name,
            "position": position,
            "schema": "redirect",
            "action_type": "http",
            "action_payload": url,
            "collect_clicks": True,
            "filters": [{"name": "country", "mode": "accept", "payload": countries}],
        })
        return stream["id"]

    async def create_offers_stream(
        self, campaign_id: int, *, name: str, position: int, offers: list[OfferShare]
    ) -> int:
        stream = await self._request("POST", "/streams", json={
            "campaign_id": campaign_id,
            "type": "regular",
            "name": name,
            "position": position,
            "schema": "landings",
            "action_type": "http",
            "collect_clicks": True,
            "offers": _offers_payload(offers),
        })
        return stream["id"]

    async def update_stream_offers(self, stream_id: int, offers: list[OfferShare]) -> None:
        await self._request("PUT", f"/streams/{stream_id}", json={"offers": _offers_payload(offers)})

    # dictionaries
    async def list_offers(self) -> list[TrackerOffer]:
        return [_offer(o) for o in await self._request("GET", "/offers")]

    async def get_offer(self, offer_id: int) -> TrackerOffer:
        return _offer(await self._request("GET", f"/offers/{offer_id}"))

    async def list_groups(self) -> list[NamedItem]:
        return _named(await self._request("GET", "/groups", params={"type": "campaigns"}))

    async def list_traffic_sources(self) -> list[NamedItem]:
        return _named(await self._request("GET", "/traffic_sources"))

    async def list_domains(self) -> list[NamedItem]:
        return _named(await self._request("GET", "/domains"))


def _campaign(c: dict) -> TrackerCampaign:
    return TrackerCampaign(id=c["id"], name=c["name"], alias=c.get("alias") or "", state=c.get("state"))


def _offer(o: dict) -> TrackerOffer:
    return TrackerOffer(id=o["id"], name=o.get("name", ""), state=o.get("state"))


def _named(items: list[dict]) -> list[NamedItem]:
    return [NamedItem(id=x["id"], name=x["name"]) for x in items]


def _stream(s: dict) -> StreamSnapshot:
    return StreamSnapshot(
        keitaro_id=s["id"],
        name=s.get("name") or f"Flow #{s['id']}",
        position=s.get("position") or 0,
        schema=s.get("schema") or "",
        offers=[OfferShare(offer_id=o["offer_id"], share=o.get("share") or 0) for o in s.get("offers") or []],
    )


def _offers_payload(offers: list[OfferShare]) -> list[dict]:
    return [{"offer_id": o.offer_id, "share": o.share, "state": "active"} for o in offers]
