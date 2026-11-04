from __future__ import annotations

import logging
import os
from typing import Callable

from .context import TurnRequest, TurnResponse, TurnOutput
from .guardrail import check_pii
from .prompts import system_prompt
from .tools import build_tools

log = logging.getLogger("exchange")

# AgentFactory(request) -> callable(prompt) -> TurnOutput. Injectable so tests can avoid Bedrock (LOCAL MOCK).
AgentRunner = Callable[[str], TurnOutput]


def _build_real_runner(req: TurnRequest) -> AgentRunner:
    from strands import Agent
    from strands.models import BedrockModel

    guardrail_id = os.environ["GUARDRAIL_ID"]
    guardrail_version = os.environ["GUARDRAIL_VERSION"]
    model = BedrockModel(
        model_id=os.environ["MODEL_ID"],
        region_name=os.environ.get("AWS_REGION", "us-west-2"),
        max_tokens=700,
        temperature=0.4,
        guardrail_id=guardrail_id,
        guardrail_version=guardrail_version,
        guardrail_trace="disabled",
    )
    history = [{"role": m.role, "content": [{"text": m.text}]} for m in req.messages[:-1]]
    if history and history[0]["role"] == "assistant":  # Bedrock requires the first turn to be the user's
        # A natural greeting, not an instruction: instruction-like user text trips the guardrail's prompt-attack filter.
        history.insert(0, {"role": "user", "content": [{"text": GREETING[req.context.language]}]})
    agent = Agent(
        model=model,
        system_prompt=system_prompt(req.context),
        tools=build_tools(req.context.producer),
        messages=history,
        callback_handler=None,
    )

    def run(prompt: str) -> TurnOutput:
        result = agent(prompt, structured_output_model=TurnOutput)
        if result.stop_reason in BLOCKED_STOP_REASONS:
            # Never turn a guardrail block message into a reply; the caller has its own safe fallback.
            log.warning("guardrail_intervened conversation=%s", req.context.conversationId)
            raise GuardrailBlocked(result.stop_reason)
        return resolve_output(
            result.structured_output,
            force=lambda: agent.structured_output(TurnOutput, FORCE_FORMAT_PROMPT),
            text=str(result),
            conversation_id=req.context.conversationId,
        )

    return run


GREETING = {"en": "Hello", "es": "Hola", "fr": "Bonjour"}
BLOCKED_STOP_REASONS = {"guardrail_intervened", "content_filtered"}


class GuardrailBlocked(RuntimeError):
    """The guardrail blocked this turn. Surfaced as a failure, never as a reply."""


FORCE_FORMAT_PROMPT = (
    "Return your last reply to the producer in the required structured format. "
    "Do not change its content or language."
)


def resolve_output(structured, force, text: str, conversation_id: str = "") -> TurnOutput:
    """The model occasionally ends a turn with plain text instead of the structured output.
    1) use the structured output; 2) ask once more, forcing the format; 3) keep the plain text as an
    ordinary intake reply, which never triggers a workflow transition (playback, guidance or storage)."""
    if structured is not None:
        return structured
    log.warning("structured_output_missing conversation=%s", conversation_id)
    try:
        forced = force()
        if forced is not None:
            return forced
    except Exception as e:  # noqa: BLE001 - recovery path; the reason is logged without content
        log.warning("structured_output_retry_failed conversation=%s error=%s", conversation_id, type(e).__name__)
    reply = (text or "").strip()
    if reply:
        return TurnOutput(reply=reply, phase="intake")
    raise RuntimeError("model returned no structured output")


def _pii_client():
    import boto3

    return boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-west-2"))


def handle_turn(
    payload: dict,
    runner_factory: Callable[[TurnRequest], AgentRunner] = _build_real_runner,
    pii_checker: Callable[[str], list[str]] | None = None,
) -> dict:
    req = TurnRequest.model_validate(payload)
    last = req.messages[-1]
    if last.role != "user":
        raise ValueError("last message must be from the user")

    if pii_checker is None:
        client = _pii_client()
        gid, gver = os.environ["GUARDRAIL_ID"], os.environ["GUARDRAIL_VERSION"]
        pii_checker = lambda text: check_pii(client, gid, gver, text)  # noqa: E731
    try:
        pii_types = pii_checker(last.text)
    except Exception:  # flagging must not break the turn; fail open on the flag, log structurally
        log.warning("pii_check_failed conversation=%s", req.context.conversationId)
        pii_types = []

    out = runner_factory(req)(last.text)

    # Enforce the phase contract the application relies on; the app re-checks independently.
    phase = out.phase
    if req.context.mode == "intake" and phase in ("guidance", "answer"):
        phase = "intake"
    if req.context.mode == "intake" and not req.context.allowPlayback and phase == "playback":
        phase = "intake"
    if req.context.mode == "guidance":
        phase = "guidance"
    if req.context.mode == "ask":
        phase = "answer"
    playback = out.playback_summary if phase == "playback" else None
    if req.context.mode == "ask":
        playback = None
    if phase == "playback" and not playback:
        phase = "intake"

    log.info(
        "turn conversation=%s mode=%s phase=%s pii=%d",
        req.context.conversationId, req.context.mode, phase, len(pii_types),
    )
    return TurnResponse(
        reply=out.reply,
        phase=phase,
        playbackSummary=playback,
        title=(out.title or "").strip()[:80] or None if playback else None,
        summaryOriginal=(out.summary_original or (out.summary_en if req.context.language == "en" else None)) if phase == "guidance" else None,
        summaryEn=out.summary_en if phase == "guidance" else None,
        piiFlag=bool(pii_types),
        piiTypes=pii_types,
        language=req.context.language,
    ).model_dump()
