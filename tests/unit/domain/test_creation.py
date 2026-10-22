"""New campaign rules: geo parsing and alias generation."""

import re
from unittest.mock import patch

import pytest

from app.domain.creation import make_alias, parse_geo
from app.domain.errors import InvalidInputError


@pytest.mark.parametrize(
    ("geo", "expected"),
    [
        ("AU", ["AU"]),
        ("au", ["AU"]),
        ("MX,AU,RO", ["MX", "AU", "RO"]),
        (" mx , au ", ["MX", "AU"]),
        ("MX AU\tRO", ["MX", "AU", "RO"]),
        ("MX,,AU,", ["MX", "AU"]),
        ("AU,au,MX,AU", ["AU", "MX"]),  # duplicates dropped, first occurrence wins
    ],
)
def test_parse_geo(geo, expected):
    assert parse_geo(geo) == expected


@pytest.mark.parametrize(
    ("geo", "reported"),
    [
        ("", "''"),
        ("   ", "'   '"),
        (",", "','"),
        ("AUS", "'AUS'"),
        ("A", "'A'"),
        ("A1", "'A1'"),
        ("AU;MX", "'AU;MX'"),
        ("ÄÖ", "'ÄÖ'"),
        ("AU,USA,mx,X", "'USA, X'"),  # only the bad ones are reported
    ],
)
def test_parse_geo_rejects_bad_codes(geo, reported):
    with pytest.raises(InvalidInputError, match=re.escape(f"Invalid country codes: {reported}")):
        parse_geo(geo)


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("My Campaign", "my-campaign"),
        ("  Hello,  World!  ", "hello-world"),
        ("AU / MX — test #2", "au-mx-test-2"),
        ("Привет", "campaign"),
        ("", "campaign"),
        ("a" * 50, "a" * 40),
        ("a" * 39 + " b", "a" * 39),  # cut right after a separator: no dangling dash
    ],
)
def test_make_alias(name, slug):
    with patch("app.domain.creation.secrets") as secrets:
        secrets.token_hex.return_value = "abc123"
        assert make_alias(name) == f"{slug}-abc123"
    secrets.token_hex.assert_called_once_with(3)


def test_make_alias_is_random():
    alias = make_alias("x")
    assert re.fullmatch(r"x-[0-9a-f]{6}", alias)
    assert alias != make_alias("x")
