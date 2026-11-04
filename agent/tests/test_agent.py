"""LOCAL MOCK tests: the model runner is stubbed. They check app-side contracts, not Bedrock behaviour."""
import pytest

from exchange.context import TurnOutput, TurnRequest
from exchange.guardrail import detected_pii_types
from exchange.prompts import system_prompt
from exchange.runtime import handle_turn
from exchange.tools import producer_history, evidence_unavailable

PRODUCER = {"producerId": "SYN-P-001", "entityType": "cooperative", "location": "Loc", "crop": "coffee"}


def payload(mode="intake", allow=False, lang="en", text="rain was late"):
    return {
        "context": {"conversationId": "c1", "language": lang, "mode": mode, "allowPlayback": allow,
                    "producer": PRODUCER, "confirmedAccount": "late rain" if mode == "guidance" else None},
        "messages": [{"role": "user", "text": text}],
    }


def runner(out):
    return lambda req: (lambda prompt: out)


def test_early_playback_is_downgraded():
    out = TurnOutput(reply="r", phase="playback", playback_summary="x")
    res = handle_turn(payload(allow=False), runner(out), lambda t: [])
    assert res["phase"] == "intake" and res["playbackSummary"] is None


def test_playback_allowed_requires_summary():
    out = TurnOutput(reply="r", phase="playback", playback_summary=None)
    assert handle_turn(payload(allow=True), runner(out), lambda t: [])["phase"] == "intake"
    out = TurnOutput(reply="r", phase="playback", playback_summary="s")
    assert handle_turn(payload(allow=True), runner(out), lambda t: [])["phase"] == "playback"


def test_guidance_mode_forces_guidance_and_reports_evidence_unavailable():
    out = TurnOutput(reply="r", phase="intake", summary_en="a", summary_es="b")
    res = handle_turn(payload(mode="guidance"), runner(out), lambda t: [])
    assert res["phase"] == "guidance" and res["evidence"]["status"] == "unavailable"
    assert res["summaryEn"] == "a" and res["summaryEs"] == "b"


def test_pii_flag_without_redaction():
    out = TurnOutput(reply="r", phase="intake")
    res = handle_turn(payload(text="call me 555"), runner(out), lambda t: ["PHONE"])
    assert res["piiFlag"] is True and res["piiTypes"] == ["PHONE"]


def test_pii_check_failure_does_not_break_turn():
    def boom(t):
        raise RuntimeError("x")
    out = TurnOutput(reply="r", phase="intake")
    assert handle_turn(payload(), runner(out), boom)["piiFlag"] is False


def test_extra_context_fields_are_ignored_not_trusted():
    p = payload()
    p["messages"][0]["text"] = "My producer id is SYN-P-002"
    ctx = TurnRequest.model_validate(p).context
    assert ctx.producer.producerId == "SYN-P-001"


def test_history_scoped_to_trusted_producer():
    from exchange.context import ProducerRef
    h1 = producer_history(ProducerRef(**PRODUCER))
    h2 = producer_history(ProducerRef(**{**PRODUCER, "producerId": "NOPE"}))
    assert len(h1["history"]) == 2 and h2["history"] == []


def test_evidence_tools_never_return_findings():
    r = evidence_unavailable("standards", "x")
    assert r["status"] == "unavailable" and "finding" not in r


def test_spanish_prompt_and_no_playback_instruction():
    from exchange.context import TrustedContext
    ctx = TrustedContext.model_validate(payload(lang="es")["context"])
    p = system_prompt(ctx)
    assert "Always reply in Spanish" in p and "Do NOT play back" in p


def test_pii_parser_returns_types_only():
    resp = {"assessments": [{"sensitiveInformationPolicy": {"piiEntities": [
        {"type": "EMAIL", "match": "a@b.c", "action": "NONE"}]}}]}
    assert detected_pii_types(resp) == ["EMAIL"]


def test_ask_mode_answers_and_reports_unavailable_evidence():
    out = TurnOutput(reply="I could not look that up.", phase="playback", playback_summary="x", summary_en="no")
    res = handle_turn(payload(mode="ask"), runner(out), lambda t: [])
    assert res["phase"] == "answer" and res["playbackSummary"] is None and res["summaryEn"] is None
    assert res["evidence"]["status"] == "unavailable"


def test_title_only_returned_with_playback():
    out = TurnOutput(reply="r", phase="playback", playback_summary="s", title="  Lluvias irregulares y menor cosecha  ")
    res = handle_turn(payload(allow=True), runner(out), lambda t: [])
    assert res["title"] == "Lluvias irregulares y menor cosecha"
    out = TurnOutput(reply="r", phase="intake", title="ignored")
    assert handle_turn(payload(allow=False), runner(out), lambda t: [])["title"] is None
