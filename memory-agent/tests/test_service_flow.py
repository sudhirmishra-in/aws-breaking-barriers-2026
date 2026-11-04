"""The whole turn loop, offline: stage changes, memory persistence and what the model is actually sent."""

import json

import pytest
from fakes import ScriptedModel, call, say

from conftest import ME, OTHER
from producer_exchange.memory.models import EventType, MemoryRuleError, Phase, ProfileField, ReviewStatus
from producer_exchange.service import ExchangeNotFound


def _stage(model_call) -> str:
    return model_call.system_prompt.split("<stage name='")[1].split("'")[0]


def _last_user_text(model_call) -> str:
    return next(block["text"] for block in model_call.messages[-1]["content"] if "text" in block) if "text" in model_call.messages[-1]["content"][0] else ""


def _section(prompt: str, name: str) -> str:
    """The memory block itself, not a mention of its name in the stage instructions."""
    return prompt.split(f"<{name}>\n")[1].split(f"\n</{name}>")[0]


COMPLETE = dict(
    reasoning="saving",
    challenge="La lluvia es irregular",
    onset="2024",
    severity="30%",
    actions_tried=["riego a mano"],
    tags=["water"],
    producer_quotes=["La lluvia es irregular"],
    location_checked=True,
    entity_type_checked=True,
)
ENTITY_FACT = {"field": "entity_type", "value": "cooperative", "quote": "somos cooperativa"}


def _happy_script(model_call):
    """A well-behaved model, keyed on the stage and the last message."""
    stage, last = _stage(model_call), _last_user_text(model_call)
    if stage == "clarify":
        if "lluvia" in last and "No field recorded" not in model_call.system_prompt and '"challenge": null' in model_call.system_prompt:
            return [call("record_understanding", **COMPLETE)]
        return [say("¿Cuándo empezó?")]
    if stage == "playback":
        if "cooperativa" in last and "cooperative" not in _section(model_call.system_prompt, "working_memory"):
            return [call("record_understanding", reasoning="correction", profile_facts=[ENTITY_FACT])]
        if '"awaiting_confirmation": true' in model_call.system_prompt and last.strip() == "Sí":
            return [call("confirm_understanding", reasoning="said yes")]
        return [say("Entendí: lluvia irregular desde 2024. ¿Es correcto?")]
    if stage == "retrieve":
        return [
            call("get_producer_record", reasoning="r"),
            call("get_regional_context", reasoning="r", tags=["water"]),
            call("search_peer_examples", reasoning="r", tags=["water"]),
            call("retrieve_standards", reasoning="r", tags=["water"]),
        ]
    if stage == "draft":
        prompt = model_call.system_prompt
        return [
            call(
                "submit_guidance",
                reasoning="r",
                draft={
                    "intro": "Esto muestran los datos.",
                    "claims": [
                        {"kind": "insight", "text": "La lluvia cayó.", "evidence_ids": [_first_id(prompt, "regional")]},
                        {
                            "kind": "peer_example",
                            "text": "Otra organización instaló tanques.",
                            "evidence_ids": [_first_id(prompt, "peer_case")],
                            "standard_evidence_ids": [_first_id(prompt, "standard")],
                        },
                    ],
                    "closing": "La decisión es suya.",
                },
            )
        ]
    return [say("Según el borrador, la lluvia cayó.")]


def _first_id(prompt: str, source_type: str) -> str:
    evidence = json.loads(_section(prompt, "evidence"))
    return next(item["evidence_id"] for item in evidence if item["source_type"] == source_type)


@pytest.fixture
def model():
    return ScriptedModel(_happy_script)


@pytest.fixture
def service(make_service, model):
    return make_service(model)


def _to_playback(service):
    started = service.start_exchange(ME)
    response = service.handle_turn(started.exchange_id, ME, "La lluvia es irregular")
    return started.exchange_id, response


def _to_drafted(service):
    exchange_id, _ = _to_playback(service)
    response = service.handle_turn(exchange_id, ME, "Sí")
    return exchange_id, response


def test_greeting_is_open_and_uses_the_producers_language(service):
    started = service.start_exchange(ME)
    assert started.phase == Phase.CLARIFY
    assert "difícil" in started.greeting


def test_a_complete_message_moves_to_playback_in_one_turn_with_two_model_runs(service):
    exchange_id, response = _to_playback(service)
    assert response.phase == Phase.PLAYBACK
    assert [run.phase for run in response.stage_runs] == [Phase.CLARIFY, Phase.PLAYBACK]
    assert "¿Es correcto?" in response.reply
    memory = service.get_working_memory(exchange_id, ME)
    assert memory.awaiting_confirmation
    assert memory.confirmed_version is None


def test_confirmation_runs_through_retrieval_and_draft_within_one_turn(service):
    exchange_id, response = _to_drafted(service)
    assert response.completed
    assert response.phase == Phase.DRAFTED
    assert [run.phase for run in response.stage_runs] == [Phase.PLAYBACK, Phase.RETRIEVE, Phase.DRAFT]
    memory = service.get_working_memory(exchange_id, ME)
    assert memory.draft is not None
    assert {item.source_type.value for item in memory.evidence.values()} >= {"regional", "peer_case", "standard"}


def test_drafted_reply_cites_sources_from_the_ledger_and_is_labelled_unverified(service):
    exchange_id, response = _to_drafted(service)
    memory = service.get_working_memory(exchange_id, ME)
    assert "Borrador, aún sin verificar" in response.reply
    assert "SYNTHETIC STAND-IN" in response.reply
    assert all(claim.text in response.reply for claim in memory.draft.claims)


def test_correction_during_playback_replays_before_accepting_confirmation(make_service):
    """A correction bumps the version, so the next message must confirm the new playback."""
    script = ScriptedModel(_happy_script)
    service = make_service(script)
    exchange_id, _ = _to_playback(service)
    response = service.handle_turn(exchange_id, ME, "No, somos cooperativa")
    memory = service.get_working_memory(exchange_id, ME)
    assert response.phase == Phase.PLAYBACK
    assert memory.understanding.version == 2
    assert memory.shown_version == 2
    assert not memory.is_confirmed
    # Not effective until confirmed.
    assert service.get_profile(ME).current(ProfileField.ENTITY_TYPE) == "small producer association"
    response = service.handle_turn(exchange_id, ME, "Sí")
    assert response.phase == Phase.DRAFTED


def test_confirmed_fact_is_used_for_this_exchanges_peer_query_only(make_service, model, sources, profiles):
    service = make_service(model)
    captured = []
    original = sources.peers.search
    object.__setattr__(sources.peers, "search", lambda query: captured.append(query) or original(query))
    exchange_id, _ = _to_playback(service)
    service.handle_turn(exchange_id, ME, "No, somos cooperativa")
    service.handle_turn(exchange_id, ME, "Sí")
    assert captured[-1].entity_type == "cooperative"
    assert service.get_profile(ME).current(ProfileField.ENTITY_TYPE) == "small producer association"


def test_prompt_and_tools_stay_frozen_within_a_run_and_history_is_text_only_between_runs(make_service, model):
    service = make_service(model)
    _to_drafted(service)
    for model_call in model.calls:
        spec_tools = model_call.tool_names
        assert "record_understanding" not in spec_tools or _stage(model_call) in ("clarify", "playback")
        assert "get_regional_context" not in spec_tools or _stage(model_call) == "retrieve"
        # Every run starts from a plain transcript: no replayed tool or thinking blocks.
        assert all(set(block) == {"text"} for message in model_call.messages for block in message["content"])


def test_each_stage_sees_only_its_own_tools(make_service, model):
    service = make_service(model)
    _to_drafted(service)
    by_stage = {_stage(model_call): set(model_call.tool_names) for model_call in model.calls}
    assert by_stage["clarify"] == {"record_understanding"}
    assert by_stage["playback"] == {"record_understanding", "confirm_understanding"}
    assert by_stage["retrieve"] == {"get_producer_record", "get_regional_context", "search_peer_examples", "retrieve_standards"}
    assert by_stage["draft"] == {"retrieve_standards", "submit_guidance"}


def test_follow_up_after_the_draft_goes_to_the_model_without_tools(make_service, model):
    service = make_service(model)
    exchange_id, _ = _to_drafted(service)
    response = service.handle_turn(exchange_id, ME, "¿Cuánto cayó?")
    assert response.reply == "Según el borrador, la lluvia cayó."
    assert model.calls[-1].tool_names == ()
    assert "<draft>\n" in model.calls[-1].system_prompt


def test_memory_survives_a_new_service_instance(make_service, model):
    first = make_service(model)
    exchange_id, _ = _to_playback(first)
    second = make_service(model)
    response = second.handle_turn(exchange_id, ME, "Sí")
    assert response.phase == Phase.DRAFTED


def test_a_failed_tool_keeps_memory_clean_and_the_model_can_try_again(make_service):
    attempts = []

    def script(model_call):
        if _stage(model_call) == "clarify":
            if not attempts:
                attempts.append(1)
                return [call("record_understanding", reasoning="r", producer_quotes=["nunca dije esto"])]
            return [say("¿Puede contarme más?")]
        raise AssertionError("unexpected stage")

    service = make_service(ScriptedModel(script))
    started = service.start_exchange(ME)
    response = service.handle_turn(started.exchange_id, ME, "Hola")
    memory = service.get_working_memory(started.exchange_id, ME)
    assert response.reply == "¿Puede contarme más?"
    assert memory.understanding.producer_quotes == []
    assert memory.understanding.version == 0
    calls = [event for event in memory.events if event.type == EventType.TOOL_CALL]
    assert [(event.data["tool"], event.data["status"]) for event in calls] == [("record_understanding", "error")]


def test_a_silent_stage_that_never_advances_ends_with_a_fallback_and_keeps_its_place(make_service):
    def script(model_call):
        stage = _stage(model_call)
        if stage == "clarify":
            return [call("record_understanding", **COMPLETE)]
        if stage == "playback":
            if '"awaiting_confirmation": true' in model_call.system_prompt:
                return [call("confirm_understanding", reasoning="yes")]
            return [say("¿Correcto?")]
        return [say("I refuse to call tools")]

    service = make_service(ScriptedModel(script))
    exchange_id, _ = _to_playback(service)
    response = service.handle_turn(exchange_id, ME, "Sí")
    assert response.completed is False
    assert response.phase == Phase.RETRIEVE
    assert "no pude completar" in response.reply


def test_runaway_stage_loop_is_bounded(make_service):
    counter = {"n": 0}

    def script(model_call):
        counter["n"] += 1
        return [call("record_understanding", reasoning="r", challenge=f"v{counter['n']}")]

    service = make_service(ScriptedModel(script))
    started = service.start_exchange(ME)
    response = service.handle_turn(started.exchange_id, ME, "Hola")
    assert response.completed is False
    assert len(response.stage_runs) == 8


def test_an_invalid_fact_is_returned_to_the_model_to_fix_without_changing_memory(make_service):
    results = []

    def script(model_call):
        last = model_call.messages[-1]["content"][0]
        if "toolResult" in last:
            results.append(last["toolResult"])
            return [say("¿Cuántas familias son?")]
        return [
            call(
                "record_understanding",
                reasoning="r",
                profile_facts=[{"field": "member_count", "value": "about 350", "quote": "unas 350 familias"}],
            )
        ]

    service = make_service(ScriptedModel(script))
    started = service.start_exchange(ME)
    response = service.handle_turn(started.exchange_id, ME, "Somos unas 350 familias")
    assert results[0]["status"] == "error"
    assert "digits" in results[0]["content"][0]["text"]
    assert response.reply == "¿Cuántas familias son?"
    assert service.get_working_memory(started.exchange_id, ME).understanding.profile_facts == []


def test_a_tool_that_keeps_failing_cannot_loop_forever_within_one_run(make_service):
    model = ScriptedModel(lambda model_call: [call("record_understanding", reasoning="r", producer_quotes=["nunca dije esto"])])
    service = make_service(model)
    started = service.start_exchange(ME)
    response = service.handle_turn(started.exchange_id, ME, "Hola")
    assert response.completed is False
    assert len(model.calls) <= 8  # one nudged retry, each run capped at max_model_calls_per_run
    assert service.get_working_memory(started.exchange_id, ME).understanding.version == 0


def test_observer_sees_the_exact_prompt_and_the_memory_change_of_each_run(store, sources):
    from producer_exchange.config import Settings
    from producer_exchange.factory import build_service
    from producer_exchange.safety.pii import NoopPiiDetector

    traces = []
    model = ScriptedModel(_happy_script)
    service = build_service(
        Settings(), store=store, sources=sources, model=model, pii=NoopPiiDetector(), observer=traces.append
    )
    _to_playback(service)
    assert [trace.stage_run.phase for trace in traces] == [Phase.CLARIFY, Phase.PLAYBACK]
    assert [trace.system_prompt for trace in traces] == [call_.system_prompt for call_ in model.calls]
    first = traces[0]
    assert first.tool_names == ("record_understanding",)
    assert first.memory_before["understanding"]["version"] == 0
    assert first.memory_after["understanding"]["version"] == 1
    assert first.memory_after["event_count"] > first.memory_before["event_count"]
    assert any("toolUse" in block for message in first.run_messages for block in message["content"])
    assert all(set(block) == {"text"} for message in first.request_messages for block in message["content"])


def test_the_event_log_records_every_run_with_its_exact_prompt_and_every_tool_call(make_service, model):
    service = make_service(model)
    exchange_id, _ = _to_playback(service)
    log = service.get_event_log(exchange_id, ME)
    assert [event.type for event in log] == [
        EventType.USER_MESSAGE,
        EventType.TOOL_CALL,
        EventType.STAGE_RUN,
        EventType.STAGE_RUN,
        EventType.ASSISTANT_MESSAGE,
    ]
    assert [event.seq for event in log] == [1, 2, 3, 4, 5]
    call = log[1]
    assert call.data["tool"] == "record_understanding"
    assert call.data["reasoning"] == "saving"
    assert call.data["input"]["challenge"] == "La lluvia es irregular"
    assert call.data["status"] == "success"
    assert log[2].data["system_prompt"] == model.calls[0].system_prompt
    assert log[2].data["input_tokens"] == 10


def test_a_write_of_only_quotes_does_not_force_a_new_stage_run(make_service):
    def script(model_call):
        last = model_call.messages[-1]["content"][0]
        if "toolResult" in last:
            return [say("¿Desde cuándo?")]
        return [call("record_understanding", reasoning="r", producer_quotes=["La lluvia es irregular"])]

    service = make_service(ScriptedModel(script))
    started = service.start_exchange(ME)
    response = service.handle_turn(started.exchange_id, ME, "La lluvia es irregular")
    assert len(response.stage_runs) == 1
    assert response.reply == "¿Desde cuándo?"
    memory = service.get_working_memory(started.exchange_id, ME)
    assert memory.understanding.version == 0
    assert memory.understanding.producer_quotes == ["La lluvia es irregular"]


def test_the_commit_is_recorded_in_the_log(service):
    exchange_id, _ = _to_drafted(service)
    result = service.commit_memory(exchange_id, ME, consent_granted=True)
    last = service.get_event_log(exchange_id, ME)[-1]
    assert last.type == EventType.MEMORY_COMMITTED
    assert last.data["episode_id"] == result.episode_id


def test_exchanges_are_bound_to_their_producer(service):
    exchange_id, _ = _to_playback(service)
    for action in (
        lambda: service.handle_turn(exchange_id, OTHER, "Sí"),
        lambda: service.get_working_memory(exchange_id, OTHER),
        lambda: service.get_event_log(exchange_id, OTHER),
        lambda: service.commit_memory(exchange_id, OTHER, consent_granted=True),
        lambda: service.discard_exchange(exchange_id, OTHER),
    ):
        with pytest.raises(ExchangeNotFound):
            action()
    assert service.get_working_memory(exchange_id, ME).turn == 1


def test_commit_requires_explicit_consent_and_confirmation(service):
    exchange_id, _ = _to_playback(service)
    with pytest.raises(MemoryRuleError, match="consent"):
        service.commit_memory(exchange_id, ME, consent_granted=False)
    with pytest.raises(MemoryRuleError, match="confirmed"):
        service.commit_memory(exchange_id, ME, consent_granted=True)


def test_no_durable_profile_write_happens_during_conversation(service, profiles):
    _to_drafted(service)
    assert profiles.list_facts(ME) == []
    assert profiles.list_episodes(ME) == []


def test_full_longitudinal_loop_commit_review_then_a_new_exchange_remembers(make_service, model, profiles):
    service = make_service(model)
    exchange_id, _ = _to_playback(service)
    service.handle_turn(exchange_id, ME, "No, somos cooperativa")
    service.handle_turn(exchange_id, ME, "Sí")
    result = service.commit_memory(exchange_id, ME, consent_granted=True)
    assert service.get_working_memory(exchange_id, ME).committed_at is not None

    pending = service.start_exchange(ME)
    service.handle_turn(pending.exchange_id, ME, "Hola")
    assert "<past_reviewed_exchanges>\n" not in model.calls[-1].system_prompt
    assert "small producer association" in model.calls[-1].system_prompt

    profiles.review_fact(ME, result.fact_ids[0], status=ReviewStatus.APPROVED, reviewer="irl")
    profiles.review_episode(ME, result.episode_id, status=ReviewStatus.APPROVED, reviewer="irl")

    later = service.start_exchange(ME)
    service.handle_turn(later.exchange_id, ME, "Hola")
    prompt = model.calls[-1].system_prompt
    assert "<past_reviewed_exchanges>" in prompt
    assert "entity_type: cooperative (reviewed)" in prompt


def test_discard_removes_the_state_and_log_and_writes_nothing_durable(service, profiles, store):
    exchange_id, _ = _to_playback(service)
    assert store.query(f"EXCHANGE#{exchange_id}")
    service.discard_exchange(exchange_id, ME)
    with pytest.raises(ExchangeNotFound):
        service.get_working_memory(exchange_id, ME)
    assert store.query(f"EXCHANGE#{exchange_id}") == []
    assert profiles.list_episodes(ME) == []


def test_pii_is_flagged_without_altering_the_transcript(store, sources, model):
    from producer_exchange.config import Settings
    from producer_exchange.factory import build_service
    from producer_exchange.memory.models import PiiFlag

    class Detector:
        def scan(self, text, language, turn):
            return PiiFlag(turn=turn, entity_types=["PHONE"])

    service = build_service(Settings(), store=store, sources=sources, model=model, pii=Detector())
    started = service.start_exchange(ME)
    text = "La lluvia es irregular, llámenme al 3125550199"
    service.handle_turn(started.exchange_id, ME, text)
    memory = service.get_working_memory(started.exchange_id, ME)
    assert memory.pii_flags[0].entity_types == ["PHONE"]
    assert memory.transcript[0].text == text
