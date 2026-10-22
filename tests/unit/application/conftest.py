"""Use cases are tested in isolation: every port is an autospec mock, so a call that
doesn't match the real signature fails the test."""

from unittest.mock import create_autospec

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.offers import OfferCatalog
from app.application.ports import CampaignRepository, Tracker


@pytest.fixture
def session():
    return create_autospec(AsyncSession, instance=True)


@pytest.fixture
def campaigns():
    repo = create_autospec(CampaignRepository, instance=True)
    # saving hands back the stored entity; here it's the same object
    repo.save.side_effect = lambda campaign: campaign
    repo.save_stream.side_effect = lambda stream: stream
    repo.get_by_keitaro_id.return_value = None
    repo.get_stream.return_value = None
    repo.get_stream_by_offer.return_value = None
    return repo


@pytest.fixture
def tracker():
    return create_autospec(Tracker, instance=True)


@pytest.fixture
def offers():
    catalog = create_autospec(OfferCatalog, instance=True)
    catalog.name_of.side_effect = lambda offer_id: f"Offer {offer_id}"
    return catalog
