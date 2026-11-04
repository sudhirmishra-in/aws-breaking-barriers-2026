"""Runs one producer turn as a series of short model runs, one per stage.

Each run gets a prompt built fresh from memory, and that prompt and tool set stay frozen for the run.
When a tool changes memory, the run ends and the next one starts from the updated memory. This is how a
single producer message can move through PLAYBACK, RETRIEVE and DRAFT with each stage seeing only its own
tools and context.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from strands import Agent
from strands.agent.conversation_manager import NullConversationManager
from strands.models import Model
from strands.tools.executors import SequentialToolExecutor

from producer_exchange.agent.context import build_messages, build_system_prompt
from producer_exchange.agent.phases import PHASE_SPECS
from producer_exchange.agent.rendering import FALLBACK_REPLIES, localized, render_guidance
from producer_exchange.agent.tools import ALL_TOOLS, TURN_CONTEXT_KEY, TurnContext
from producer_exchange.memory.models import EventType, Phase, WorkingMemory

logger = logging.getLogger(__name__)

_NUDGE = "Your previous attempt at this stage did not finish it. Complete the stage now as instructed."
_MAX_NUDGES_PER_STAGE = 1
_MAX_LOGGED_RESULT_CHARS = 500


@dataclass(frozen=True)
class StageRun:
    phase: Phase
    tools_called: tuple[str, ...]
    input_tokens: int
    output_tokens: int
    seconds: float
    stop_reason: str


@dataclass(frozen=True)
class StageTrace:
    """Exactly what one model run received and changed, for debugging views and demos.

    A trace holds the conversation text, so treat it like the transcript: never log it in production
    until retention is decided, because a decline must leave no narrative behind.
    """

    stage_run: StageRun
    system_prompt: str
    tool_names: tuple[str, ...]
    request_messages: list[dict[str, Any]]
    run_messages: list[dict[str, Any]]
    memory_before: dict[str, Any]
    memory_after: dict[str, Any]


StageObserver = Callable[[StageTrace], None]


@dataclass
class TurnOutcome:
    reply: str
    spoken_from: Phase | None
    stage_runs: list[StageRun] = field(default_factory=list)
    completed: bool = True


class TurnRunner:
    def __init__(
        self,
        model: Model,
        *,
        transcript_window: int,
        max_stage_runs: int,
        max_model_calls_per_run: int,
        observer: StageObserver | None = None,
    ) -> None:
        self._model = model
        self._observer = observer
        self._transcript_window = transcript_window
        self._max_stage_runs = max_stage_runs
        self._max_model_calls_per_run = max_model_calls_per_run

    def run(self, context: TurnContext) -> TurnOutcome:
        memory = context.memory
        started_in = memory.phase
        stage_runs: list[StageRun] = []
        nudges = 0
        while len(stage_runs) < self._max_stage_runs:
            # A stage entered during this turn may produce its reply in code, without another model call.
            if memory.phase == Phase.DRAFTED and started_in != Phase.DRAFTED:
                return TurnOutcome(render_guidance(memory), Phase.DRAFTED, stage_runs)

            spec = PHASE_SPECS[memory.phase]
            text, stage_run = self._run_stage(context, nudge=_NUDGE if nudges else None)
            stage_runs.append(stage_run)

            if context.context_is_stale:
                nudges = 0
                continue
            if spec.speaks and text:
                return TurnOutcome(text, spec.phase, stage_runs)
            if nudges >= _MAX_NUDGES_PER_STAGE:
                break
            nudges += 1

        logger.warning("turn did not complete", extra={"exchange_id": memory.exchange_id, "phase": memory.phase.value})
        return TurnOutcome(localized(FALLBACK_REPLIES, memory.language), None, stage_runs, completed=False)

    def _run_stage(self, context: TurnContext, *, nudge: str | None) -> tuple[str, StageRun]:
        memory = context.memory
        spec = PHASE_SPECS[memory.phase]
        context.context_is_stale = False
        request_messages = build_messages(memory, self._transcript_window)
        system_prompt = build_system_prompt(spec, memory, context.view, nudge=nudge)
        memory_before = memory.snapshot() if self._observer else {}
        agent = Agent(
            model=self._model,
            messages=list(request_messages),
            system_prompt=system_prompt,
            tools=[ALL_TOOLS[name] for name in spec.tools],
            callback_handler=None,
            conversation_manager=NullConversationManager(),
            tool_executor=SequentialToolExecutor(),
        )
        started = perf_counter()
        result = agent(
            invocation_state={TURN_CONTEXT_KEY: context},
            limits={"turns": self._max_model_calls_per_run},
        )
        usage = result.metrics.accumulated_usage
        text = "\n".join(block["text"] for block in result.message.get("content", []) if "text" in block).strip()
        tool_calls = _tool_calls(agent.messages[len(request_messages) :])
        stage_run = StageRun(
            phase=spec.phase,
            tools_called=tuple(call["tool"] for call in tool_calls),
            input_tokens=usage.get("inputTokens", 0),
            output_tokens=usage.get("outputTokens", 0),
            seconds=round(perf_counter() - started, 1),
            stop_reason=str(result.stop_reason),
        )
        _log_run(memory, stage_run, spec.tools, system_prompt, len(request_messages), tool_calls)
        if self._observer:
            self._observer(
                StageTrace(
                    stage_run=stage_run,
                    system_prompt=system_prompt,
                    tool_names=spec.tools,
                    request_messages=request_messages,
                    run_messages=list(agent.messages),
                    memory_before=memory_before,
                    memory_after=memory.snapshot(),
                )
            )
        return text, stage_run


def _tool_calls(new_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Read what the model called and what came back, including calls that failed validation or were refused."""
    results = {
        block["toolResult"]["toolUseId"]: block["toolResult"]
        for message in new_messages
        for block in message["content"]
        if "toolResult" in block
    }
    calls = []
    for message in new_messages:
        for block in message["content"]:
            if "toolUse" not in block:
                continue
            use = block["toolUse"]
            result = results.get(use["toolUseId"], {})
            text = " ".join(part["text"] for part in result.get("content", []) if "text" in part)
            calls.append(
                {
                    "tool": use["name"],
                    "input": use["input"],
                    "reasoning": use["input"].get("reasoning", ""),
                    "status": result.get("status", "not_run"),
                    "result": text[:_MAX_LOGGED_RESULT_CHARS],
                }
            )
    return calls


def _log_run(
    memory: WorkingMemory,
    stage_run: StageRun,
    tool_names: tuple[str, ...],
    system_prompt: str,
    message_count: int,
    tool_calls: list[dict[str, Any]],
) -> None:
    """Keep what the model was given and what it did, so any run can be audited later."""
    for call in tool_calls:
        memory.record_event(EventType.TOOL_CALL, phase=stage_run.phase, **call)
    memory.record_event(
        EventType.STAGE_RUN,
        phase=stage_run.phase,
        tools_offered=list(tool_names),
        system_prompt=system_prompt,
        message_count=message_count,
        input_tokens=stage_run.input_tokens,
        output_tokens=stage_run.output_tokens,
        seconds=stage_run.seconds,
        stop_reason=stage_run.stop_reason,
    )
