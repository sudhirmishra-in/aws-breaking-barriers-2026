"""L0 repository. One state document plus one document per event, under one partition per exchange.

A turn is saved as a single atomic write: the state and every new event, or nothing. Keeping events as
separate documents means the log can grow without hitting a per-item size limit, and the state stays small.
"""

import time

from producer_exchange.memory.models import ExchangeEvent, WorkingMemory
from producer_exchange.memory.store import DocumentStore, Write

_STATE_KEY = "STATE"
_EVENT_PREFIX = "EVENT#"


def _partition_key(exchange_id: str) -> str:
    return f"EXCHANGE#{exchange_id}"


def _event_key(seq: int) -> str:
    return f"{_EVENT_PREFIX}{seq:08d}"


class WorkingMemoryRepository:
    def __init__(self, store: DocumentStore, ttl_seconds: int) -> None:
        self._store = store
        self._ttl_seconds = ttl_seconds

    def load(self, exchange_id: str) -> WorkingMemory | None:
        documents = self._store.query(_partition_key(exchange_id))
        state = next((document for document in documents if document.sk == _STATE_KEY), None)
        if state is None:
            return None
        events = [ExchangeEvent.model_validate(d.body) for d in documents if d.sk.startswith(_EVENT_PREFIX)]
        return WorkingMemory.model_validate({**state.body, "events": events, "saved_events": len(events), "rev": state.rev})

    def save(self, memory: WorkingMemory) -> None:
        """Persist a whole turn atomically. Raises RevisionConflict if another turn got there first."""
        if memory.expires_at is None:
            memory.expires_at = int(time.time()) + self._ttl_seconds
        partition = _partition_key(memory.exchange_id)
        writes = [
            Write(partition, _event_key(event.seq), event.model_dump(mode="json"), 0, memory.expires_at)
            for event in memory.events[memory.saved_events :]
        ]
        writes.append(Write(partition, _STATE_KEY, memory.state_document(), memory.rev, memory.expires_at))
        documents = self._store.write_all(writes)
        memory.rev = documents[-1].rev
        memory.saved_events = len(memory.events)

    def delete(self, exchange_id: str) -> None:
        """Remove the state and the whole log."""
        partition = _partition_key(exchange_id)
        for document in self._store.query(partition):
            self._store.delete(partition, document.sk)
