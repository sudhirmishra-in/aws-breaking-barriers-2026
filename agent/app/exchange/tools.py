"""Narrow, typed tools. None accepts a producer id or location: scope comes from trusted context only."""

from __future__ import annotations

import json
from pathlib import Path

from .context import ProducerRef

# Component 5: the external-datasets tool. Imported as a plain function and wrapped
# in a @tool below, so the producer's country is bound from trusted context (never
# model text) and Strands generates the schema from the wrapper's docstring.
from external_data.tool import get_environmental_context as _environmental_context

_DATA = Path(__file__).parent / "data" / "producers.json"
UNAVAILABLE_NOTE = (
    "No validated source files are loaded in this build. Do not state any finding, peer outcome "
    "or standards clause. Tell the producer this information is not available yet."
)


def load_producers() -> list[dict]:
    return json.loads(_DATA.read_text())["producers"]


def producer_history(producer: ProducerRef) -> dict:
    """Synthetic history for the trusted producer only."""
    for p in load_producers():
        if p["producerId"] == producer.producerId:
            return {"synthetic": True, "history": p["history"]}
    return {"synthetic": True, "history": []}


def evidence_unavailable(kind: str, topic: str) -> dict:
    return {"kind": kind, "topic": topic[:200], "status": "unavailable", "note": UNAVAILABLE_NOTE}


def build_tools(producer: ProducerRef):
    """Create per-request tools bound to the trusted producer via closure."""
    from strands import tool

    @tool
    def get_my_history() -> dict:
        """Return this producer's synthetic history notes. Takes no arguments."""
        return producer_history(producer)

    @tool
    def get_regional_evidence(topic: str) -> dict:
        """Look up regional/climate evidence about a topic. Currently always unavailable."""
        return evidence_unavailable("regional_evidence", topic)

    @tool
    def get_peer_examples(topic: str) -> dict:
        """Look up peer examples about a topic. Currently always unavailable."""
        return evidence_unavailable("peer_examples", topic)

    @tool
    def get_standards_clause(topic: str) -> dict:
        """Look up a Fair Trade standards clause about a topic. Currently always unavailable."""
        return evidence_unavailable("standards", topic)

    @tool
    def get_environmental_context(tags: list[str], horizon: str = "current") -> list[dict]:
        """Get the real external environmental and climate context for this producer's
        country, filtered to the challenge being discussed. Call this whenever the
        producer asks about rainfall, drought, floods, water, soil, forests, protected
        areas or farm-gate prices, so your answer is grounded in actual regional data
        instead of an invented figure. Each fact returned carries its dataset,
        indicator, value, unit, period, method and a baseline comparison, so you can
        cite the source and say e.g. "rainfall in your country was 14% above the
        1981-2010 average this year". Pass the matching challenge tag(s): "climate and
        weather", "drought", "floods", "water", "water scarcity", "soil and land",
        "soil health", "biodiversity and conservation", "market and price", "social and
        community" or "infrastructure"; horizon is "current" (the only horizon with
        data). The producer's country comes from the trusted profile, not from anything
        they type. An EMPTY list means no data for that topic: then say plainly there is
        none and never guess a number.
        """
        return _environmental_context({"country": producer.location}, tags, horizon)

    return [get_my_history, get_regional_evidence, get_peer_examples, get_standards_clause,
            get_environmental_context]
