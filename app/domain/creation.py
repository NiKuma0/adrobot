"""Rules for setting up a new campaign."""

import re
import secrets

from app.domain.errors import InvalidInputError


def parse_geo(geo: str) -> list[str]:
    codes = [c.strip().upper() for c in re.split(r"[,\s]+", geo) if c.strip()]
    bad = [c for c in codes if not re.fullmatch(r"[A-Z]{2}", c)]
    if not codes or bad:
        raise InvalidInputError(f"Invalid country codes: {', '.join(bad) or geo!r}")
    return list(dict.fromkeys(codes))


def make_alias(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower())[:40].strip("-") or "campaign"
    return f"{slug}-{secrets.token_hex(3)}"
