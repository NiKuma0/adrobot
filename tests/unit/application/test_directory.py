"""TrackerDirectory: lookups for the UI, resilient to failing dictionaries."""

import pytest

from app.application.creator import CampaignDefaults
from app.application.directory import CampaignFormOptions, TrackerDirectory
from app.application.ports import NamedItem, TrackerCampaign, TrackerError

pytestmark = pytest.mark.anyio

DEFAULTS = CampaignDefaults(group_id=1)
LISTS = {
    "list_groups": [NamedItem(id=1, name="Group")],
    "list_traffic_sources": [NamedItem(id=2, name="Source")],
    "list_domains": [NamedItem(id=3, name="example.com")],
}


@pytest.fixture
def tracker(tracker):
    for method, items in LISTS.items():
        getattr(tracker, method).return_value = items
    return tracker


@pytest.fixture
def directory(tracker):
    return TrackerDirectory(tracker, DEFAULTS)


@pytest.mark.parametrize(
    ("ids", "expected"),
    [([], []), ([1], [1]), ([3, 10, 1, 7], [10, 7, 3, 1])],
)
async def test_campaigns_newest_first(directory, tracker, ids, expected):
    tracker.list_campaigns.return_value = [TrackerCampaign(id=i, name=f"c{i}") for i in ids]
    assert [c.id for c in await directory.campaigns()] == expected


async def test_form_options(directory):
    assert await directory.campaign_form_options() == CampaignFormOptions(
        groups=LISTS["list_groups"],
        traffic_sources=LISTS["list_traffic_sources"],
        domains=LISTS["list_domains"],
        defaults=DEFAULTS,
    )


@pytest.mark.parametrize("failing", [*LISTS, "all"])
async def test_form_options_survive_tracker_errors(directory, tracker, failing):
    for method in LISTS if failing == "all" else [failing]:
        getattr(tracker, method).side_effect = TrackerError(403, "forbidden")

    options = await directory.campaign_form_options()

    got = {"list_groups": options.groups, "list_traffic_sources": options.traffic_sources,
           "list_domains": options.domains}
    for method, items in got.items():
        assert items == ([] if failing in (method, "all") else LISTS[method])
    assert options.defaults is DEFAULTS


async def test_form_options_dont_hide_bugs(directory, tracker):
    tracker.list_domains.side_effect = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        await directory.campaign_form_options()
