"""The application boundary. A web API, AgentCore entrypoint or CLI calls only this class.

The service is stateless between calls: every turn loads working memory, runs, and saves. `producer_id`
must come from the caller's authenticated session, and is checked against the exchange on every call.
"""

import uuid

from pydantic import BaseModel, Field

from producer_exchange.agent.phases import next_phase
from producer_exchange.agent.rendering import GREETINGS, localized
from producer_exchange.agent.runner import StageRun, TurnRunner
from producer_exchange.agent.tools import TurnContext
from producer_exchange.memory.models import (
    EventType,
    ExchangeEvent,
    MemoryRuleError,
    Phase,
    ProfileFact,
    ProfileField,
    WorkingMemory,
    utc_now,
)
from producer_exchange.memory.profile import CommitResult, ProfileRepository, ProfileView
from producer_exchange.memory.working import WorkingMemoryRepository
from producer_exchange.safety.pii import PiiDetector
from producer_exchange.sources.base import DataSources


class ExchangeNotFound(Exception):
    """The exchange does not exist, has expired, or belongs to another producer."""


class ExchangeStarted(BaseModel):
    exchange_id: str
    greeting: str
    phase: Phase


class TurnResponse(BaseModel):
    exchange_id: str
    turn: int
    reply: str
    phase: Phase
    completed: bool
    stage_runs: list[StageRun] = Field(default_factory=list)


class ExchangeService:
    def __init__(
        self,
        working: WorkingMemoryRepository,
        profiles: ProfileRepository,
        sources: DataSources,
        runner: TurnRunner,
        pii: PiiDetector,
    ) -> None:
        self._working = working
        self._profiles = profiles
        self._sources = sources
        self._runner = runner
        self._pii = pii

    def start_exchange(self, producer_id: str, language: str | None = None) -> ExchangeStarted:
        view = self._profiles.load_view(producer_id)
        language = language or view.registered.language or "en"
        memory = WorkingMemory(
            exchange_id=uuid.uuid4().hex,
            producer_id=producer_id,
            language=language,
            greeting=localized(GREETINGS, language),
        )
        self._working.save(memory)
        return ExchangeStarted(exchange_id=memory.exchange_id, greeting=memory.greeting, phase=memory.phase)

    def handle_turn(self, exchange_id: str, producer_id: str, message: str) -> TurnResponse:
        memory = self._load(exchange_id, producer_id)
        memory.begin_turn(message)
        flag = self._pii.scan(message, memory.language, memory.turn)
        if flag is not None:
            memory.flag_pii(flag)
        context = TurnContext(
            memory=memory,
            view=self._profiles.load_view(producer_id, memory.confirmed_facts()),
            profiles=self._profiles,
            sources=self._sources,
        )
        outcome = self._runner.run(context)
        memory.end_turn(outcome.reply)
        if outcome.spoken_from == Phase.PLAYBACK:
            memory.mark_playback_shown()
        memory.phase = next_phase(memory)
        self._working.save(memory)
        return TurnResponse(
            exchange_id=exchange_id,
            turn=memory.turn,
            reply=outcome.reply,
            phase=memory.phase,
            completed=outcome.completed,
            stage_runs=outcome.stage_runs,
        )

    def get_working_memory(self, exchange_id: str, producer_id: str) -> WorkingMemory:
        return self._load(exchange_id, producer_id)

    def get_event_log(self, exchange_id: str, producer_id: str) -> list[ExchangeEvent]:
        """The exchange's audit trail: messages, tool calls with reasoning, and each run's exact prompt."""
        return self._load(exchange_id, producer_id).events

    def get_profile(self, producer_id: str) -> ProfileView:
        return self._profiles.load_view(producer_id)

    def get_fact_history(self, producer_id: str, field: ProfileField) -> list[ProfileFact]:
        return self._profiles.fact_history(producer_id, field)

    def commit_memory(self, exchange_id: str, producer_id: str, *, consent_granted: bool) -> CommitResult:
        """Copy a confirmed exchange into L1 as pending review.

        The consent stage is not built yet, so the caller states the decision explicitly. Durable writes
        have no other path, which is the single seam ASK_CONSENT will plug into.
        """
        if not consent_granted:
            raise MemoryRuleError("durable memory requires the producer's consent")
        memory = self._load(exchange_id, producer_id)
        result = self._profiles.commit_exchange(memory)
        memory.committed_at = utc_now()
        memory.record_event(EventType.MEMORY_COMMITTED, episode_id=result.episode_id, fact_ids=result.fact_ids)
        self._working.save(memory)
        return result

    def discard_exchange(self, exchange_id: str, producer_id: str) -> None:
        """Delete everything held for this exchange: its state and its whole event log."""
        self._load(exchange_id, producer_id)
        self._working.delete(exchange_id)

    def _load(self, exchange_id: str, producer_id: str) -> WorkingMemory:
        memory = self._working.load(exchange_id)
        if memory is None or memory.producer_id != producer_id:
            raise ExchangeNotFound(exchange_id)
        return memory
