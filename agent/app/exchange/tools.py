"""Narrow, typed tools. None accepts a producer id or location: scope comes from trusted context only."""

from __future__ import annotations

import json
from pathlib import Path

from .context import ProducerRef

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

    return [get_my_history, get_regional_evidence, get_peer_examples, get_standards_clause]
