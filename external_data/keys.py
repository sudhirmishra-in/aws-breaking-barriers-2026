"""Region keys for the environmental-facts table. Pure Python on purpose: the agent's hot path imports this and nothing geospatial.

Producer locations in the app look like "Huila, Colombia" or "Nawa (Soubré), Côte d'Ivoire" and organizations record a bare country. Both must resolve to the same
country partition, and spelling variants of one country must not create two partitions.
"""
from __future__ import annotations

import re

_ALIASES = {
    "cote d'ivoire": "côte d'ivoire", "côte d'ivoire": "côte d'ivoire", "ivory coast": "côte d'ivoire", "cote divoire": "côte d'ivoire",
    "bolivia (plurinational state of)": "bolivia", "usa": "united states", "united states of america": "united states",
}


def country_of(location) -> str | None:
    """Canonical lowercase country from a bare country ("Colombia"), a "Region, Country" string, or {"country": ...}. None when nothing usable."""
    if isinstance(location, dict):
        location = location.get("country")
    if not isinstance(location, str) or not location.strip():
        return None
    s = location.replace("’", "'").strip()
    if "," in s:
        s = s.rsplit(",", 1)[-1]                       # "Huila, Colombia" -> "Colombia"
    s = re.sub(r"\s+", " ", s).strip().lower()
    if not s or len(s) > 80:
        return None
    return _ALIASES.get(s, s)


def region_key(country: str, region_name: str | None = None) -> str:
    """Partition key for a region. The demo resolves every region to its COUNTRY partition (country-level data), so the key is always <country>#COUNTRY."""
    c = country_of(country)
    if not c:
        raise ValueError("no country")
    return f"{c}#COUNTRY"
