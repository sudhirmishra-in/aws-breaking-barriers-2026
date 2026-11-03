"""Memory schemas.

L0 is one exchange: `WorkingMemory` is its current state and `ExchangeEvent` is its append-only log.
L1 is longitudinal: `ProfileFact` and `ExchangeEpisode` take effect only after human review.
"""

import re
import unicodedata
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, Field, model_validator


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def _quote_key(quote: str) -> str:
    """Compare quotes by their words, so trailing punctuation does not make a near-duplicate look new."""
    return " ".join(re.sub(r"[^\w\s]", " ", _normalized(quote)).split())


class MemoryRuleError(Exception):
    """A write broke a memory invariant. The message is safe to return to the model."""


class Phase(StrEnum):
    CLARIFY = "clarify"
    PLAYBACK = "playback"
    RETRIEVE = "retrieve"
    DRAFT = "draft"
    DRAFTED = "drafted"


class ChallengeTag(StrEnum):
    CLIMATE_AND_WEATHER = "climate and weather"
    WATER = "water"
    SOIL_AND_LAND = "soil and land"
    MARKET_AND_PRICE = "market and price"
    LABOR_AND_MIGRATION = "labor and migration"
    FINANCIAL_AND_ACCESS_TO_CAPITAL = "financial and access to capital"
    EDUCATION = "education"
    HEALTH = "health"
    INFRASTRUCTURE = "infrastructure"
    BIODIVERSITY_AND_CONSERVATION = "biodiversity and conservation"
    SOCIAL_AND_COMMUNITY = "social and community"


class ProfileField(StrEnum):
    ENTITY_TYPE = "entity_type"
    MEMBER_COUNT = "member_count"
    CURRENT_PRACTICE = "current_practice"
    STATED_LOCATION = "stated_location"
    ADDITIONAL_CROP = "additional_crop"


class FieldPolicy(NamedTuple):
    multi_valued: bool
    # A scope-locked field is only ever a note for the reviewer. It never changes which data tools can read.
    scope_locked: bool


FIELD_POLICIES: dict[ProfileField, FieldPolicy] = {
    ProfileField.ENTITY_TYPE: FieldPolicy(multi_valued=False, scope_locked=False),
    ProfileField.MEMBER_COUNT: FieldPolicy(multi_valued=False, scope_locked=False),
    ProfileField.CURRENT_PRACTICE: FieldPolicy(multi_valued=True, scope_locked=False),
    ProfileField.STATED_LOCATION: FieldPolicy(multi_valued=False, scope_locked=True),
    ProfileField.ADDITIONAL_CROP: FieldPolicy(multi_valued=True, scope_locked=True),
}


class ProposedFact(BaseModel):
    """A profile change the producer stated in this exchange."""

    field: ProfileField
    value: str = Field(min_length=1)
    quote: str = Field(min_length=1, description="The producer's exact words that support this fact.")
    valid_from: str | None = Field(default=None, description="When this became true, if the producer said so.")

    @model_validator(mode="after")
    def _value_fits_field(self) -> "ProposedFact":
        if self.field == ProfileField.MEMBER_COUNT and not self.value.isdigit():
            raise ValueError("member_count must contain digits only, for example 350")
        return self


class SessionNote(BaseModel):
    """Something useful the producer said that fits no slot."""

    text: str = Field(min_length=1, description="The detail, in the producer's language.")
    quote: str = Field(min_length=1, description="The producer's exact words that support this note.")


class UnderstandingUpdate(BaseModel):
    """A partial update. Omitted fields keep their stored value."""

    challenge: str | None = None
    onset: str | None = None
    severity: str | None = None
    actions_tried: list[str] | None = None
    tags: list[ChallengeTag] | None = None
    producer_quotes: list[str] | None = None
    notes: list[SessionNote] | None = None
    location_checked: bool | None = None
    entity_type_checked: bool | None = None
    profile_facts: list[ProposedFact] | None = None


class UpdateEffect(StrEnum):
    UNCHANGED = "unchanged"
    # Quotes or notes were added. The playback does not cover these, so the version and confirmation stand.
    RECORDED = "recorded"
    # Something the producer must confirm changed, so the version moves and the stage prompt is rebuilt.
    CHANGED = "changed"


class Understanding(BaseModel):
    challenge: str | None = None
    onset: str | None = None
    severity: str | None = None
    actions_tried: list[str] | None = None  # None: not asked yet. Empty: nothing tried.
    tags: list[ChallengeTag] = Field(default_factory=list)
    producer_quotes: list[str] = Field(default_factory=list)
    notes: list[SessionNote] = Field(default_factory=list)
    location_checked: bool = False
    entity_type_checked: bool = False
    profile_facts: list[ProposedFact] = Field(default_factory=list)
    version: int = 0

    def missing_slots(self) -> list[str]:
        checks = {
            "challenge": bool(self.challenge),
            "onset": bool(self.onset),
            "severity": bool(self.severity),
            "actions_tried": self.actions_tried is not None,
            "tags": bool(self.tags),
            "location_checked": self.location_checked,
            "entity_type_checked": self.entity_type_checked,
        }
        return [slot for slot, filled in checks.items() if not filled]


class EvidenceSource(StrEnum):
    PRODUCER_RECORD = "producer_record"
    REGIONAL = "regional"
    PEER_CASE = "peer_case"
    STANDARD = "standard"


class EvidenceItem(BaseModel):
    evidence_id: str
    source_type: EvidenceSource
    source_ref: str
    source_label: str
    fact: str
    details: dict[str, Any] = Field(default_factory=dict)


class DraftClaim(BaseModel):
    kind: Literal["insight", "peer_example"]
    text: str = Field(min_length=1, description="The claim, written in the producer's language.")
    evidence_ids: list[str] = Field(min_length=1, description="IDs of the non-standard evidence behind this claim.")
    standard_evidence_ids: list[str] = Field(
        default_factory=list, description="IDs of the standard clauses this claim relates to."
    )


class GuidanceDraft(BaseModel):
    intro: str = Field(description="One or two sentences opening the response, in the producer's language.")
    claims: list[DraftClaim] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(
        default_factory=list, description="What could not be supported by evidence, in the producer's language."
    )
    closing: str = Field(description="One sentence that leaves the decision with the producer, in their language.")


class TranscriptEntry(NamedTuple):
    role: Literal["user", "assistant"]
    text: str
    turn: int


class PiiFlag(BaseModel):
    """Entity types only. Values stay in the event log, unredacted, for the human reviewer."""

    turn: int
    entity_types: list[str] = Field(default_factory=list)
    scan_status: Literal["scanned", "unsupported_language", "failed"] = "scanned"


class EventType(StrEnum):
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    PII_FLAG = "pii_flag"
    TOOL_CALL = "tool_call"
    STAGE_RUN = "stage_run"
    MEMORY_COMMITTED = "memory_committed"


class ExchangeEvent(BaseModel):
    """One immutable entry in an exchange's audit log. Rejected tool calls are kept too."""

    seq: int
    turn: int
    type: EventType
    phase: Phase
    at: str = Field(default_factory=utc_now)
    data: dict[str, Any] = Field(default_factory=dict)


class WorkingMemory(BaseModel):
    """L0: what the agent currently knows about this exchange, plus how it got there.

    The fields are the current state, overwritten on each save. `events` only ever grows. The model sees a
    projection of the state and the recent messages, rebuilt for each stage. Nothing is durable until the
    repository saves the whole turn at once.
    """

    exchange_id: str
    producer_id: str
    language: str
    phase: Phase = Phase.CLARIFY
    turn: int = 0
    greeting: str = ""
    understanding: Understanding = Field(default_factory=Understanding)
    shown_version: int | None = None
    shown_turn: int | None = None
    confirmed_version: int | None = None
    evidence: dict[str, EvidenceItem] = Field(default_factory=dict)
    retrieved_sources: list[EvidenceSource] = Field(default_factory=list)
    draft: GuidanceDraft | None = None
    pii_flags: list[PiiFlag] = Field(default_factory=list)
    committed_at: str | None = None
    created_at: str = Field(default_factory=utc_now)
    expires_at: int | None = None  # A fixed deadline for the state and every event, set on first save.
    events: list[ExchangeEvent] = Field(default_factory=list)
    saved_events: int = 0
    rev: int = 0

    @property
    def is_confirmed(self) -> bool:
        return self.confirmed_version is not None and self.confirmed_version == self.understanding.version

    @property
    def awaiting_confirmation(self) -> bool:
        return self.shown_version == self.understanding.version and self.shown_turn is not None

    @property
    def transcript(self) -> list[TranscriptEntry]:
        roles = {EventType.USER_MESSAGE: "user", EventType.ASSISTANT_MESSAGE: "assistant"}
        return [
            TranscriptEntry(roles[event.type], event.data["text"], event.turn)
            for event in self.events
            if event.type in roles
        ]

    def state_document(self) -> dict[str, Any]:
        """The state as stored: everything except the log, which lives in its own documents."""
        return self.model_dump(mode="json", exclude={"events", "saved_events", "rev"})

    def snapshot(self) -> dict[str, Any]:
        """The state plus log counters, for debugging views. Holds conversation text, so treat it like the log."""
        return {
            **self.state_document(),
            "rev": self.rev,
            "event_count": len(self.events),
            "saved_events": self.saved_events,
            "transcript_count": len(self.transcript),
        }

    def record_event(self, event_type: EventType, *, phase: Phase | None = None, **data: Any) -> ExchangeEvent:
        event = ExchangeEvent(
            seq=len(self.events) + 1,
            turn=self.turn,
            type=event_type,
            phase=phase or self.phase,
            data=data,
        )
        self.events.append(event)
        return event

    def begin_turn(self, message: str) -> None:
        self.turn += 1
        self.record_event(EventType.USER_MESSAGE, text=message)

    def end_turn(self, reply: str) -> None:
        self.record_event(EventType.ASSISTANT_MESSAGE, text=reply)

    def flag_pii(self, flag: PiiFlag) -> None:
        self.pii_flags.append(flag)
        self.record_event(EventType.PII_FLAG, entity_types=flag.entity_types, scan_status=flag.scan_status)

    def update_understanding(self, update: UnderstandingUpdate) -> UpdateEffect:
        """Apply a partial update and report what kind of change it was."""
        current = self.understanding
        changes = update.model_dump(exclude_none=True, exclude={"producer_quotes", "notes", "profile_facts"})
        merged = current.model_copy(update=changes)
        merged.producer_quotes = self._merged_quotes(update.producer_quotes)
        merged.notes = self._merged_notes(update.notes)
        merged.profile_facts = self._merged_facts(update.profile_facts)
        supporting = {"version", "producer_quotes", "notes"}
        if merged.model_dump(exclude=supporting) != current.model_dump(exclude=supporting):
            merged.version = current.version + 1
            self.understanding = merged
            return UpdateEffect.CHANGED
        recorded = merged.producer_quotes != current.producer_quotes or merged.notes != current.notes
        self.understanding = merged
        return UpdateEffect.RECORDED if recorded else UpdateEffect.UNCHANGED

    def mark_playback_shown(self) -> None:
        self.shown_version = self.understanding.version
        self.shown_turn = self.turn

    def confirm_understanding(self) -> None:
        """Accept only a version the producer has seen and answered in a later turn."""
        if self.understanding.missing_slots():
            raise MemoryRuleError(f"understanding is incomplete: {self.understanding.missing_slots()}")
        if self.shown_version != self.understanding.version:
            raise MemoryRuleError("this version has not been played back; restate it to the producer first")
        if self.shown_turn is None or self.turn <= self.shown_turn:
            raise MemoryRuleError("the producer has not answered the playback yet; wait for their next message")
        self.confirmed_version = self.understanding.version

    def confirmed_facts(self) -> list[ProposedFact]:
        return list(self.understanding.profile_facts) if self.is_confirmed else []

    def register_evidence(
        self,
        source_type: EvidenceSource,
        source_ref: str,
        source_label: str,
        fact: str,
        details: dict[str, Any] | None = None,
    ) -> EvidenceItem:
        """Return the ledger entry for a source record, creating it once with a server-side ID."""
        for item in self.evidence.values():
            if item.source_type == source_type and item.source_ref == source_ref:
                return item
        evidence_id = f"E{len(self.evidence) + 1}"
        item = EvidenceItem(
            evidence_id=evidence_id,
            source_type=source_type,
            source_ref=source_ref,
            source_label=source_label,
            fact=fact,
            details=details or {},
        )
        self.evidence[evidence_id] = item
        return item

    def mark_retrieved(self, source: EvidenceSource) -> None:
        if source not in self.retrieved_sources:
            self.retrieved_sources.append(source)

    def store_draft(self, draft: GuidanceDraft) -> None:
        """Referential integrity only: every citation must point at this session's ledger.

        Whether a claim is actually supported belongs to the future verify stage.
        """
        problems: list[str] = []
        for index, claim in enumerate(draft.claims, start=1):
            for evidence_id in claim.evidence_ids:
                item = self.evidence.get(evidence_id)
                if item is None or item.source_type == EvidenceSource.STANDARD:
                    problems.append(f"claim {index}: {evidence_id} is not retrieved non-standard evidence")
            for evidence_id in claim.standard_evidence_ids:
                item = self.evidence.get(evidence_id)
                if item is None or item.source_type != EvidenceSource.STANDARD:
                    problems.append(f"claim {index}: {evidence_id} is not a retrieved standard clause")
        if problems:
            raise MemoryRuleError("; ".join(problems))
        self.draft = draft

    def _merged_quotes(self, quotes: list[str] | None) -> list[str]:
        merged = list(self.understanding.producer_quotes)
        for quote in quotes or []:
            self._require_verbatim(quote)
            key = _quote_key(quote)
            if any(key in _quote_key(existing) for existing in merged):
                continue
            merged = [existing for existing in merged if _quote_key(existing) not in key]
            merged.append(quote)
        return merged

    def _merged_notes(self, notes: list[SessionNote] | None) -> list[SessionNote]:
        merged = list(self.understanding.notes)
        for note in notes or []:
            self._require_verbatim(note.quote)
            if not any(_quote_key(existing.quote) == _quote_key(note.quote) for existing in merged):
                merged.append(note)
        return merged

    def _merged_facts(self, facts: list[ProposedFact] | None) -> list[ProposedFact]:
        merged = list(self.understanding.profile_facts)
        for fact in facts or []:
            self._require_verbatim(fact.quote)
            if not FIELD_POLICIES[fact.field].multi_valued:
                merged = [existing for existing in merged if existing.field != fact.field]
            if not any(existing.field == fact.field and existing.value == fact.value for existing in merged):
                merged.append(fact)
        return merged

    def _require_verbatim(self, quote: str) -> None:
        said = _normalized(" ".join(entry.text for entry in self.transcript if entry.role == "user"))
        if _normalized(quote) not in said:
            raise MemoryRuleError(f"quote is not the producer's exact words: {quote!r}")


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    CORRECTED = "corrected"
    REJECTED = "rejected"


REVIEWED_STATUSES = (ReviewStatus.APPROVED, ReviewStatus.CORRECTED)


class ProfileFact(BaseModel):
    """L1: one reviewable change to a producer's profile, with its provenance and time range.

    `valid_from` is when it became true, as the producer said it. `created_at` is when we learned it. A newer
    reviewed value sets `superseded_by` on this one instead of deleting it, so the history stays answerable.
    """

    fact_id: str
    producer_id: str
    field: ProfileField
    value: str
    corrected_value: str | None = None
    producer_quote: str
    valid_from: str | None = None
    exchange_id: str
    source: Literal["agent conversation"] = "agent conversation"
    status: ReviewStatus = ReviewStatus.PENDING
    created_at: str = Field(default_factory=utc_now)
    reviewer: str | None = None
    reviewed_at: str | None = None
    superseded_by: str | None = None
    superseded_at: str | None = None

    @property
    def effective_value(self) -> str:
        return self.corrected_value if self.corrected_value is not None else self.value


class ExchangeEpisode(BaseModel):
    """L1: the confirmed account of one past exchange. Becomes evidence only after review."""

    episode_id: str
    producer_id: str
    exchange_id: str
    source: Literal["agent conversation"] = "agent conversation"
    language: str
    challenge: str
    onset: str | None = None
    severity: str | None = None
    actions_tried: list[str] = Field(default_factory=list)
    tags: list[ChallengeTag] = Field(default_factory=list)
    producer_quotes: list[str] = Field(default_factory=list)
    notes: list[SessionNote] = Field(default_factory=list)
    guidance_given: list[str] = Field(default_factory=list)
    pii_entity_types: list[str] = Field(default_factory=list)
    status: ReviewStatus = ReviewStatus.PENDING
    created_at: str = Field(default_factory=utc_now)
    reviewer: str | None = None
    reviewed_at: str | None = None
    original_values: dict[str, Any] = Field(default_factory=dict)
