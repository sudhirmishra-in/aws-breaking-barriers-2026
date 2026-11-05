"""Component 4 tool function, named and shaped like main's `get_standards_clause(topic: str) -> dict`.

A PLAIN function, not a Strands tool.
The agent wraps it in a @tool inside build_tools(producer) and passes the trusted ProducerRef by
closure, so the model supplies only `topic`. The model-facing docstring lives on that wrapper.

Result keeps main's keys (kind / topic / status / note) and adds `standard` and, when status is "ok",
`clauses` with clause_id citations. See docs/COMPONENT_4_STANDARDS.md.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from .access import StandardsAccess
from .corpus import load_clauses
from .retriever import LexicalRetriever, S3VectorsRetriever

DEFAULT_CLAUSES = Path(__file__).resolve().parents[1] / "out" / "standards" / "standard_clauses.jsonl"
VECTOR_MIN_SCORE = 0.25


def get_standards_clause(producer, topic: str, *, sa: StandardsAccess | None = None, language: str = "en") -> dict:
    """main: get_standards_clause(topic) -> {"kind": "standards", "topic", "status", "note"}"""
    return (sa or default_standards_access()).get_standards_clause(producer, topic, language)


def local_standards_access(path: str | Path = DEFAULT_CLAUSES) -> StandardsAccess:
    """Offline BM25 backend (no AWS)."""
    clauses = load_clauses(path)
    return StandardsAccess(clauses, LexicalRetriever(clauses))


@lru_cache(maxsize=1)
def default_standards_access() -> StandardsAccess:
    """STANDARDS_CLAUSES (jsonl path) is always read for clause text and applicability.
    If STANDARDS_VECTOR_BUCKET is set, retrieval uses S3 Vectors (index STANDARDS_VECTOR_INDEX, default
    "standards"; NOT RUN in the build environment); otherwise the offline lexical retriever."""
    clauses = load_clauses(os.environ.get("STANDARDS_CLAUSES", DEFAULT_CLAUSES))
    bucket = os.environ.get("STANDARDS_VECTOR_BUCKET")
    if not bucket:
        return StandardsAccess(clauses, LexicalRetriever(clauses))
    r = S3VectorsRetriever(bucket, os.environ.get("STANDARDS_VECTOR_INDEX", "standards"),
                           region=os.environ.get("AWS_REGION"))
    return StandardsAccess(clauses, r, min_score=VECTOR_MIN_SCORE)
