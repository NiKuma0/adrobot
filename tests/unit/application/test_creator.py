"""CampaignCreator over mocked ports: Keitaro calls, defaults and rollback."""

from unittest.mock import create_autospec, patch

import pytest

from app.application.creator import CampaignCreator, CampaignDefaults
from app.application.editor import CampaignEditor
from app.application.ports import NewCampaign, TrackerCampaign, TrackerError
from app.domain.errors import InvalidInputError
from app.domain.models import Campaign, OfferShare

pytestmark = pytest.mark.anyio

DEFAULTS = CampaignDefaults(group_id=1, traffic_source_id=2, domain_id=3, geo_redirect_url="https://example.com")


@pytest.fixture
def editor():
    editor = create_autospec(CampaignEditor, instance=True)
    editor.sync_campaign.side_effect = lambda campaign: campaign
    return editor


@pytest.fixture
def tracker(tracker):
    tracker.create_campaign.return_value = TrackerCampaign(id=42, name="Spring", alias="spring-abc123")
    return tracker


@pytest.fixture
def creator(tracker, editor):
    return CampaignCreator(tracker, editor, DEFAULTS)


@pytest.fixture(autouse=True)
def alias():
    with patch("app.application.creator.make_alias", return_value="spring-abc123") as make_alias:
        yield make_alias


async def test_create(creator, tracker, editor, alias):
    c = await creator.create(name="Spring", geo="au, mx", offer_id=9)

    alias.assert_called_once_with("Spring")
    tracker.create_campaign.assert_awaited_once_with(
        NewCampaign(name="Spring", alias="spring-abc123", group_id=1, traffic_source_id=2, domain_id=3)
    )
    tracker.create_redirect_stream.assert_awaited_once_with(
        42, name="Flow 1", position=1, url="https://example.com", countries=["AU", "MX"]
    )
    tracker.create_offers_stream.assert_awaited_once_with(
        42, name="Flow 2", position=2, offers=[OfferShare(offer_id=9, share=100)]
    )
    assert isinstance(c, Campaign)
    assert (c.id, c.keitaro_id, c.name, c.alias) == (None, 42, "Spring", "spring-abc123")
    editor.sync_campaign.assert_awaited_once_with(c)  # it saves the campaign
    tracker.delete_campaign.assert_not_awaited()


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        pytest.param({}, (1, 2, 3), id="defaults"),
        pytest.param({"group_id": 10, "traffic_source_id": 20, "domain_id": 30}, (10, 20, 30), id="explicit"),
        pytest.param({"domain_id": 30}, (1, 2, 30), id="mixed"),
        pytest.param({"group_id": None}, (1, 2, 3), id="none-means-default"),
    ],
)
async def test_create_picks_ids(creator, tracker, given, expected):
    await creator.create(name="Spring", geo="AU", offer_id=9, **given)
    sent: NewCampaign = tracker.create_campaign.await_args.args[0]
    assert (sent.group_id, sent.traffic_source_id, sent.domain_id) == expected


async def test_create_without_defaults(tracker, editor):
    creator = CampaignCreator(tracker, editor, CampaignDefaults())
    await creator.create(name="Spring", geo="AU", offer_id=9)
    assert tracker.create_campaign.await_args.args[0] == NewCampaign(name="Spring", alias="spring-abc123")
    assert tracker.create_redirect_stream.await_args.kwargs["url"] == "https://google.com"


async def test_invalid_geo_touches_nothing(creator, tracker, editor):
    with pytest.raises(InvalidInputError):
        await creator.create(name="Spring", geo="AUS", offer_id=9)
    assert tracker.mock_calls == []
    editor.sync_campaign.assert_not_awaited()


async def test_campaign_rejected_by_keitaro(creator, tracker, editor):
    tracker.create_campaign.side_effect = TrackerError(400, "bad name")
    with pytest.raises(TrackerError):
        await creator.create(name="Spring", geo="AU", offer_id=9)
    tracker.delete_campaign.assert_not_awaited()
    editor.sync_campaign.assert_not_awaited()


@pytest.mark.parametrize("failing", ["create_redirect_stream", "create_offers_stream"])
@pytest.mark.parametrize("delete_fails", [False, True], ids=["deleted", "delete-failed"])
async def test_half_created_campaign_is_deleted(creator, tracker, editor, failing, delete_fails):
    error = TrackerError(400, f"{failing} failed")
    getattr(tracker, failing).side_effect = error
    if delete_fails:
        tracker.delete_campaign.side_effect = TrackerError(500, "delete failed")

    with pytest.raises(TrackerError) as e:
        await creator.create(name="Spring", geo="AU", offer_id=9)

    assert e.value is error  # the original error, not the one from the cleanup
    tracker.delete_campaign.assert_awaited_once_with(42)
    editor.sync_campaign.assert_not_awaited()
