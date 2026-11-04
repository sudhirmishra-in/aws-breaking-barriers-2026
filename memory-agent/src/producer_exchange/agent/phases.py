"""The conversation workflow, declared in one place.

To add a stage (VERIFY, PRESENT, ASK_CONSENT and so on):
  1. add a value to `Phase`,
  2. add a branch to `next_phase` that derives it from memory,
  3. add a `PhaseSpec` naming its prompt, tools and the memory it reads.
"""

from dataclasses import dataclass
from enum import StrEnum

from producer_exchange.memory.models import EvidenceSource, Phase, WorkingMemory

REQUIRED_SOURCES = frozenset(
    {
        EvidenceSource.PRODUCER_RECORD,
        EvidenceSource.REGIONAL,
        EvidenceSource.PEER_CASE,
        EvidenceSource.STANDARD,
    }
)


class ContextSection(StrEnum):
    """Each section is a projection of memory that a stage can choose to read."""

    PROFILE = "profile"
    PAST_EPISODES = "past_episodes"
    UNDERSTANDING = "understanding"
    EVIDENCE = "evidence"
    DRAFT = "draft"


@dataclass(frozen=True)
class PhaseSpec:
    phase: Phase
    instructions: str
    tools: tuple[str, ...]
    context: tuple[ContextSection, ...]
    # True: the model's final text is the reply to the producer. False: a silent stage that must advance.
    speaks: bool


def next_phase(memory: WorkingMemory) -> Phase:
    """Derive the stage from memory, so the workflow state can never disagree with the data."""
    if memory.draft is not None:
        return Phase.DRAFTED
    if memory.is_confirmed:
        if REQUIRED_SOURCES <= set(memory.retrieved_sources):
            return Phase.DRAFT
        return Phase.RETRIEVE
    if memory.understanding.missing_slots():
        return Phase.CLARIFY
    return Phase.PLAYBACK


_CLARIFY = """\
You are at the listening stage. Let the producer frame the challenge in their own words, and do not suggest \
causes or categories they have not raised.

If their latest message contains details that <working_memory> does not show yet, save them with \
record_understanding first. Everything shown there, including quotes and notes, is already saved, so never save \
it again. A useful detail that fits no field goes in notes. Then ask one or two short follow-up questions about \
the slots listed as missing. For location_checked and entity_type_checked, ask them to confirm the location and \
entity type shown in <producer_profile>. If they state something different or new, record it in profile_facts \
with their exact words."""

_PLAYBACK = """\
Everything needed is recorded. Play it back so the producer can correct it.

If <working_memory> says awaiting_confirmation is false, restate the understanding in a short paragraph covering \
the challenge, timing, severity, what they tried, location and entity type, then ask whether it is right.

If awaiting_confirmation is true, read their latest message. If they corrected anything, save it with \
record_understanding. If they confirmed it without changes, call confirm_understanding."""

_RETRIEVE = """\
The producer confirmed the understanding. This stage is silent: write nothing to the producer. Call \
get_producer_record, get_regional_context, search_peer_examples and retrieve_standards, once each, using the \
challenge tags that best match the confirmed understanding."""

_DRAFT = """\
This stage is silent: write nothing to the producer. Call submit_guidance with a draft built only from \
<evidence>, written in the producer's language.

Select the two or three insights about what the data shows for this producer's crop and region that matter most \
to the challenge they described, and one or two peer examples of what comparable organizations did. Producers \
read this on a phone, so leave out anything that does not help with this challenge. Make the draft specific to \
this producer: use their own history, and do not present something they already tried as new. Each claim cites the evidence behind it by ID, and the standard \
clauses it relates to. State facts and precedents as information for their own decision, never as instructions. \
If the evidence does not support something they need, list it in evidence_gaps instead of filling it in. Call \
retrieve_standards first if you need clauses that are not in <evidence>."""

_DRAFTED = """\
The draft in <draft> has been shown to the producer. Answer their follow-up questions using only <draft> and \
<evidence>. If they ask for something those do not cover, say so plainly."""


PHASE_SPECS: dict[Phase, PhaseSpec] = {
    Phase.CLARIFY: PhaseSpec(
        phase=Phase.CLARIFY,
        instructions=_CLARIFY,
        tools=("record_understanding",),
        context=(ContextSection.PROFILE, ContextSection.PAST_EPISODES, ContextSection.UNDERSTANDING),
        speaks=True,
    ),
    Phase.PLAYBACK: PhaseSpec(
        phase=Phase.PLAYBACK,
        instructions=_PLAYBACK,
        tools=("record_understanding", "confirm_understanding"),
        context=(ContextSection.PROFILE, ContextSection.UNDERSTANDING),
        speaks=True,
    ),
    Phase.RETRIEVE: PhaseSpec(
        phase=Phase.RETRIEVE,
        instructions=_RETRIEVE,
        tools=("get_producer_record", "get_regional_context", "search_peer_examples", "retrieve_standards"),
        context=(ContextSection.PROFILE, ContextSection.UNDERSTANDING),
        speaks=False,
    ),
    Phase.DRAFT: PhaseSpec(
        phase=Phase.DRAFT,
        instructions=_DRAFT,
        tools=("retrieve_standards", "submit_guidance"),
        context=(ContextSection.PROFILE, ContextSection.UNDERSTANDING, ContextSection.EVIDENCE),
        speaks=False,
    ),
    Phase.DRAFTED: PhaseSpec(
        phase=Phase.DRAFTED,
        instructions=_DRAFTED,
        tools=(),
        context=(ContextSection.PROFILE, ContextSection.DRAFT, ContextSection.EVIDENCE),
        speaks=True,
    ),
}
