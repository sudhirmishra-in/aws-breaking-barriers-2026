"""Every storage backend must pass the same contract. Repositories rely on nothing else."""

import time
import uuid

import pytest

from producer_exchange.config import Settings
from producer_exchange.memory.store import RevisionConflict, SqliteDocumentStore, Write


@pytest.fixture(scope="module")
def dynamodb_table():
    from producer_exchange.memory.dynamodb import create_table, delete_table

    region = Settings.from_env().aws_region
    name = f"px-contract-test-{uuid.uuid4().hex[:8]}"
    create_table(name, region)
    yield name, region
    delete_table(name, region)


@pytest.fixture(params=["sqlite", pytest.param("dynamodb", marks=pytest.mark.aws)])
def backend(request):
    if request.param == "sqlite":
        return SqliteDocumentStore()
    from producer_exchange.memory.dynamodb import DynamoDBDocumentStore

    name, region = request.getfixturevalue("dynamodb_table")
    return DynamoDBDocumentStore(name, region)


def _pk() -> str:
    return f"TEST#{uuid.uuid4().hex}"


def _put(backend, pk, sk, body, expected_rev=0, expires_at=None):
    return backend.write_all([Write(pk, sk, body, expected_rev, expires_at)])[0]


def test_create_then_read_round_trips_nested_unicode(backend):
    pk = _pk()
    body = {"texto": "línea de café", "n": 1.5, "items": [{"a": None}]}
    created = _put(backend, pk, "A", body)
    assert created.rev == 1
    assert backend.get(pk, "A").body == body


def test_create_fails_when_document_exists(backend):
    pk = _pk()
    _put(backend, pk, "A", {"v": 1})
    with pytest.raises(RevisionConflict):
        _put(backend, pk, "A", {"v": 2})
    assert backend.get(pk, "A").body == {"v": 1}


def test_update_requires_the_current_revision(backend):
    pk = _pk()
    _put(backend, pk, "A", {"v": 1})
    _put(backend, pk, "A", {"v": 2}, expected_rev=1)
    with pytest.raises(RevisionConflict):
        _put(backend, pk, "A", {"v": 3}, expected_rev=1)
    assert backend.get(pk, "A").rev == 2


def test_query_filters_by_prefix_and_sorts(backend):
    pk = _pk()
    for key in ("FACT#2", "EPISODE#1", "FACT#1"):
        _put(backend, pk, key, {"key": key})
    assert [doc.sk for doc in backend.query(pk, "FACT#")] == ["FACT#1", "FACT#2"]
    assert len(backend.query(pk)) == 3
    assert backend.query(_pk()) == []


def test_delete_is_idempotent(backend):
    pk = _pk()
    _put(backend, pk, "A", {})
    backend.delete(pk, "A")
    backend.delete(pk, "A")
    assert backend.get(pk, "A") is None


def test_expired_documents_are_invisible_and_can_be_recreated(backend):
    pk = _pk()
    _put(backend, pk, "A", {"v": 1}, expires_at=int(time.time()) - 1)
    assert backend.get(pk, "A") is None
    assert backend.query(pk) == []
    assert _put(backend, pk, "A", {"v": 2}).body == {"v": 2}


def test_write_all_applies_every_document_and_returns_new_revisions(backend):
    pk = _pk()
    _put(backend, pk, "STATE", {"v": 1})
    documents = backend.write_all(
        [Write(pk, "EVENT#1", {"e": 1}, 0), Write(pk, "EVENT#2", {"e": 2}, 0), Write(pk, "STATE", {"v": 2}, 1)]
    )
    assert [document.rev for document in documents] == [1, 1, 2]
    assert [document.sk for document in backend.query(pk)] == ["EVENT#1", "EVENT#2", "STATE"]


def test_write_all_is_all_or_nothing(backend):
    pk = _pk()
    _put(backend, pk, "STATE", {"v": 1})
    _put(backend, pk, "STATE", {"v": 2}, expected_rev=1)
    with pytest.raises(RevisionConflict):
        backend.write_all(
            [Write(pk, "EVENT#1", {"e": 1}, 0), Write(pk, "EVENT#2", {"e": 2}, 0), Write(pk, "STATE", {"stale": True}, 1)]
        )
    assert [document.sk for document in backend.query(pk)] == ["STATE"]
    assert backend.get(pk, "STATE").body == {"v": 2}
