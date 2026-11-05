"""Store interface: the minimal, backend-specific fetch operations.

Everything that matters for correctness (bounds, scope, shaping, citations,
logging) lives one level up in access.DataAccess, which is shared by every
backend and fully tested with the InMemoryStore.

Filters are a list of (attribute, op, value) with op in {"eq", "ne", "ge"}.
Vector filters use the S3 Vectors operator syntax ({"$and": [...], "$eq", "$ne", "$in"}).
"""
from __future__ import annotations

from typing import Protocol

Filter = tuple[str, str, object]


class Store(Protocol):
    def get_producer(self, account_sk: str) -> dict | None: ...

    def list_projects(self, account_sk: str, limit: int) -> list[dict]: ...

    def list_surveys(self, account_sk: str) -> list[dict]: ...

    def batch_get_projects(self, keys: list[tuple[str, str]]) -> list[dict]: ...

    def query_projects(self, index: str, pk: str, sk_prefix: str | None, filters: list[Filter],
                       limit: int) -> list[dict]:
        """index 'country' -> GSI peers_by_country_tag; index 'tag' -> GSI peers_by_tag. Peer-eligible items only."""

    def query_producers(self, country: str, sk_prefix: str | None, filters: list[Filter], limit: int) -> list[dict]: ...

    def vector_search(self, text: str, vfilter: dict, top_k: int) -> list[tuple[str, float, dict]]:
        """-> [(project_id, similarity 0..1, metadata)]"""


def passes(item: dict, filters: list[Filter]) -> bool:
    for attr, op, val in filters:
        v = item.get(attr)
        if op == "eq" and v != val:
            return False
        if op == "ne" and v == val:
            return False
        if op == "ge" and (v is None or v < val):
            return False
    return True


def vector_filter_match(meta: dict, f: dict | None) -> bool:
    if not f:
        return True
    if "$and" in f:
        return all(vector_filter_match(meta, x) for x in f["$and"])
    if "$or" in f:
        return any(vector_filter_match(meta, x) for x in f["$or"])
    for k, cond in f.items():
        v = meta.get(k)
        if not isinstance(cond, dict):
            cond = {"$eq": cond}
        for op, x in cond.items():
            if op == "$eq" and v != x:
                return False
            if op == "$ne" and v == x:
                return False
            if op == "$in" and v not in x:
                return False
            if op == "$nin" and v in x:
                return False
    return True
