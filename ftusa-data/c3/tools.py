"""The four Component 3 tools.

Two ways to bind the session producer (SCOPE-1). Neither lets the model supply it:

  make_tools(da)                       Strands @tool(context=True); reads
                                       tool_context.invocation_state["account_sk"],
                                       which the AgentCore entrypoint sets per request:
                                           agent(prompt, account_sk=payload["account_sk"])
  make_session_tools(da, account_sk)   Fallback: plain @tool functions closed over
                                       the session; build a fresh Agent per session.

The tool bodies are plain functions in this module (`impl_*`) so they are
tested without Strands. The Strands wrappers are thin and NOT RUN in the build
environment (Strands is not installable there).
"""
from __future__ import annotations

from .access import DataAccess, Session

# --------------------------------------------------------------------------- docstrings (become tool schemas)
DOC_RECORD = """Get the current producer's own record: profile, its Premium-funded projects, and its latest
household-survey summary (aggregated; null if the producer has no survey data).
The producer is taken from the session; you cannot look up another producer.

Args:
    include_all_survey_years: return every survey year instead of only the latest.
"""
DOC_SIMILAR = """Find peer examples: Premium projects other producers funded in response to a similar challenge.
Never returns the current producer's own projects. Crop and entity type come from the session producer.

Args:
    challenge: the challenge in the producer's own words (any language).
    tags: optional challenge tags to restrict to (ids from the 11-tag set).
    same_crop: prefer producers growing the same crop (relaxed automatically if too few matches).
    same_entity_type: prefer the same entity type (cooperative, smallholder, ...).
    top_k: number of results, 1-10.
"""
DOC_QUERY = """Bounded lookup across producers. Returns public, organization-level fields only.

Args:
    dataset: "projects" or "producers".
    filters: projects -> country, primary_tag, crop, status, start_year_from (needs country or primary_tag);
             producers -> country (required), primary_crop, entity_type.
    limit: required, 1-20.
"""
DOC_DESCRIBE = """Describe a dataset: grain, what it answers and cannot answer, coverage, and field meanings.

Args:
    name: dataset name, e.g. "projects", "producers", "survey_summaries".
"""


# --------------------------------------------------------------------------- plain implementations
def impl_get_producer_record(da: DataAccess, session: Session | None, include_all_survey_years: bool = False):
    return da.producer_record(session, include_all_survey_years)


def impl_find_similar_projects(da: DataAccess, session: Session | None, challenge: str, tags=None,
                               same_crop: bool = True, same_entity_type: bool = False, top_k: int = 5):
    return da.similar_projects(session, challenge, tags, same_crop, same_entity_type, top_k)


def impl_query(da: DataAccess, session: Session | None, dataset: str, filters: dict | None = None, limit: int | None = None):
    return da.query(session, dataset, filters, limit)


def impl_describe_dataset(da: DataAccess, name: str):
    return da.describe(name)


# --------------------------------------------------------------------------- Strands wrappers
def _session_from(tool_context) -> Session | None:
    state = getattr(tool_context, "invocation_state", None) or {}
    sk = state.get("account_sk")
    return Session(sk) if sk else None


def make_tools(da: DataAccess) -> list:
    """Strands tools reading the producer from invocation state (preferred)."""
    from strands import ToolContext, tool

    @tool(context=True)
    @_doc(DOC_RECORD)
    def get_producer_record(include_all_survey_years: bool = False, tool_context: ToolContext = None) -> dict:
        return impl_get_producer_record(da, _session_from(tool_context), include_all_survey_years)

    @tool(context=True)
    @_doc(DOC_SIMILAR)
    def find_similar_projects(challenge: str, tags: list[str] | None = None, same_crop: bool = True,
                              same_entity_type: bool = False, top_k: int = 5, tool_context: ToolContext = None) -> dict:
        return impl_find_similar_projects(da, _session_from(tool_context), challenge, tags, same_crop,
                                          same_entity_type, top_k)

    @tool(context=True)
    @_doc(DOC_QUERY)
    def query(dataset: str, filters: dict | None = None, limit: int | None = None,
              tool_context: ToolContext = None) -> dict:
        return impl_query(da, _session_from(tool_context), dataset, filters, limit)

    @tool
    @_doc(DOC_DESCRIBE)
    def describe_dataset(name: str) -> dict:
        return impl_describe_dataset(da, name)

    return [get_producer_record, find_similar_projects, query, describe_dataset]


def make_session_tools(da: DataAccess, account_sk: str) -> list:
    """Fallback: tools closed over one session (build a new Agent per session)."""
    from strands import tool

    s = Session(account_sk)

    @tool
    @_doc(DOC_RECORD)
    def get_producer_record(include_all_survey_years: bool = False) -> dict:
        return impl_get_producer_record(da, s, include_all_survey_years)

    @tool
    @_doc(DOC_SIMILAR)
    def find_similar_projects(challenge: str, tags: list[str] | None = None, same_crop: bool = True,
                              same_entity_type: bool = False, top_k: int = 5) -> dict:
        return impl_find_similar_projects(da, s, challenge, tags, same_crop, same_entity_type, top_k)

    @tool
    @_doc(DOC_QUERY)
    def query(dataset: str, filters: dict | None = None, limit: int | None = None) -> dict:
        return impl_query(da, s, dataset, filters, limit)

    @tool
    @_doc(DOC_DESCRIBE)
    def describe_dataset(name: str) -> dict:
        return impl_describe_dataset(da, name)

    return [get_producer_record, find_similar_projects, query, describe_dataset]


def _doc(text):
    """Set the docstring BEFORE @tool runs (decorators apply bottom-up), so Strands builds the schema from it."""
    def deco(f):
        f.__doc__ = text
        return f
    return deco


# --------------------------------------------------------------------------- local factory
def local_data_access(tables="out/tables") -> DataAccess:
    """DataAccess over the InMemoryStore (no AWS)."""
    from .catalog import Catalog
    from .items import build_all
    from .store_memory import InMemoryStore

    built = build_all(tables)
    return DataAccess(InMemoryStore(built), Catalog(stats=built["stats"]))
