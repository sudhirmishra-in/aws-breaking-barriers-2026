import pytest

from conftest import ME
from producer_exchange.memory.models import (
    ChallengeTag,
    MemoryRuleError,
    PiiFlag,
    ProfileField,
    ProposedFact,
    ReviewStatus,
    SessionNote,
    UnderstandingUpdate,
    WorkingMemory,
)
from producer_exchange.memory.profile import Provenance


def _confirmed(facts, exchange_id="ex-1") -> WorkingMemory:
    memory = WorkingMemory(exchange_id=exchange_id, producer_id=ME, language="es")
    memory.begin_turn("somos una cooperativa de 350 familias en Sullana y también cultivamos mango")
    memory.update_understanding(
        UnderstandingUpdate(
            challenge="sequía",
            onset="2024",
            severity="30%",
            actions_tried=["riego a mano"],
            tags=[ChallengeTag.WATER],
            location_checked=True,
            entity_type_checked=True,
            profile_facts=facts,
        )
    )
    memory.mark_playback_shown()
    memory.begin_turn("sí")
    memory.confirm_understanding()
    return memory


ENTITY = ProposedFact(field=ProfileField.ENTITY_TYPE, value="cooperative", quote="somos una cooperativa")
MEMBERS = ProposedFact(field=ProfileField.MEMBER_COUNT, value="350", quote="350 familias")
LOCATION = ProposedFact(field=ProfileField.STATED_LOCATION, value="Sullana", quote="en Sullana")
CROP = ProposedFact(field=ProfileField.ADDITIONAL_CROP, value="mango", quote="cultivamos mango")


def test_view_starts_from_the_registered_record(profiles):
    view = profiles.load_view(ME)
    assert view.current(ProfileField.ENTITY_TYPE) == "small producer association"
    assert view.attributes[0].provenance == Provenance.REGISTERED
    assert view.pending_review_count == 0


def test_unknown_producer_is_rejected(profiles):
    with pytest.raises(KeyError):
        profiles.load_view("P-NOPE")


def test_session_facts_override_only_for_this_exchange(profiles):
    view = profiles.load_view(ME, session_facts=[ENTITY])
    assert view.current(ProfileField.ENTITY_TYPE) == "cooperative"
    assert profiles.load_view(ME).current(ProfileField.ENTITY_TYPE) == "small producer association"


def test_commit_stays_invisible_until_review(profiles):
    profiles.commit_exchange(_confirmed([ENTITY, MEMBERS]))
    view = profiles.load_view(ME)
    assert view.current(ProfileField.ENTITY_TYPE) == "small producer association"
    assert view.current(ProfileField.MEMBER_COUNT) == "330"
    assert view.reviewed_episodes == []
    assert view.pending_review_count == 3


def test_approved_fact_and_episode_join_the_view_with_provenance(profiles):
    result = profiles.commit_exchange(_confirmed([ENTITY]))
    profiles.review_fact(ME, result.fact_ids[0], status=ReviewStatus.APPROVED, reviewer="irl")
    profiles.review_episode(ME, result.episode_id, status=ReviewStatus.APPROVED, reviewer="irl")
    view = profiles.load_view(ME)
    attribute = next(item for item in view.attributes if item.field == ProfileField.ENTITY_TYPE)
    assert (attribute.value, attribute.provenance) == ("cooperative", Provenance.REVIEWED)
    assert [episode.challenge for episode in view.reviewed_episodes] == ["sequía"]
    assert view.pending_review_count == 0


def test_rejected_fact_never_takes_effect(profiles):
    result = profiles.commit_exchange(_confirmed([ENTITY]))
    profiles.review_fact(ME, result.fact_ids[0], status=ReviewStatus.REJECTED, reviewer="irl")
    assert profiles.load_view(ME).current(ProfileField.ENTITY_TYPE) == "small producer association"


def test_correction_applies_the_reviewers_value_and_keeps_the_original(profiles):
    result = profiles.commit_exchange(_confirmed([MEMBERS]))
    fact = profiles.review_fact(ME, result.fact_ids[0], status=ReviewStatus.CORRECTED, reviewer="irl", corrected_value="340")
    assert (fact.value, fact.effective_value) == ("350", "340")
    assert profiles.load_view(ME).current(ProfileField.MEMBER_COUNT) == "340"


def test_a_correction_needs_a_value(profiles):
    result = profiles.commit_exchange(_confirmed([MEMBERS]))
    with pytest.raises(MemoryRuleError):
        profiles.review_fact(ME, result.fact_ids[0], status=ReviewStatus.CORRECTED, reviewer="irl")


def test_episode_correction_keeps_the_original(profiles):
    result = profiles.commit_exchange(_confirmed([]))
    episode = profiles.review_episode(
        ME, result.episode_id, status=ReviewStatus.CORRECTED, reviewer="irl", corrections={"challenge": "sequía severa"}
    )
    assert episode.challenge == "sequía severa"
    assert episode.original_values == {"challenge": "sequía"}


def test_scope_locked_facts_never_change_the_view_even_when_approved(profiles):
    result = profiles.commit_exchange(_confirmed([LOCATION, CROP]))
    for fact_id in result.fact_ids:
        profiles.review_fact(ME, fact_id, status=ReviewStatus.APPROVED, reviewer="irl")
    view = profiles.load_view(ME, session_facts=[LOCATION, CROP])
    assert view.registered.region == "Piura"
    assert view.registered.crops == ["banana"]
    assert view.values(ProfileField.STATED_LOCATION) == []
    assert view.values(ProfileField.ADDITIONAL_CROP) == []
    assert len(profiles.list_facts(ME)) == 2


def test_commit_requires_a_confirmed_understanding(profiles, memory):
    with pytest.raises(MemoryRuleError):
        profiles.commit_exchange(memory)


def test_commit_retry_creates_no_duplicates_and_does_not_undo_a_review(profiles):
    memory = _confirmed([ENTITY])
    result = profiles.commit_exchange(memory)
    profiles.review_episode(ME, result.episode_id, status=ReviewStatus.APPROVED, reviewer="irl")
    profiles.commit_exchange(memory)
    assert len(profiles.list_facts(ME)) == 1
    episodes = profiles.list_episodes(ME)
    assert len(episodes) == 1
    assert episodes[0].status == ReviewStatus.APPROVED


def test_fact_equal_to_the_current_value_is_not_stored(profiles):
    same = ProposedFact(field=ProfileField.MEMBER_COUNT, value="330", quote="350 familias")
    assert profiles.commit_exchange(_confirmed([same])).fact_ids == []


def _approve(profiles, fact_ids):
    for fact_id in fact_ids:
        profiles.review_fact(ME, fact_id, status=ReviewStatus.APPROVED, reviewer="irl")


def _member_fact(value):
    return ProposedFact(field=ProfileField.MEMBER_COUNT, value=value, quote="350 familias")


def test_a_newer_reviewed_value_supersedes_the_older_one_without_deleting_it(profiles):
    first = profiles.commit_exchange(_confirmed([_member_fact("350")], exchange_id="ex-1"))
    _approve(profiles, first.fact_ids)
    second = profiles.commit_exchange(_confirmed([_member_fact("360")], exchange_id="ex-2"))
    assert profiles.load_view(ME).current(ProfileField.MEMBER_COUNT) == "350"
    _approve(profiles, second.fact_ids)

    assert profiles.load_view(ME).current(ProfileField.MEMBER_COUNT) == "360"
    history = profiles.fact_history(ME, ProfileField.MEMBER_COUNT)
    assert [fact.value for fact in history] == ["350", "360"]
    assert history[0].superseded_by == history[1].fact_id
    assert history[0].superseded_at is not None
    assert history[1].superseded_by is None


def test_reviewing_out_of_order_still_keeps_the_newest_value(profiles):
    older = profiles.commit_exchange(_confirmed([_member_fact("350")], exchange_id="ex-1"))
    newer = profiles.commit_exchange(_confirmed([_member_fact("360")], exchange_id="ex-2"))
    _approve(profiles, newer.fact_ids)
    _approve(profiles, older.fact_ids)
    assert profiles.load_view(ME).current(ProfileField.MEMBER_COUNT) == "360"
    assert profiles.fact_history(ME, ProfileField.MEMBER_COUNT)[0].superseded_by == newer.fact_ids[0]


def test_rejecting_the_newest_value_restores_the_previous_one(profiles):
    older = profiles.commit_exchange(_confirmed([_member_fact("350")], exchange_id="ex-1"))
    newer = profiles.commit_exchange(_confirmed([_member_fact("360")], exchange_id="ex-2"))
    _approve(profiles, older.fact_ids + newer.fact_ids)
    profiles.review_fact(ME, newer.fact_ids[0], status=ReviewStatus.REJECTED, reviewer="irl")
    assert profiles.load_view(ME).current(ProfileField.MEMBER_COUNT) == "350"
    assert profiles.fact_history(ME, ProfileField.MEMBER_COUNT)[0].superseded_by is None


def test_multi_valued_facts_accumulate_instead_of_superseding(profiles):
    practice = lambda value, exchange_id: _confirmed(
        [ProposedFact(field=ProfileField.CURRENT_PRACTICE, value=value, quote="350 familias")], exchange_id=exchange_id
    )
    _approve(profiles, profiles.commit_exchange(practice("riego", "ex-1")).fact_ids)
    _approve(profiles, profiles.commit_exchange(practice("abono", "ex-2")).fact_ids)
    assert profiles.load_view(ME).values(ProfileField.CURRENT_PRACTICE) == ["riego", "abono"]


def test_valid_from_travels_from_the_conversation_to_the_view(profiles):
    fact = ProposedFact(field=ProfileField.ENTITY_TYPE, value="cooperative", quote="somos una cooperativa", valid_from="este año")
    session_view = profiles.load_view(ME, session_facts=[fact])
    assert next(item for item in session_view.attributes if item.field == ProfileField.ENTITY_TYPE).valid_from == "este año"
    result = profiles.commit_exchange(_confirmed([fact]))
    assert profiles.list_facts(ME)[0].valid_from == "este año"
    _approve(profiles, result.fact_ids)
    attribute = next(item for item in profiles.load_view(ME).attributes if item.field == ProfileField.ENTITY_TYPE)
    assert (attribute.value, attribute.valid_from) == ("cooperative", "este año")


def test_the_episode_carries_notes_and_pii_types_for_the_reviewer(profiles):
    memory = _confirmed([])
    memory.update_understanding(UnderstandingUpdate(notes=[SessionNote(text="Son muchas familias", quote="350 familias")]))
    memory.flag_pii(PiiFlag(turn=1, entity_types=["NAME", "PHONE"]))
    profiles.commit_exchange(memory)
    episode = profiles.list_episodes(ME)[0]
    assert [note.text for note in episode.notes] == ["Son muchas familias"]
    assert episode.pii_entity_types == ["NAME", "PHONE"]


def test_episodes_come_back_oldest_first(profiles):
    for exchange_id in ("zz-first", "aa-second"):
        profiles.commit_exchange(_confirmed([], exchange_id=exchange_id))
    assert [episode.exchange_id for episode in profiles.list_episodes(ME)] == ["zz-first", "aa-second"]
