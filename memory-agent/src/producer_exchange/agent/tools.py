"""The agent's tools: memory write path and scoped data reads.

Scope rule: no tool has a parameter for a producer ID, region or crop. Tools read those from the
`TurnContext` the service puts in `invocation_state`, which is never sent to the model.
"""

import json
from dataclasses import dataclass
from typing import Any

from strands import ToolContext, tool

from producer_exchange.agent.phases import next_phase
from producer_exchange.agent.rendering import SOURCE_NOUNS, localized
from producer_exchange.memory.models import (
    ChallengeTag,
    EvidenceItem,
    EvidenceSource,
    GuidanceDraft,
    MemoryRuleError,
    Phase,
    ProfileField,
    ProposedFact,
    SessionNote,
    UnderstandingUpdate,
    UpdateEffect,
    WorkingMemory,
)
from producer_exchange.memory.profile import ProfileRepository, ProfileView
from producer_exchange.sources.base import DataSources, PeerQuery

TURN_CONTEXT_KEY = "turn_context"


@dataclass
class TurnContext:
    """Server-side state for one turn. Tools mutate `memory`; the service persists it at the end."""

    memory: WorkingMemory
    view: ProfileView
    profiles: ProfileRepository
    sources: DataSources
    context_is_stale: bool = False

    def require_stage(self, name: str, *allowed_phases: Phase) -> None:
        if self.memory.phase not in allowed_phases:
            raise MemoryRuleError(f"{name} is not available at the {self.memory.phase.value} stage")

    def refresh_stage(self, tool_context: ToolContext) -> None:
        """End this model run after the current tools, so the next run sees memory as it now stands."""
        self.memory.phase = next_phase(self.memory)
        self.context_is_stale = True
        tool_context.agent.cancel(after_current_tools=True)


def _context(tool_context: ToolContext) -> TurnContext:
    return tool_context.invocation_state[TURN_CONTEXT_KEY]


def _as_json(items: list[EvidenceItem]) -> str:
    return json.dumps([item.model_dump(mode="json") for item in items], ensure_ascii=False)


def _finish_retrieval(context: TurnContext, tool_context: ToolContext, source: EvidenceSource) -> None:
    context.memory.mark_retrieved(source)
    if next_phase(context.memory) != context.memory.phase:
        context.refresh_stage(tool_context)


@tool(context=True)
def record_understanding(
    reasoning: str,
    tool_context: ToolContext,
    challenge: str | None = None,
    onset: str | None = None,
    severity: str | None = None,
    actions_tried: list[str] | None = None,
    tags: list[ChallengeTag] | None = None,
    producer_quotes: list[str] | None = None,
    notes: list[SessionNote] | None = None,
    location_checked: bool | None = None,
    entity_type_checked: bool | None = None,
    profile_facts: list[ProposedFact] | None = None,
) -> str:
    """Save what the producer has told you. Omitted fields keep their current value.

    Args:
        reasoning: One sentence on why you are saving this. Kept for the audit log.
        challenge: The challenge in terms close to the producer's own words, in their language.
        onset: When it started.
        severity: How severe it is.
        actions_tried: What they have already tried. Omit this until they have answered. Use an empty list
            only if they said they have tried nothing.
        tags: The challenge tags that best match what they described.
        producer_quotes: Short exact quotes from the producer that capture the challenge.
        notes: Useful details the producer stated that fit no other field, each with their exact words.
        location_checked: True once the producer has confirmed or corrected their location.
        entity_type_checked: True once the producer has confirmed or corrected their entity type.
        profile_facts: Changes to their profile that they stated. Record only what differs from or adds to
            the profile, each with their exact words. Write entity_type in English and member_count as digits.
            Set valid_from if they said when it became true.
    """
    context = _context(tool_context)
    context.require_stage("record_understanding", Phase.CLARIFY, Phase.PLAYBACK)
    effect = context.memory.update_understanding(
        UnderstandingUpdate(
            challenge=challenge,
            onset=onset,
            severity=severity,
            actions_tried=actions_tried,
            tags=tags,
            producer_quotes=producer_quotes,
            notes=notes,
            location_checked=location_checked,
            entity_type_checked=entity_type_checked,
            profile_facts=profile_facts,
        )
    )
    if effect == UpdateEffect.UNCHANGED:
        return "Nothing new to save. Continue with the conversation."
    if effect == UpdateEffect.RECORDED:
        return "Saved. Continue with the conversation."
    context.refresh_stage(tool_context)
    return "Saved."


@tool(context=True)
def confirm_understanding(reasoning: str, tool_context: ToolContext) -> str:
    """Record that the producer confirmed your playback without changes.

    Args:
        reasoning: One sentence on what the producer said that confirms it. Kept for the audit log.
    """
    context = _context(tool_context)
    context.require_stage("confirm_understanding", Phase.PLAYBACK)
    context.memory.confirm_understanding()
    context.view = context.profiles.load_view(context.memory.producer_id, context.memory.confirmed_facts())
    context.refresh_stage(tool_context)
    return "Confirmed."


@tool(context=True)
def get_producer_record(reasoning: str, tool_context: ToolContext) -> str:
    """Read this producer's own Premium projects, survey summary and reviewed past exchanges.

    Args:
        reasoning: One sentence on why you are reading this. Kept for the audit log.
    """
    context = _context(tool_context)
    context.require_stage("get_producer_record", Phase.RETRIEVE)
    memory, record = context.memory, context.view.registered
    producers = context.sources.producers
    source = EvidenceSource.PRODUCER_RECORD
    noun = lambda key: localized(SOURCE_NOUNS[key], memory.language)
    items = []
    for project in producers.projects(record.producer_id):
        fact = f"{project.year}: {project.title}. {project.description} Status: {project.status}."
        if project.outcome_note:
            fact += f" Note: {project.outcome_note}"
        items.append(memory.register_evidence(source, project.project_id, f"{noun('premium')}: {project.title}", fact))
    survey = producers.survey(record.producer_id)
    if survey is not None:
        fact = (
            f"{survey.year} survey, {survey.respondents} respondents. Top challenges: "
            f"{', '.join(survey.top_reported_challenges)}. Metrics: {json.dumps(survey.metrics)}."
        )
        items.append(memory.register_evidence(source, survey.survey_id, f"{noun('survey')} {survey.year}", fact))
    for episode in context.view.reviewed_episodes:
        fact = f"Earlier reviewed conversation: {episode.challenge}. Tried: {', '.join(episode.actions_tried) or 'nothing'}."
        items.append(memory.register_evidence(source, episode.episode_id, noun("past_exchange"), fact))
    _finish_retrieval(context, tool_context, source)
    return _as_json(items)


@tool(context=True)
def get_regional_context(reasoning: str, tags: list[ChallengeTag], tool_context: ToolContext) -> str:
    """Read open-data facts for this producer's region and crop, filtered by challenge tags.

    Args:
        reasoning: One sentence on why you are reading this. Kept for the audit log.
        tags: The challenge tags to match.
    """
    context = _context(tool_context)
    context.require_stage("get_regional_context", Phase.RETRIEVE)
    record = context.view.registered
    source = EvidenceSource.REGIONAL
    items = [
        context.memory.register_evidence(
            source,
            fact.source_id,
            fact.dataset,
            f"{fact.metric}: {fact.value}",
            {"period": fact.period, "as_of": fact.as_of},
        )
        for fact in context.sources.regional.facts(record.region_id, record.crops, tags)
    ]
    _finish_retrieval(context, tool_context, source)
    return _as_json(items) if items else json.dumps({"status": "no_data"})


@tool(context=True)
def search_peer_examples(reasoning: str, tags: list[ChallengeTag], tool_context: ToolContext) -> str:
    """Find projects comparable organizations funded for similar challenges.

    Args:
        reasoning: One sentence on why you are searching. Kept for the audit log.
        tags: The challenge tags to match.
    """
    context = _context(tool_context)
    context.require_stage("search_peer_examples", Phase.RETRIEVE)
    record = context.view.registered
    own_titles = [project.title for project in context.sources.producers.projects(record.producer_id)]
    cases = context.sources.peers.search(
        PeerQuery(
            tags=tags,
            exclude_producer_id=record.producer_id,
            crops=record.crops,
            country=record.country,
            entity_type=context.view.current(ProfileField.ENTITY_TYPE),
            exclude_titles=own_titles,
        )
    )
    source = EvidenceSource.PEER_CASE
    items = [
        context.memory.register_evidence(
            source,
            case.case_id,
            f"{case.organization_label or localized(SOURCE_NOUNS['peer'], context.memory.language)} ({case.country})",
            f"{case.title}. {case.description}",
            case.model_dump(mode="json", include={"entity_type", "crops", "year", "status", "amount_usd", "outcome_note"}),
        )
        for case in cases
    ]
    _finish_retrieval(context, tool_context, source)
    return _as_json(items) if items else json.dumps({"status": "no_data"})


@tool(context=True)
def retrieve_standards(reasoning: str, tags: list[ChallengeTag], tool_context: ToolContext) -> str:
    """Find certification standard clauses related to challenge tags.

    Args:
        reasoning: One sentence on why you are searching. Kept for the audit log.
        tags: The challenge tags to match.
    """
    context = _context(tool_context)
    context.require_stage("retrieve_standards", Phase.RETRIEVE, Phase.DRAFT)
    source = EvidenceSource.STANDARD
    items = [
        context.memory.register_evidence(
            source,
            clause.clause_id,
            f"{clause.standard} {clause.clause_id}",
            clause.localized_text.get(context.memory.language, clause.text),
            {"section": clause.section},
        )
        for clause in context.sources.standards.search(tags)
    ]
    _finish_retrieval(context, tool_context, source)
    return _as_json(items) if items else json.dumps({"status": "no_data"})


@tool(context=True)
def submit_guidance(reasoning: str, draft: GuidanceDraft, tool_context: ToolContext) -> str:
    """Submit the draft response. Every citation must be an evidence ID from this conversation.

    Args:
        reasoning: One sentence on how you selected these claims. Kept for the audit log.
        draft: The structured draft.
    """
    context = _context(tool_context)
    context.require_stage("submit_guidance", Phase.DRAFT)
    # Strands validates nested models against the schema, then passes them on as plain dicts.
    context.memory.store_draft(GuidanceDraft.model_validate(draft))
    context.refresh_stage(tool_context)
    return "Draft saved."


ALL_TOOLS: dict[str, Any] = {
    "record_understanding": record_understanding,
    "confirm_understanding": confirm_understanding,
    "get_producer_record": get_producer_record,
    "get_regional_context": get_regional_context,
    "search_peer_examples": search_peer_examples,
    "retrieve_standards": retrieve_standards,
    "submit_guidance": submit_guidance,
}
