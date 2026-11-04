"""Drop-in for main's `get_standards_clause(topic: str) -> dict` (agent/app/exchange/tools.py).

Same name, same single model-supplied argument, same per-request closure over the trusted ProducerRef,
same top-level keys (kind / topic / status / note). Wiring in agent/app/exchange/tools.py::build_tools:

    from c4.tools import make_standards_tool, standards_access_from_env
    _STANDARDS = standards_access_from_env()          # once per process
    ...
    get_standards_clause = make_standards_tool(_STANDARDS, producer, language)

`language` is optional (main's build_tools only receives the producer today); without it clause text is English.
The Strands wrapper is NOT RUN in the build environment; `impl_get_standards_clause` is what the tests call.
"""
from __future__ import annotations

import os
from pathlib import Path

from .access import StandardsAccess
from .corpus import load_clauses
from .retriever import LexicalRetriever, S3VectorsRetriever

DOC = """Look up Fair Trade USA standards clauses about a topic, for this producer's standard only (APS or FPS).
Returns clause IDs with the requirement text. Cite clause_id for anything you take from it.
If status is not "ok", do not state any standards clause.

Args:
    topic: what the producer is asking about, in their own words (any language).
"""
DEFAULT_CLAUSES = Path(__file__).resolve().parents[1] / "out" / "standards" / "standard_clauses.jsonl"
VECTOR_MIN_SCORE = 0.25


def impl_get_standards_clause(sa: StandardsAccess, producer, topic: str, language: str = "en") -> dict:
    return sa.get_standards_clause(producer, topic, language)


def make_standards_tool(sa: StandardsAccess, producer, language: str = "en"):
    """Per-request Strands tool bound to the trusted producer by closure (mirrors main's build_tools)."""
    from strands import tool

    def get_standards_clause(topic: str) -> dict:
        return impl_get_standards_clause(sa, producer, topic, language)

    get_standards_clause.__doc__ = DOC  # set BEFORE @tool so Strands builds the schema from it
    return tool(get_standards_clause)


def local_standards_access(path: str | Path = DEFAULT_CLAUSES) -> StandardsAccess:
    """Offline BM25 backend (no AWS)."""
    clauses = load_clauses(path)
    return StandardsAccess(clauses, LexicalRetriever(clauses))


def standards_access_from_env() -> StandardsAccess:
    """STANDARDS_CLAUSES (jsonl path) is always read for clause text and applicability.
    If STANDARDS_VECTOR_BUCKET is set, retrieval uses S3 Vectors (index STANDARDS_VECTOR_INDEX, default
    "standards"); otherwise the offline lexical retriever."""
    clauses = load_clauses(os.environ.get("STANDARDS_CLAUSES", DEFAULT_CLAUSES))
    bucket = os.environ.get("STANDARDS_VECTOR_BUCKET")
    if not bucket:
        return StandardsAccess(clauses, LexicalRetriever(clauses))
    r = S3VectorsRetriever(bucket, os.environ.get("STANDARDS_VECTOR_INDEX", "standards"),
                           region=os.environ.get("AWS_REGION"))
    return StandardsAccess(clauses, r, min_score=VECTOR_MIN_SCORE)
