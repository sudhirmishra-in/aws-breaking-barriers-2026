from conftest import ME
from producer_exchange.agent.context import build_messages, build_system_prompt
from producer_exchange.agent.phases import PHASE_SPECS, ContextSection
from producer_exchange.memory.models import EvidenceSource, Phase, ReviewStatus, WorkingMemory


def _transcript(count):
    memory = WorkingMemory(exchange_id="ex", producer_id=ME, language="es")
    for index in range(count):
        memory.begin_turn(f"u{index}")
        memory.end_turn(f"a{index}")
    memory.begin_turn("latest")
    return memory


def test_messages_are_text_only_and_end_with_the_latest_user_message():
    messages = build_messages(_transcript(2), window=12)
    assert [message["role"] for message in messages] == ["user", "assistant", "user", "assistant", "user"]
    assert all(set(block) == {"text"} for message in messages for block in message["content"])
    assert messages[-1]["content"][0]["text"] == "latest"


def test_window_bounds_the_history_and_never_starts_with_the_assistant():
    messages = build_messages(_transcript(20), window=4)
    assert len(messages) == 3
    assert messages[0]["role"] == "user"
    assert messages[-1]["content"][0]["text"] == "latest"


def test_transcript_outside_the_window_survives_in_structured_memory(profiles):
    memory = _transcript(20)
    memory.understanding.challenge = "sequía desde el turno uno"
    spec = PHASE_SPECS[Phase.CLARIFY]
    prompt = build_system_prompt(spec, memory, profiles.load_view(ME))
    assert "sequía desde el turno uno" in prompt
    assert "u0" not in str(build_messages(memory, window=4))


def test_stages_read_only_the_memory_they_declare(profiles, memory):
    memory.register_evidence(EvidenceSource.REGIONAL, "RF-SECRET", "CHIRPS", "-31%")
    view = profiles.load_view(ME)
    assert "RF-SECRET" not in build_system_prompt(PHASE_SPECS[Phase.CLARIFY], memory, view)
    assert "RF-SECRET" in build_system_prompt(PHASE_SPECS[Phase.DRAFT], memory, view)


def test_every_section_is_renderable(profiles, memory):
    view = profiles.load_view(ME)
    for spec in PHASE_SPECS.values():
        assert spec.instructions in build_system_prompt(spec, memory, view)
    assert {section for spec in PHASE_SPECS.values() for section in spec.context} == set(ContextSection)


def test_prompt_is_ordered_stable_first_for_future_prompt_caching(profiles, memory):
    prompt = build_system_prompt(PHASE_SPECS[Phase.CLARIFY], memory, profiles.load_view(ME))
    assert prompt.index("<stage") < prompt.index("<producer_profile>\n") < prompt.index("<working_memory>\n")


def test_past_episodes_appear_only_after_review(profiles, memory):
    from test_profile import _confirmed

    result = profiles.commit_exchange(_confirmed([]))
    spec = PHASE_SPECS[Phase.CLARIFY]
    assert "<past_reviewed_exchanges>" not in build_system_prompt(spec, memory, profiles.load_view(ME))
    profiles.review_episode(ME, result.episode_id, status=ReviewStatus.APPROVED, reviewer="irl")
    prompt = build_system_prompt(spec, memory, profiles.load_view(ME))
    assert "<past_reviewed_exchanges>" in prompt
    assert "sequía" in prompt


def test_saved_quotes_and_notes_are_visible_so_the_model_does_not_save_them_again(profiles, memory):
    from producer_exchange.memory.models import SessionNote, UnderstandingUpdate

    memory.begin_turn("La lluvia es irregular y el comité pidió ayuda")
    memory.update_understanding(
        UnderstandingUpdate(
            producer_quotes=["La lluvia es irregular"],
            notes=[SessionNote(text="Comité activo", quote="el comité pidió ayuda")],
        )
    )
    prompt = build_system_prompt(PHASE_SPECS[Phase.CLARIFY], memory, profiles.load_view(ME))
    block = prompt.split("<working_memory>\n")[1]
    assert "La lluvia es irregular" in block
    assert "Comité activo" in block


def test_the_profile_block_states_when_a_value_became_true(profiles, memory):
    from producer_exchange.memory.models import ProfileField, ProposedFact

    fact = ProposedFact(field=ProfileField.ENTITY_TYPE, value="cooperative", quote="q", valid_from="este año")
    prompt = build_system_prompt(PHASE_SPECS[Phase.PLAYBACK], memory, profiles.load_view(ME, session_facts=[fact]))
    assert "entity_type: cooperative (confirmed in this exchange, since: este año)" in prompt
