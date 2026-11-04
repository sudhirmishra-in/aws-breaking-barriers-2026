"""Scope is enforced by tool shape and trusted context, not by the prompt."""

import json

import pytest
from strands import tool

from conftest import ME, OTHER
from producer_exchange.agent.phases import PHASE_SPECS
from producer_exchange.agent.tools import ALL_TOOLS, TURN_CONTEXT_KEY, TurnContext
from producer_exchange.memory.models import ChallengeTag, EvidenceSource, MemoryRuleError, Phase, WorkingMemory
from producer_exchange.sources.base import PeerQuery

_ALL_TAGS = [tag.value for tag in ChallengeTag]


class _Agent:
    def __init__(self):
        self.cancelled = False

    def cancel(self, **kwargs):
        self.cancelled = True


class _ToolContext:
    def __init__(self, context):
        self.invocation_state = {TURN_CONTEXT_KEY: context}
        self.agent = _Agent()


@pytest.fixture
def make_context(profiles, sources):
    def _make(producer_id=ME, phase=Phase.RETRIEVE):
        memory = WorkingMemory(exchange_id="ex-1", producer_id=producer_id, language="es", phase=phase)
        return TurnContext(memory, profiles.load_view(producer_id), profiles, sources)

    return _make


def _invoke(name, context, **kwargs):
    handler = ALL_TOOLS[name]._tool_func
    return handler(reasoning="test", tool_context=_ToolContext(context), **kwargs)


@pytest.mark.parametrize("name", ALL_TOOLS)
def test_no_tool_lets_the_model_supply_identity_or_location(name):
    properties = ALL_TOOLS[name].tool_spec["inputSchema"]["json"]["properties"]
    forbidden = {"producer_id", "account", "region", "region_id", "location", "country", "crop", "crops", "tool_context"}
    assert not forbidden & set(properties)


@pytest.mark.parametrize("name", ALL_TOOLS)
def test_every_tool_records_its_reasoning(name):
    assert "reasoning" in ALL_TOOLS[name].tool_spec["inputSchema"]["json"]["required"]


def test_every_phase_names_real_tools():
    for spec in PHASE_SPECS.values():
        assert set(spec.tools) <= set(ALL_TOOLS)


def _other_producer_ids(sources):
    ids = {OTHER, sources.producers.survey(OTHER).survey_id}
    ids |= {project.project_id for project in sources.producers.projects(OTHER)}
    return ids


def test_producer_record_returns_only_this_producer(make_context, sources):
    output = _invoke("get_producer_record", make_context())
    for foreign_id in _other_producer_ids(sources):
        assert foreign_id not in output
    refs = {item["source_ref"] for item in json.loads(output)}
    assert {project.project_id for project in sources.producers.projects(ME)} <= refs
    assert sources.producers.survey(ME).survey_id in refs


def test_producer_record_does_not_expose_certification(make_context):
    output = _invoke("get_producer_record", make_context()).lower()
    for term in ("certified", "last_audit", "cert-", "decertified"):
        assert term not in output


def test_regional_context_returns_only_own_region_and_own_crop(make_context):
    items = json.loads(_invoke("get_regional_context", make_context(), tags=_ALL_TAGS))
    refs = {item["source_ref"] for item in items}
    assert refs
    assert all("PE-PIU" in ref or ref == "RF-WB-BANANA" for ref in refs)


def test_empty_results_are_reported_as_no_data(make_context):
    output = _invoke("search_peer_examples", make_context(), tags=[ChallengeTag.HEALTH.value])
    assert json.loads(output) == {"status": "no_data"}


def test_peer_examples_exclude_own_and_already_funded_projects_and_hide_owner_ids(make_context, sources):
    context = make_context()
    output = _invoke("search_peer_examples", context, tags=_ALL_TAGS)
    items = json.loads(output)
    own_titles = {project.title for project in sources.producers.projects(ME)}
    assert items
    assert not any(item["fact"].split(".")[0] in own_titles for item in items)
    assert "producer_id" not in output
    assert "P-" not in " ".join(item["source_ref"] for item in items)
    assert "PRJ-" not in output


def test_peer_search_cannot_return_the_excluded_producer(sources):
    query = PeerQuery(tags=list(ChallengeTag), exclude_producer_id=ME, limit=100)
    labels = {case.organization_label for case in sources.peers.search(query)}
    assert sources.producers.get(ME).display_name not in labels


def test_extra_model_arguments_cannot_change_scope(make_context):
    spec = ALL_TOOLS["get_producer_record"].tool_spec["inputSchema"]["json"]
    assert "producer_id" not in spec["properties"]
    with pytest.raises(TypeError):
        _invoke("get_producer_record", make_context(), producer_id=OTHER)


@pytest.mark.parametrize(
    "name, phase, kwargs",
    [
        ("get_producer_record", Phase.CLARIFY, {}),
        ("get_regional_context", Phase.PLAYBACK, {"tags": _ALL_TAGS}),
        ("search_peer_examples", Phase.CLARIFY, {"tags": _ALL_TAGS}),
        ("retrieve_standards", Phase.PLAYBACK, {"tags": _ALL_TAGS}),
        ("confirm_understanding", Phase.CLARIFY, {}),
        ("submit_guidance", Phase.RETRIEVE, {"draft": None}),
        ("record_understanding", Phase.DRAFTED, {}),
    ],
)
def test_tools_refuse_to_run_outside_their_stage(make_context, name, phase, kwargs):
    context = make_context(phase=phase)
    with pytest.raises(MemoryRuleError, match="not available"):
        _invoke(name, context, **kwargs)
    assert context.memory.evidence == {}


def test_each_tool_marks_its_source_and_the_last_one_advances_the_stage(make_context):
    context = make_context()
    context.memory.confirmed_version = 0
    _invoke("get_producer_record", context)
    _invoke("get_regional_context", context, tags=["water"])
    _invoke("search_peer_examples", context, tags=["water"])
    assert context.memory.phase == Phase.RETRIEVE
    _invoke("retrieve_standards", context, tags=["water"])
    assert set(context.memory.retrieved_sources) == set(EvidenceSource)
    assert context.memory.phase == Phase.DRAFT
    assert context.context_is_stale
