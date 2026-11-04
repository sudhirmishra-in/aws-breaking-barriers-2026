"""LOCAL MOCK tests: the model runner is stubbed. They check app-side contracts, not Bedrock behaviour."""
import pytest

from exchange.context import TurnOutput, TurnRequest
from exchange.guardrail import detected_pii_types
from exchange.prompts import system_prompt
from exchange.runtime import handle_turn
from exchange.tools import producer_history, evidence_unavailable

PRODUCER = {"producerId": "P-MX-004", "entityType": "cooperative", "location": "Loc", "crop": "coffee"}


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
    out = TurnOutput(reply="r", phase="intake", summary_en="a", summary_original="b")
    res = handle_turn(payload(mode="guidance"), runner(out), lambda t: [])
    assert res["phase"] == "guidance" and res["evidence"]["status"] == "unavailable"
    assert res["summaryEn"] == "a" and res["summaryOriginal"] == "b"


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
    assert ctx.producer.producerId == "P-MX-004"


def test_history_scoped_to_trusted_producer():
    from exchange.context import ProducerRef
    h1 = producer_history(ProducerRef(**PRODUCER))
    h2 = producer_history(ProducerRef(**{**PRODUCER, "producerId": "NOPE"}))
    assert len(h1["history"]) == 3 and h2["history"] == []


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


def test_french_prompt_and_summary_fields():
    from exchange.context import TrustedContext
    ctx = TrustedContext.model_validate(payload(lang="fr", mode="guidance")["context"])
    p = system_prompt(ctx)
    assert "Always reply in French" in p and "summary_original" in p and "in French" in p
    out = TurnOutput(reply="r", phase="guidance", summary_original="Pluies irrégulières", summary_en="Irregular rain")
    res = handle_turn(payload(lang="fr", mode="guidance"), runner(out), lambda t: [])
    assert res["language"] == "fr" and res["summaryOriginal"] == "Pluies irrégulières" and res["summaryEn"] == "Irregular rain"


def test_english_summary_original_falls_back_to_english():
    out = TurnOutput(reply="r", phase="guidance", summary_en="Late rain")
    res = handle_turn(payload(mode="guidance"), runner(out), lambda t: [])
    assert res["summaryOriginal"] == "Late rain"


def test_structured_output_used_when_present():
    from exchange.runtime import resolve_output
    out = TurnOutput(reply="ok", phase="intake")
    assert resolve_output(out, force=lambda: (_ for _ in ()).throw(AssertionError("not called")), text="x") is out


def test_missing_structured_output_is_forced_once():
    from exchange.runtime import resolve_output
    forced = TurnOutput(reply="forced", phase="playback", playback_summary="s")
    calls = []
    res = resolve_output(None, force=lambda: calls.append(1) or forced, text="plain")
    assert res is forced and calls == [1]


def test_failed_retry_keeps_plain_text_as_a_safe_intake_reply():
    from exchange.runtime import resolve_output
    def boom():
        raise ValueError("no tool call")
    res = resolve_output(None, force=boom, text="  ¿Qué ha sido difícil últimamente?  ")
    assert res.reply == "¿Qué ha sido difícil últimamente?" and res.phase == "intake" and res.playback_summary is None


def test_plain_text_fallback_cannot_advance_guidance_or_store_summaries():
    out = TurnOutput(reply="plain", phase="intake")
    res = handle_turn(payload(mode="guidance"), runner(out), lambda t: [])
    assert res["phase"] == "guidance" and res["summaryEn"] is None and res["summaryOriginal"] is None


def test_no_text_at_all_still_fails():
    from exchange.runtime import resolve_output
    import pytest as _pytest
    with _pytest.raises(RuntimeError):
        resolve_output(None, force=lambda: None, text="   ")


def test_guardrail_block_is_a_failure_not_a_reply():
    from exchange.runtime import GuardrailBlocked, BLOCKED_STOP_REASONS
    assert "guardrail_intervened" in BLOCKED_STOP_REASONS and issubclass(GuardrailBlocked, RuntimeError)


def test_greetings_are_natural_phrases_in_each_language():
    from exchange.runtime import GREETING
    assert GREETING == {"en": "Hello", "es": "Hola", "fr": "Bonjour"}


def test_challenge_tags_only_in_guidance_and_capped():
    out = TurnOutput(reply="r", phase="guidance", summary_en="a", summary_original="b", challenge_tags=["water", "water", "climate_weather", "soil_land", "health"])
    res = handle_turn(payload(mode="guidance"), runner(out), lambda t: [])
    assert res["challengeTags"] == ["water", "climate_weather", "soil_land"]
    res = handle_turn(payload(mode="intake"), runner(TurnOutput(reply="r", phase="intake", challenge_tags=["water"])), lambda t: [])
    assert res["challengeTags"] == []


def test_unknown_tags_are_rejected_by_the_schema():
    import pytest as _pytest
    from pydantic import ValidationError
    with _pytest.raises(ValidationError):
        TurnOutput(reply="r", phase="guidance", challenge_tags=["weather"])


def test_seed_producers_join_to_team_synthetic_data():
    import json, pathlib
    from exchange.tools import load_producers
    team = {p["producer_id"] for p in json.load(open(pathlib.Path(__file__).resolve().parents[2] / "data/team-synthetic/producers.json"))}
    ours = load_producers()
    assert {p["producerId"] for p in ours} <= team and all(p["entityType"] in {"smallholder", "cooperative", "estate", "processing_operation"} for p in ours)
