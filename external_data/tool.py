"""The Component 5 Strands tool: ``get_environmental_context``.

A plain Python function — Strands auto-generates its JSON schema from the
signature + docstring (no hand-written schema), runs the call loop, and hands
the returned facts back to the model. The model never queries a store directly;
it calls this tool. The tool is a single bounded DynamoDB partition query plus
an in-code theme/horizon filter (NFR-1) — no network, no geospatial compute.
"""
from __future__ import annotations

import logging

from external_data import access, gazetteer as gaz

logger = logging.getLogger("external_data.tool")

# Challenge-tag -> dataset-theme map (Component 5 §4). Data-driven in principle
# (it belongs in the catalog); inlined here for the demo. Only the ``climate``
# theme has a cached dataset in the demo (Open-Meteo rainfall); the other themes
# are reserved for the datasets that will be added later.
TAG_TO_THEME: dict[str, set[str]] = {
    "climate and weather": {"climate"},
    "drought": {"climate"},
    "floods": {"climate", "water"},
    "water": {"water"},
    "water scarcity": {"water"},
    "soil and land": {"soil_land"},
    "soil health": {"soil_land"},
    "biodiversity and conservation": {"biodiversity", "soil_land"},
    "market and price": {"market"},
    "social and community": {"tenure"},
    "infrastructure": {"elevation"},
}


def get_environmental_context(
    location: dict,
    tags: list[str],
    horizon: str = "current",
) -> list[dict]:
    """Get the real external environmental/climate context for a producer's
    region, filtered to the challenge being addressed.

    Call this to ground a claim in actual regional data — rainfall, water
    stress, soil, forest, protected areas, prices — instead of inventing a
    figure. Every returned fact carries its dataset, period, method, and a
    baseline comparison, so you can cite the source and say "X% below the
    1981-2010 average".

    Args:
        location: {"country": str, "region": str (optional)} — the session's
            country and region, supplied by the UI, never free model text. The
            demo resolves to the country level, so state "in your country".
        tags: the challenge tag(s) from the conversation, e.g.
            ["climate and weather"]. Only data matching these tags is returned.
        horizon: "current" | "2030" | "2050" | "trend". The demo stores only
            "current"; projections are reserved.

    Returns:
        A list of facts, each: {dataset, theme, indicator, value, unit, period,
        method, baseline_value, baseline_delta_pct, baseline_period,
        is_projection, is_stand_in, horizon, geographic_scope}. An EMPTY LIST
        (not an error) when nothing matches — then say "no external data for
        that" rather than inventing a number.
    """
    country = location.get("country") if isinstance(location, dict) else location
    if not country:
        logger.info("get_environmental_context: no country in location=%r -> []", location)
        return []
    themes: set[str] = set()
    for tag in tags or []:
        themes |= TAG_TO_THEME.get(tag.strip().lower(), set())
    if not themes:
        logger.info("get_environmental_context %s tags=%s: no matching theme -> []",
                    country, tags)
        return []
    facts = access.get_facts(gaz.region_key(country), themes=themes, horizon=horizon)
    # NFR-4 observability: log the request and the returned facts' attribution
    # flags, so a reviewer can trace exactly what the agent was grounded on.
    summary = [(f["dataset"], f["indicator"],
                "proj" if f["is_projection"] else "-",
                "stand-in" if f["is_stand_in"] else "-") for f in facts]
    logger.info("get_environmental_context country=%s tags=%s horizon=%s themes=%s "
                "-> %d fact(s) %s", country, tags, horizon, sorted(themes), len(facts), summary)
    return facts
