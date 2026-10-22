"""Keitaro adapter: what goes over the wire, on a mocked transport."""

import json

import httpx
import pytest

from app.adapters.keitaro import KeitaroTracker
from app.application.ports import (
    NamedItem,
    NewCampaign,
    TrackerCampaign,
    TrackerError,
    TrackerOffer,
)
from app.domain.models import OfferShare, StreamSnapshot

pytestmark = pytest.mark.anyio


def tracker(handler) -> KeitaroTracker:
    return KeitaroTracker("https://kt.test/", "key", transport=httpx.MockTransport(handler))


async def test_create_streams_payload():
    sent = []

    def handler(request: httpx.Request):
        assert request.headers["Api-Key"] == "key"
        sent.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"id": 7})

    kt = tracker(handler)
    await kt.create_redirect_stream(1, name="Flow 1", position=1, url="https://google.com", countries=["AU"])
    await kt.create_offers_stream(1, name="Flow 2", position=2, offers=[OfferShare(offer_id=3, share=100)])

    (path1, flow1), (_, flow2) = sent
    assert path1 == "/admin_api/v1/streams"
    assert flow1["action_payload"] == "https://google.com"
    assert flow1["filters"] == [{"name": "country", "mode": "accept", "payload": ["AU"]}]
    assert flow2["offers"] == [{"offer_id": 3, "share": 100, "state": "active"}]


async def test_streams_are_mapped_to_snapshots():
    kt = tracker(lambda _: httpx.Response(200, json=[
        {"id": 5, "name": None, "position": 2, "schema": "landings", "offers": [{"offer_id": 1, "share": 60}]},
    ]))
    [snap] = await kt.get_campaign_streams(1)
    assert (snap.keitaro_id, snap.name, snap.offers) == (5, "Flow #5", [OfferShare(offer_id=1, share=60)])


async def test_error_status_raises():
    kt = tracker(lambda _: httpx.Response(404, json={"error": "nope"}))
    with pytest.raises(TrackerError) as e:
        await kt.get_offer(1)
    assert (e.value.status, e.value.detail) == (404, {"error": "nope"})


@pytest.mark.parametrize(
    ("call", "method", "path", "params"),
    [
        (lambda kt: kt.list_campaigns(), "GET", "/campaigns", {}),
        (lambda kt: kt.get_campaign(5), "GET", "/campaigns/5", {}),
        (lambda kt: kt.delete_campaign(5), "DELETE", "/campaigns/5", {}),
        (lambda kt: kt.get_campaign_streams(5), "GET", "/campaigns/5/streams", {}),
        (lambda kt: kt.list_offers(), "GET", "/offers", {}),
        (lambda kt: kt.get_offer(9), "GET", "/offers/9", {}),
        (lambda kt: kt.list_groups(), "GET", "/groups", {"type": "campaigns"}),
        (lambda kt: kt.list_traffic_sources(), "GET", "/traffic_sources", {}),
        (lambda kt: kt.list_domains(), "GET", "/domains", {}),
    ],
    ids=lambda v: v if isinstance(v, str) else None,
)
async def test_endpoints(call, method, path, params):
    seen = []

    def handler(request: httpx.Request):
        seen.append((request.method, request.url.path, dict(request.url.params)))
        body = {"id": 5, "name": "x"} if path.rsplit("/", 1)[-1].isdigit() else []
        return httpx.Response(200, json=body)

    await call(tracker(handler))
    assert seen == [(method, "/admin_api/v1" + path, params)]


@pytest.mark.parametrize(
    ("given", "sent"),
    [
        pytest.param({}, {}, id="no-ids"),
        pytest.param({"group_id": 1, "traffic_source_id": 2, "domain_id": 3},
                     {"group_id": 1, "traffic_source_id": 2, "domain_id": 3}, id="all-ids"),
        pytest.param({"domain_id": 3}, {"domain_id": 3}, id="none-is-omitted"),
    ],
)
async def test_create_campaign_payload(given, sent):
    seen = []

    def handler(request: httpx.Request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"id": 42, "name": "c", "alias": "c-1", "state": "active"})

    created = await tracker(handler).create_campaign(NewCampaign(name="c", alias="c-1", **given))
    assert seen == [{"name": "c", "alias": "c-1", "type": "position", **sent}]
    assert created == TrackerCampaign(id=42, name="c", alias="c-1", state="active")


async def test_update_stream_offers_payload():
    seen = []

    def handler(request: httpx.Request):
        seen.append((request.method, request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"id": 7})

    await tracker(handler).update_stream_offers(
        7, [OfferShare(offer_id=1, share=60), OfferShare(offer_id=2, share=40)]
    )
    assert seen == [("PUT", "/admin_api/v1/streams/7", {"offers": [
        {"offer_id": 1, "share": 60, "state": "active"},
        {"offer_id": 2, "share": 40, "state": "active"},
    ]})]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param({"id": 1, "name": "c", "alias": "a", "state": "active"},
                     TrackerCampaign(id=1, name="c", alias="a", state="active"),
                     id="full"),
        pytest.param({"id": 1, "name": "c"}, TrackerCampaign(id=1, name="c", alias="", state=None), id="minimal"),
        pytest.param({"id": 1, "name": "c", "alias": None}, TrackerCampaign(id=1, name="c", alias="", state=None),
                     id="null-alias"),
    ],
)
async def test_campaign_mapping(raw, expected):
    assert await tracker(lambda _: httpx.Response(200, json=raw)).get_campaign(1) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param({"id": 3, "name": "Full", "position": 1, "schema": "redirect", "offers": []},
                     StreamSnapshot(keitaro_id=3, name="Full", position=1, schema="redirect", offers=[]), id="full"),
        pytest.param({"id": 3}, StreamSnapshot(keitaro_id=3, name="Flow #3", position=0, schema="", offers=[]),
                     id="minimal"),
        pytest.param({"id": 3, "name": "", "position": None, "schema": None, "offers": None},
                     StreamSnapshot(keitaro_id=3, name="Flow #3", position=0, schema="", offers=[]), id="nulls"),
        pytest.param({"id": 3, "offers": [{"offer_id": 1}, {"offer_id": 2, "share": None}, {"offer_id": 4, "share": 70}]},
                     StreamSnapshot(keitaro_id=3, name="Flow #3", position=0, schema="", offers=[
                         OfferShare(offer_id=1, share=0), OfferShare(offer_id=2, share=0), OfferShare(offer_id=4, share=70)
                     ]),
                     id="offer-shares"),
    ],
)
async def test_stream_mapping(raw, expected):
    assert await tracker(lambda _: httpx.Response(200, json=[raw])).get_campaign_streams(1) == [expected]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param({"id": 1, "name": "Offer", "state": "active"}, TrackerOffer(id=1, name="Offer", state="active"),
                     id="full"),
        pytest.param({"id": 1}, TrackerOffer(id=1, name="", state=None), id="minimal"),
    ],
)
async def test_offer_mapping(raw, expected):
    assert await tracker(lambda _: httpx.Response(200, json=raw)).get_offer(1) == expected


async def test_named_items_mapping():
    kt = tracker(lambda _: httpx.Response(200, json=[{"id": 1, "name": "a", "extra": True}, {"id": 2, "name": "b"}]))
    assert await kt.list_domains() == [NamedItem(id=1, name="a"), NamedItem(id=2, name="b")]


@pytest.mark.parametrize(
    ("response", "status", "detail"),
    [
        pytest.param(httpx.Response(400, json={"error": "bad"}), 400, {"error": "bad"}, id="json-body"),
        pytest.param(httpx.Response(500, text="Internal error"), 500, "Internal error", id="text-body"),
        pytest.param(httpx.Response(502, text="x" * 600), 502, "x" * 500, id="long-text-is-cut"),
        pytest.param(httpx.Response(401), 401, "", id="empty-body"),
    ],
)
async def test_error_responses(response, status, detail):
    with pytest.raises(TrackerError) as e:
        await tracker(lambda _: response).list_offers()
    assert (e.value.status, e.value.detail) == (status, detail)


@pytest.mark.parametrize("error", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow")])
async def test_network_errors_become_502(error):
    def handler(request):
        raise error

    with pytest.raises(TrackerError) as e:
        await tracker(handler).list_offers()
    assert e.value.status == 502
    assert isinstance(e.value.__cause__, httpx.HTTPError)


async def test_empty_success_body():
    assert await tracker(lambda _: httpx.Response(204)).delete_campaign(1) is None


async def test_base_url_and_close():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json=[])

    kt = KeitaroTracker("https://kt.test///", "key", transport=httpx.MockTransport(handler))
    await kt.list_offers()
    await kt.aclose()
    assert seen == ["https://kt.test/admin_api/v1/offers"]
    with pytest.raises(RuntimeError):
        await kt.list_offers()
