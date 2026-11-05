"""Region gazetteer — the keystone that bridges name-only producer data to
gridded external datasets.

The producer data carries country + region name but **no coordinates** (CON-1).
External datasets are geographic (rasters, polygons). This gazetteer is the only
place that knows region geometry. For the demo it resolves at **country level**
(OPEN-7): every region maps to its country boundary, never a precise point, so
the agent states "in your country" rather than "in your region" (GZ-4).

Built once from Natural Earth admin-0 (open) and cached in the repo
(``external_data/data/countries.geojson``) — see ``scripts/build_gazetteer.py``.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

_GAZ_PATH = Path(__file__).resolve().parent / "data" / "countries.geojson"


@lru_cache(maxsize=1)
def _load() -> dict[str, BaseGeometry]:
    """Load the cached country gazetteer once, keyed by lowercased country name."""
    with open(_GAZ_PATH, "r", encoding="utf-8") as fh:
        fc = json.load(fh)
    return {
        feat["properties"]["name"].strip().lower(): shape(feat["geometry"])
        for feat in fc["features"]
    }


def list_countries() -> list[str]:
    """The countries the gazetteer knows (the pilot set)."""
    return sorted(_load().keys())


def has_country(country: str) -> bool:
    from external_data.keys import country_of
    c = country_of(country)
    return bool(c) and c in _load()


def get_geometry(country: str) -> BaseGeometry | None:
    """Return the country boundary (a shapely geometry) or None if unknown.

    MultiPolygon for countries with islands (e.g. Mexico); the full geometry is
    kept so raster masking covers every part of the country.
    """
    from external_data.keys import country_of
    c = country_of(country)
    return _load().get(c) if c else None


from external_data.keys import region_key  # noqa: E402,F401  (kept here for existing callers; pure, no shapely needed)
