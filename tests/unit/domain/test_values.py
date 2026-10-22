"""Value objects: immutable Pydantic models that compare by value and validate their input."""

import pytest
from pydantic import ValidationError

from app.application.creator import CampaignDefaults
from app.application.ports import NamedItem, NewCampaign, TrackerCampaign, TrackerOffer
from app.domain.models import OfferShare, StreamSnapshot

SAMPLES = [
    OfferShare(offer_id=1, share=100),
    StreamSnapshot(keitaro_id=1, name="Flow", position=1, schema="landings", offers=[]),
    TrackerCampaign(id=1, name="c"),
    TrackerOffer(id=1, name="o"),
    NamedItem(id=1, name="n"),
    NewCampaign(name="c", alias="c-1"),
    CampaignDefaults(),
]


@pytest.mark.parametrize("value", SAMPLES, ids=lambda v: type(v).__name__)
def test_immutable(value):
    field = next(iter(type(value).model_fields))
    with pytest.raises(ValidationError, match="frozen"):
        setattr(value, field, getattr(value, field))


@pytest.mark.parametrize("value", SAMPLES, ids=lambda v: type(v).__name__)
def test_compares_by_value(value):
    copy = type(value).model_validate(value.model_dump(by_alias=True))
    assert copy is not value
    assert copy == value


@pytest.mark.parametrize(
    ("a", "b", "equal"),
    [
        (OfferShare(offer_id=1, share=50), OfferShare(offer_id=1, share=50), True),
        (OfferShare(offer_id=1, share=50), OfferShare(offer_id=1, share=51), False),
        (NamedItem(id=1, name="x"), TrackerOffer(id=1, name="x"), False),  # same fields, different type
    ],
)
def test_equality(a, b, equal):
    assert (a == b) is equal


def test_hashable():
    assert {OfferShare(offer_id=1, share=50), OfferShare(offer_id=1, share=50)} == {OfferShare(offer_id=1, share=50)}


def test_keyword_only():
    with pytest.raises(TypeError):
        OfferShare(1, 100)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"offer_id": 1, "share": 100}, OfferShare(offer_id=1, share=100)),
        ({"offer_id": "1", "share": "100"}, OfferShare(offer_id=1, share=100)),  # numeric strings are coerced
    ],
)
def test_valid_input(data, expected):
    assert OfferShare(**data) == expected


@pytest.mark.parametrize(
    "data",
    [
        {"offer_id": 1},
        {"offer_id": "one", "share": 100},
        {"offer_id": 1, "share": 1.5},
        {"offer_id": None, "share": 100},
    ],
)
def test_invalid_input(data):
    with pytest.raises(ValidationError):
        OfferShare(**data)


def test_snapshot_schema_alias():
    snap = StreamSnapshot(keitaro_id=1, name="Flow", position=1, schema="redirect",
                          offers=[{"offer_id": 2, "share": 100}])
    assert snap.schema_ == "redirect"
    assert snap.offers == [OfferShare(offer_id=2, share=100)]
    assert snap.model_dump(by_alias=True)["schema"] == "redirect"
