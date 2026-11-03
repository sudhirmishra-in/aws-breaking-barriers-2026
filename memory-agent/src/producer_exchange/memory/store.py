"""Storage port shared by every memory layer.

All memory is stored as JSON documents addressed by (pk, sk) with optimistic concurrency. Repositories
depend only on `DocumentStore`, so adding a backend means implementing one class.
"""

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class RevisionConflict(Exception):
    """A document changed since it was read, or already exists on a create."""


@dataclass(frozen=True)
class Document:
    pk: str
    sk: str
    body: dict[str, Any]
    rev: int
    expires_at: int | None = None


@dataclass(frozen=True)
class Write:
    """Applied only if the stored revision equals `expected_rev`. 0 means the document must not exist."""

    pk: str
    sk: str
    body: dict[str, Any]
    expected_rev: int
    expires_at: int | None = None


class DocumentStore(Protocol):
    def get(self, pk: str, sk: str) -> Document | None: ...

    def write_all(self, writes: list[Write]) -> list[Document]:
        """Apply every write or none of them. Raises RevisionConflict if any revision check fails.

        Backends may limit one call to 100 writes.
        """
        ...

    def delete(self, pk: str, sk: str) -> None: ...

    def query(self, pk: str, sk_prefix: str = "") -> list[Document]:
        """Return live documents under `pk`, sorted by `sk`."""
        ...


class SqliteDocumentStore:
    """Single-file local backend for development and tests. Use ":memory:" for an ephemeral store."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS documents (
                pk TEXT NOT NULL, sk TEXT NOT NULL, body TEXT NOT NULL,
                rev INTEGER NOT NULL, expires_at INTEGER,
                PRIMARY KEY (pk, sk))"""
        )
        self._db.commit()

    def get(self, pk: str, sk: str) -> Document | None:
        with self._lock:
            row = self._db.execute(
                "SELECT pk, sk, body, rev, expires_at FROM documents WHERE pk = ? AND sk = ?", (pk, sk)
            ).fetchone()
        return self._live(row)

    def write_all(self, writes: list[Write]) -> list[Document]:
        with self._lock:
            try:
                for write in writes:
                    self._apply(write)
            except RevisionConflict:
                self._db.rollback()
                raise
            self._db.commit()
        return [Document(w.pk, w.sk, w.body, w.expected_rev + 1, w.expires_at) for w in writes]

    def _apply(self, write: Write) -> None:
        payload = json.dumps(write.body, ensure_ascii=False)
        new_rev = write.expected_rev + 1
        if write.expected_rev == 0:
            self._db.execute(
                "DELETE FROM documents WHERE pk = ? AND sk = ? AND expires_at IS NOT NULL AND expires_at <= ?",
                (write.pk, write.sk, int(time.time())),
            )
            changed = self._db.execute(
                "INSERT OR IGNORE INTO documents VALUES (?, ?, ?, ?, ?)",
                (write.pk, write.sk, payload, new_rev, write.expires_at),
            ).rowcount
        else:
            changed = self._db.execute(
                "UPDATE documents SET body = ?, rev = ?, expires_at = ? WHERE pk = ? AND sk = ? AND rev = ?",
                (payload, new_rev, write.expires_at, write.pk, write.sk, write.expected_rev),
            ).rowcount
        if not changed:
            raise RevisionConflict(f"{write.pk}/{write.sk} is not at revision {write.expected_rev}")

    def delete(self, pk: str, sk: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM documents WHERE pk = ? AND sk = ?", (pk, sk))
            self._db.commit()

    def query(self, pk: str, sk_prefix: str = "") -> list[Document]:
        with self._lock:
            rows = self._db.execute(
                "SELECT pk, sk, body, rev, expires_at FROM documents WHERE pk = ? AND substr(sk, 1, ?) = ? ORDER BY sk",
                (pk, len(sk_prefix), sk_prefix),
            ).fetchall()
        return [doc for doc in map(self._live, rows) if doc is not None]

    @staticmethod
    def _live(row: tuple | None) -> Document | None:
        if row is None:
            return None
        pk, sk, body, rev, expires_at = row
        if expires_at is not None and expires_at <= time.time():
            return None
        return Document(pk, sk, json.loads(body), rev, expires_at)
