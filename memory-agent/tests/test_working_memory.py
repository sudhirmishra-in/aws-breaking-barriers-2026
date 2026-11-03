import pytest

from producer_exchange.agent.phases import next_phase
from producer_exchange.memory.models import (
    ChallengeTag,
    DraftClaim,
    EventType,
    EvidenceSource,
    GuidanceDraft,
    MemoryRuleError,
    Phase,
    ProfileField,
    ProposedFact,
    SessionNote,
    UnderstandingUpdate,
    UpdateEffect,
)
from producer_exchange.memory.store import RevisionConflict

COMPLETE = UnderstandingUpdate(
    challenge="sequía",
    onset="2024",
    severity="30%",
    actions_tried=[],
    tags=[ChallengeTag.WATER],
    location_checked=True,
    entity_type_checked=True,
)


def test_slots_track_what_is_missing(memory):
    assert "challenge" in memory.understanding.missing_slots()
    assert "actions_tried" in memory.understanding.missing_slots()
    memory.update_understanding(COMPLETE)
    assert memory.understanding.missing_slots() == []


def test_empty_actions_list_means_nothing_tried_rather_than_not_asked(memory):
    memory.update_understanding(UnderstandingUpdate(actions_tried=[]))
    assert "actions_tried" not in memory.understanding.missing_slots()


def test_partial_update_keeps_existing_values_and_bumps_version_only_on_change(memory):
    assert memory.update_understanding(UnderstandingUpdate(challenge="sequía")) == UpdateEffect.CHANGED
    assert memory.understanding.version == 1
    assert memory.update_understanding(UnderstandingUpdate(onset="2024")) == UpdateEffect.CHANGED
    assert memory.understanding.challenge == "sequía"
    assert memory.understanding.version == 2
    assert memory.update_understanding(UnderstandingUpdate(onset="2024")) == UpdateEffect.UNCHANGED
    assert memory.understanding.version == 2


def test_quotes_must_be_the_producers_exact_words(memory):
    memory.begin_turn("Somos una  Cooperativa de 350 familias")
    memory.update_understanding(UnderstandingUpdate(producer_quotes=["somos una cooperativa"]))
    with pytest.raises(MemoryRuleError):
        memory.update_understanding(UnderstandingUpdate(producer_quotes=["somos una empresa"]))
    assert memory.understanding.producer_quotes == ["somos una cooperativa"]


def test_near_duplicate_quotes_are_not_stored_twice(memory):
    memory.begin_turn("Hemos probado regar a mano, pero no alcanza el agua.")
    memory.update_understanding(UnderstandingUpdate(producer_quotes=["Hemos probado regar a mano, pero no alcanza el agua"]))
    effect = memory.update_understanding(UnderstandingUpdate(producer_quotes=["Hemos probado regar a mano, pero no alcanza el agua."]))
    assert effect == UpdateEffect.UNCHANGED
    assert len(memory.understanding.producer_quotes) == 1


def test_a_shorter_quote_inside_a_saved_one_adds_nothing_and_a_longer_one_replaces_it(memory):
    memory.begin_turn("La lluvia ha sido muy irregular y la cosecha bajó mucho")
    memory.update_understanding(UnderstandingUpdate(producer_quotes=["La lluvia ha sido muy irregular"]))
    memory.update_understanding(UnderstandingUpdate(producer_quotes=["muy irregular"]))
    assert memory.understanding.producer_quotes == ["La lluvia ha sido muy irregular"]
    memory.update_understanding(UnderstandingUpdate(producer_quotes=["La lluvia ha sido muy irregular y la cosecha bajó mucho"]))
    assert memory.understanding.producer_quotes == ["La lluvia ha sido muy irregular y la cosecha bajó mucho"]


def test_quotes_and_notes_do_not_move_the_version_or_revoke_confirmation(memory):
    _played_back(memory)
    memory.begin_turn("sí, y el comité de agua pidió ayuda")
    memory.confirm_understanding()
    version = memory.understanding.version
    note = SessionNote(text="El comité pidió ayuda", quote="el comité de agua pidió ayuda")
    effect = memory.update_understanding(UnderstandingUpdate(notes=[note], producer_quotes=["pidió ayuda"]))
    assert effect == UpdateEffect.RECORDED
    assert memory.understanding.version == version
    assert memory.is_confirmed


def test_notes_need_the_producers_exact_words_and_are_not_repeated(memory):
    memory.begin_turn("el comité de agua pidió ayuda")
    note = SessionNote(text="Pidieron ayuda", quote="el comité de agua pidió ayuda")
    memory.update_understanding(UnderstandingUpdate(notes=[note]))
    assert memory.update_understanding(UnderstandingUpdate(notes=[note])) == UpdateEffect.UNCHANGED
    with pytest.raises(MemoryRuleError):
        memory.update_understanding(UnderstandingUpdate(notes=[SessionNote(text="x", quote="nunca lo dije")]))
    assert len(memory.understanding.notes) == 1


def test_quotes_cannot_come_from_the_agents_own_messages(memory):
    memory.begin_turn("hola")
    memory.end_turn("usted es una cooperativa")
    fact = ProposedFact(field=ProfileField.ENTITY_TYPE, value="cooperative", quote="usted es una cooperativa")
    with pytest.raises(MemoryRuleError):
        memory.update_understanding(UnderstandingUpdate(profile_facts=[fact]))


def test_single_valued_fact_is_replaced_and_multi_valued_fact_accumulates(memory):
    memory.begin_turn("somos cooperativa, antes asociación; usamos riego; usamos abono")
    entity = lambda value: ProposedFact(field=ProfileField.ENTITY_TYPE, value=value, quote="somos cooperativa")
    practice = lambda value, quote: ProposedFact(field=ProfileField.CURRENT_PRACTICE, value=value, quote=quote)
    memory.update_understanding(UnderstandingUpdate(profile_facts=[entity("association"), practice("riego", "usamos riego")]))
    memory.update_understanding(UnderstandingUpdate(profile_facts=[entity("cooperative"), practice("abono", "usamos abono")]))
    values = [(fact.field, fact.value) for fact in memory.understanding.profile_facts]
    assert (ProfileField.ENTITY_TYPE, "association") not in values
    assert (ProfileField.ENTITY_TYPE, "cooperative") in values
    assert {value for field, value in values if field == ProfileField.CURRENT_PRACTICE} == {"riego", "abono"}


def test_member_count_must_be_a_number_so_reviewed_values_stay_comparable():
    with pytest.raises(ValueError, match="digits"):
        ProposedFact(field=ProfileField.MEMBER_COUNT, value="about 350 families", quote="unas 350 familias")
    assert ProposedFact(field=ProfileField.MEMBER_COUNT, value="350", quote="unas 350 familias").value == "350"


def _played_back(memory):
    memory.begin_turn("primera")
    memory.update_understanding(COMPLETE)
    memory.mark_playback_shown()


def test_confirmation_in_the_same_turn_as_playback_is_refused(memory):
    _played_back(memory)
    with pytest.raises(MemoryRuleError, match="not answered"):
        memory.confirm_understanding()


def test_confirmation_of_an_unseen_version_is_refused(memory):
    _played_back(memory)
    memory.begin_turn("sí, pero fue en 2023")
    memory.update_understanding(UnderstandingUpdate(onset="2023"))
    with pytest.raises(MemoryRuleError, match="not been played back"):
        memory.confirm_understanding()


def test_confirmation_after_a_later_turn_succeeds_and_a_new_correction_revokes_it(memory):
    _played_back(memory)
    memory.begin_turn("sí")
    memory.confirm_understanding()
    assert memory.is_confirmed
    memory.update_understanding(UnderstandingUpdate(onset="2023"))
    assert not memory.is_confirmed


def test_facts_become_session_facts_only_after_confirmation(memory):
    memory.begin_turn("somos cooperativa")
    fact = ProposedFact(field=ProfileField.ENTITY_TYPE, value="cooperative", quote="somos cooperativa")
    memory.update_understanding(COMPLETE.model_copy(update={"profile_facts": [fact]}))
    assert memory.confirmed_facts() == []
    memory.mark_playback_shown()
    memory.begin_turn("sí")
    memory.confirm_understanding()
    assert memory.confirmed_facts() == [fact]


def test_evidence_ids_are_stable_for_the_same_source(memory):
    first = memory.register_evidence(EvidenceSource.REGIONAL, "RF-1", "CHIRPS", "-31%")
    again = memory.register_evidence(EvidenceSource.REGIONAL, "RF-1", "CHIRPS", "-31%")
    other = memory.register_evidence(EvidenceSource.PEER_CASE, "RF-1", "Peer", "x")
    assert first.evidence_id == again.evidence_id
    assert other.evidence_id != first.evidence_id


def test_draft_citations_must_point_at_this_sessions_ledger(memory):
    evidence = memory.register_evidence(EvidenceSource.REGIONAL, "RF-1", "CHIRPS", "-31%")
    clause = memory.register_evidence(EvidenceSource.STANDARD, "APS-1", "APS", "text")
    claim = lambda **kwargs: DraftClaim(kind="insight", text="x", **kwargs)
    draft = lambda *claims: GuidanceDraft(intro="i", claims=list(claims), closing="c")
    for bad in (
        claim(evidence_ids=["E99"]),
        claim(evidence_ids=[clause.evidence_id]),
        claim(evidence_ids=[evidence.evidence_id], standard_evidence_ids=[evidence.evidence_id]),
    ):
        with pytest.raises(MemoryRuleError):
            memory.store_draft(draft(bad))
        assert memory.draft is None
    memory.store_draft(draft(claim(evidence_ids=[evidence.evidence_id], standard_evidence_ids=[clause.evidence_id])))
    assert memory.draft is not None


def test_phase_is_derived_from_memory(memory):
    assert next_phase(memory) == Phase.CLARIFY
    _played_back(memory)
    assert next_phase(memory) == Phase.PLAYBACK
    memory.begin_turn("sí")
    memory.confirm_understanding()
    assert next_phase(memory) == Phase.RETRIEVE
    for source in EvidenceSource:
        memory.mark_retrieved(source)
    assert next_phase(memory) == Phase.DRAFT
    memory.store_draft(GuidanceDraft(intro="i", closing="c"))
    assert next_phase(memory) == Phase.DRAFTED


def test_a_correction_that_empties_a_slot_returns_to_clarify(memory):
    _played_back(memory)
    memory.understanding.onset = None
    assert next_phase(memory) == Phase.CLARIFY


def test_repository_round_trip_and_stale_writes_are_rejected(memory, working):
    working.save(memory)
    memory.begin_turn("hola")
    working.save(memory)

    first, second = working.load("ex-1"), working.load("ex-1")
    assert first.transcript[0].text == "hola"
    first.begin_turn("a")
    working.save(first)
    second.begin_turn("b")
    with pytest.raises(RevisionConflict):
        working.save(second)
    assert [entry.text for entry in working.load("ex-1").transcript] == ["hola", "a"]


def test_transcript_is_derived_from_the_event_log(memory):
    memory.begin_turn("hola")
    memory.record_event(EventType.TOOL_CALL, tool="record_understanding")
    memory.end_turn("buenas")
    assert [event.seq for event in memory.events] == [1, 2, 3]
    assert [(entry.role, entry.text, entry.turn) for entry in memory.transcript] == [("user", "hola", 1), ("assistant", "buenas", 1)]


def test_state_and_events_are_stored_as_separate_documents(memory, working, store):
    memory.begin_turn("hola")
    working.save(memory)
    documents = store.query("EXCHANGE#ex-1")
    assert [document.sk for document in documents] == ["EVENT#00000001", "STATE"]
    state = next(document for document in documents if document.sk == "STATE")
    assert "hola" not in str(state.body)
    assert "events" not in state.body


def test_saved_events_are_never_rewritten(memory, working, store):
    memory.begin_turn("primera")
    working.save(memory)
    first_event = store.get("EXCHANGE#ex-1", "EVENT#00000001")
    loaded = working.load("ex-1")
    assert loaded.saved_events == 1
    loaded.begin_turn("segunda")
    working.save(loaded)
    assert store.get("EXCHANGE#ex-1", "EVENT#00000001") == first_event
    assert [entry.text for entry in working.load("ex-1").transcript] == ["primera", "segunda"]


def test_a_stale_save_writes_no_events(memory, working, store):
    working.save(memory)
    first, second = working.load("ex-1"), working.load("ex-1")
    first.begin_turn("a")
    working.save(first)
    second.record_event(EventType.PII_FLAG, entity_types=[])
    second.record_event(EventType.PII_FLAG, entity_types=[])
    with pytest.raises(RevisionConflict):
        working.save(second)
    assert len(store.query("EXCHANGE#ex-1", "EVENT#")) == 1


def test_every_document_shares_one_fixed_deadline(memory, working, store):
    memory.begin_turn("hola")
    working.save(memory)
    deadline = memory.expires_at
    assert deadline is not None
    memory.begin_turn("otra vez")
    working.save(memory)
    assert memory.expires_at == deadline
    assert {document.expires_at for document in store.query("EXCHANGE#ex-1")} == {deadline}


def test_repository_delete_removes_the_state_and_the_whole_log(memory, working, store):
    memory.begin_turn("hola")
    memory.end_turn("buenas")
    working.save(memory)
    working.delete("ex-1")
    assert working.load("ex-1") is None
    assert store.query("EXCHANGE#ex-1") == []
