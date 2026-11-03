"""L1 repository: the producer profile as a read-time merge of three layers.

    registered record  <  reviewed facts  <  facts confirmed in this exchange

The registered record comes from the system of record and is never written here. A conversation only
appends reviewable facts and one episode. They stay invisible to other exchanges until a person approves
them, so one conversation cannot poison what later conversations treat as evidence. A newer reviewed value
supersedes an older one without deleting it.
"""

import hashlib
from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from producer_exchange.memory.models import (
    FIELD_POLICIES,
    REVIEWED_STATUSES,
    ExchangeEpisode,
    MemoryRuleError,
    ProfileFact,
    ProfileField,
    ProposedFact,
    ReviewStatus,
    WorkingMemory,
    utc_now,
)
from producer_exchange.memory.store import DocumentStore, RevisionConflict, Write
from producer_exchange.sources.base import ProducerDirectory, ProducerRecord

_FACT_PREFIX = "FACT#"
_EPISODE_PREFIX = "EPISODE#"


def _partition_key(producer_id: str) -> str:
    return f"PRODUCER#{producer_id}"


class Provenance(StrEnum):
    REGISTERED = "registered"
    REVIEWED = "reviewed"
    SESSION = "confirmed in this exchange"


class ProfileAttribute(BaseModel):
    field: ProfileField
    value: str
    provenance: Provenance
    valid_from: str | None = None


class ProfileView(BaseModel):
    """What the agent may believe about a producer right now."""

    registered: ProducerRecord
    attributes: list[ProfileAttribute] = Field(default_factory=list)
    reviewed_episodes: list[ExchangeEpisode] = Field(default_factory=list)
    pending_review_count: int = 0

    def current(self, field: ProfileField) -> str | None:
        values = self.values(field)
        return values[-1] if values else None

    def values(self, field: ProfileField) -> list[str]:
        return [attribute.value for attribute in self.attributes if attribute.field == field]


class CommitResult(BaseModel):
    episode_id: str
    fact_ids: list[str]


class ProfileRepository:
    def __init__(self, store: DocumentStore, producers: ProducerDirectory) -> None:
        self._store = store
        self._producers = producers

    def load_view(self, producer_id: str, session_facts: Iterable[ProposedFact] = ()) -> ProfileView:
        registered = self._producers.get(producer_id)
        if registered is None:
            raise KeyError(f"unknown producer: {producer_id}")
        facts = self.list_facts(producer_id)
        episodes = self.list_episodes(producer_id)
        attributes = _registered_attributes(registered)
        current = (fact for fact in facts if fact.status in REVIEWED_STATUSES and fact.superseded_by is None)
        for fact in sorted(current, key=lambda fact: fact.created_at):
            _apply(attributes, fact.field, fact.effective_value, Provenance.REVIEWED, fact.valid_from)
        for fact in session_facts:
            _apply(attributes, fact.field, fact.value, Provenance.SESSION, fact.valid_from)
        return ProfileView(
            registered=registered,
            attributes=attributes,
            reviewed_episodes=[episode for episode in episodes if episode.status in REVIEWED_STATUSES],
            pending_review_count=sum(fact.status == ReviewStatus.PENDING for fact in facts)
            + sum(episode.status == ReviewStatus.PENDING for episode in episodes),
        )

    def commit_exchange(self, memory: WorkingMemory) -> CommitResult:
        """Write one episode and its facts as pending review, atomically. Safe to retry: IDs are deterministic.

        Callers must establish permission first. Nothing in this module checks consent.
        """
        understanding = memory.understanding
        if not memory.is_confirmed or not understanding.challenge:
            raise MemoryRuleError("only a confirmed understanding can be committed")
        unchanged = self.load_view(memory.producer_id)
        facts = [
            ProfileFact(
                fact_id=_fact_id(memory.exchange_id, proposed),
                producer_id=memory.producer_id,
                field=proposed.field,
                value=proposed.value,
                producer_quote=proposed.quote,
                valid_from=proposed.valid_from,
                exchange_id=memory.exchange_id,
            )
            for proposed in understanding.profile_facts
            if proposed.value not in unchanged.values(proposed.field)
        ]
        episode = ExchangeEpisode(
            episode_id=memory.exchange_id,
            producer_id=memory.producer_id,
            exchange_id=memory.exchange_id,
            language=memory.language,
            challenge=understanding.challenge,
            onset=understanding.onset,
            severity=understanding.severity,
            actions_tried=understanding.actions_tried or [],
            tags=understanding.tags,
            producer_quotes=understanding.producer_quotes,
            notes=understanding.notes,
            guidance_given=[claim.text for claim in memory.draft.claims] if memory.draft else [],
            pii_entity_types=sorted({kind for flag in memory.pii_flags for kind in flag.entity_types}),
        )
        partition = _partition_key(memory.producer_id)
        writes = [Write(partition, f"{_FACT_PREFIX}{fact.fact_id}", fact.model_dump(mode="json"), 0) for fact in facts]
        writes.append(Write(partition, f"{_EPISODE_PREFIX}{episode.episode_id}", episode.model_dump(mode="json"), 0))
        try:
            self._store.write_all(writes)
        except RevisionConflict:
            pass  # Already committed by an earlier attempt, possibly already reviewed. Keep that version.
        return CommitResult(episode_id=episode.episode_id, fact_ids=[fact.fact_id for fact in facts])

    def list_facts(self, producer_id: str) -> list[ProfileFact]:
        documents = self._store.query(_partition_key(producer_id), _FACT_PREFIX)
        return [ProfileFact.model_validate(document.body) for document in documents]

    def list_episodes(self, producer_id: str) -> list[ExchangeEpisode]:
        documents = self._store.query(_partition_key(producer_id), _EPISODE_PREFIX)
        episodes = [ExchangeEpisode.model_validate(document.body) for document in documents]
        return sorted(episodes, key=lambda episode: episode.created_at)

    def fact_history(self, producer_id: str, field: ProfileField) -> list[ProfileFact]:
        """Every value recorded for a field, oldest first, including superseded and rejected ones."""
        facts = [fact for fact in self.list_facts(producer_id) if fact.field == field]
        return sorted(facts, key=lambda fact: fact.created_at)

    def review_fact(
        self,
        producer_id: str,
        fact_id: str,
        *,
        status: ReviewStatus,
        reviewer: str,
        corrected_value: str | None = None,
    ) -> ProfileFact:
        """Apply a reviewer's decision and keep the field's history consistent, atomically.

        The original value is kept beside any correction, and the newest reviewed value of a single-valued
        field supersedes the older ones, whatever order the reviewer handles them in.
        """
        if status == ReviewStatus.CORRECTED and corrected_value is None:
            raise MemoryRuleError("a corrected fact needs a corrected_value")
        partition = _partition_key(producer_id)
        documents = {document.body["fact_id"]: document for document in self._store.query(partition, _FACT_PREFIX)}
        if fact_id not in documents:
            raise KeyError(f"not found: {producer_id}/{fact_id}")
        facts = {key: ProfileFact.model_validate(document.body) for key, document in documents.items()}
        fact = facts[fact_id]
        fact.status = status
        fact.corrected_value = corrected_value
        fact.reviewer = reviewer
        fact.reviewed_at = utc_now()
        changed = {fact_id} | _resolve_supersession(facts, fact.field)
        self._store.write_all(
            [
                Write(partition, documents[key].sk, facts[key].model_dump(mode="json"), documents[key].rev)
                for key in sorted(changed)
            ]
        )
        return fact

    def review_episode(
        self,
        producer_id: str,
        episode_id: str,
        *,
        status: ReviewStatus,
        reviewer: str,
        corrections: dict[str, Any] | None = None,
    ) -> ExchangeEpisode:
        """Apply a reviewer's decision, keeping the original of every corrected field."""
        partition = _partition_key(producer_id)
        document = self._store.get(partition, f"{_EPISODE_PREFIX}{episode_id}")
        if document is None:
            raise KeyError(f"not found: {producer_id}/{episode_id}")
        episode = ExchangeEpisode.model_validate(document.body)
        corrections = corrections or {}
        original_values = {key: document.body[key] for key in corrections}
        reviewed = ExchangeEpisode.model_validate(
            {
                **document.body,
                **corrections,
                "status": status,
                "reviewer": reviewer,
                "reviewed_at": utc_now(),
                "original_values": {**episode.original_values, **original_values},
            }
        )
        self._store.write_all([Write(partition, document.sk, reviewed.model_dump(mode="json"), document.rev)])
        return reviewed


def _resolve_supersession(facts: dict[str, ProfileFact], field: ProfileField) -> set[str]:
    """Point every older reviewed value of a single-valued field at the newest one. Returns the changed IDs."""
    if FIELD_POLICIES[field].multi_valued:
        return set()
    same_field = [fact for fact in facts.values() if fact.field == field]
    reviewed = [fact for fact in same_field if fact.status in REVIEWED_STATUSES]
    newest = max(reviewed, key=lambda fact: fact.created_at, default=None)
    changed = set()
    for fact in same_field:
        target = newest.fact_id if newest and fact in reviewed and fact is not newest else None
        if fact.superseded_by != target:
            fact.superseded_by = target
            fact.superseded_at = utc_now() if target else None
            changed.add(fact.fact_id)
    return changed


def _registered_attributes(record: ProducerRecord) -> list[ProfileAttribute]:
    attributes = []
    if record.entity_type:
        attributes.append(
            ProfileAttribute(field=ProfileField.ENTITY_TYPE, value=record.entity_type, provenance=Provenance.REGISTERED)
        )
    if record.member_count is not None:
        attributes.append(
            ProfileAttribute(
                field=ProfileField.MEMBER_COUNT, value=str(record.member_count), provenance=Provenance.REGISTERED
            )
        )
    return attributes


def _apply(
    attributes: list[ProfileAttribute],
    field: ProfileField,
    value: str,
    provenance: Provenance,
    valid_from: str | None,
) -> None:
    policy = FIELD_POLICIES[field]
    if policy.scope_locked:
        return
    if not policy.multi_valued:
        attributes[:] = [attribute for attribute in attributes if attribute.field != field]
    if not any(attribute.field == field and attribute.value == value for attribute in attributes):
        attributes.append(ProfileAttribute(field=field, value=value, provenance=provenance, valid_from=valid_from))


def _fact_id(exchange_id: str, fact: ProposedFact) -> str:
    key = f"{exchange_id}|{fact.field}|{fact.value}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]
