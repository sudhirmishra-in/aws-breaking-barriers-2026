"""Component 3 tool functions, named and shaped like main's agent tools (agent/app/exchange/tools.py).

These are PLAIN functions, not Strands tools. The agent wraps each one in a @tool inside
build_tools(producer) and passes the trusted ProducerRef by closure, so the model never supplies
the producer. Docstrings for the model live on the agent's wrappers.

    main tool (model args)            this module
    get_my_history()                  get_my_history(producer)
    get_peer_examples(topic: str)     get_peer_examples(producer, topic)
    get_standards_clause(topic: str)  c4.tools.get_standards_clause(producer, topic)
    get_regional_evidence(topic)      not C3 (Component 5)

Results keep main's keys: get_my_history -> {synthetic, history[{period, note}]}; get_peer_examples ->
{kind, topic, status, note}. Both add cited detail on top.

Producer mapping: ProducerRef.producerId is looked up as an FTUSA account_sk, optionally through the JSON
map in FTUSA_PRODUCER_MAP ({producerId: account_sk}). A producer with no FTUSA record (e.g. the app's
SYN-P-00x demo accounts) gets an empty history and peer examples matched on its crop / entity type.

`query` and `describe_dataset` have no tool in main's agent; their impl_* functions stay for the
smoke script and tests only.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from .access import DataAccess, Session

DEFAULT_TABLES = Path(__file__).resolve().parents[1] / "out" / "tables"
TOPIC_CHARS = 200
PEER_TOP_K = 5

NOTE_PEERS_OK = ("Peer examples are other producers' Premium projects. Describe them as what others did, cite each "
                 "by its citation, and never present them as advice or as this producer's own record.")
NOTE_PEERS_NONE = "No comparable peer projects were found. Do not describe any peer outcome; say none was found."
NOTE_UNAVAILABLE = ("Peer examples are not available right now. Do not state any peer outcome. Tell the producer "
                    "this information is not available yet.")


# --------------------------------------------------------------------------- internal implementations
def impl_get_producer_record(da: DataAccess, session: Session | None, include_all_survey_years: bool = False):
    return da.producer_record(session, include_all_survey_years)


def impl_find_similar_projects(da: DataAccess, session: Session | None, challenge: str, tags=None,
                               same_crop: bool = True, same_entity_type: bool = False, top_k: int = 5):
    return da.similar_projects(session, challenge, tags, same_crop, same_entity_type, top_k)


def impl_query(da: DataAccess, session: Session | None, dataset: str, filters: dict | None = None, limit: int | None = None):
    return da.query(session, dataset, filters, limit)


def impl_describe_dataset(da: DataAccess, name: str):
    return da.describe(name)


# --------------------------------------------------------------------------- producer mapping
@lru_cache(maxsize=1)
def _producer_map() -> dict:
    p = os.environ.get("FTUSA_PRODUCER_MAP")
    return json.loads(Path(p).read_text()) if p and Path(p).exists() else {}


def session_for(da: DataAccess, producer) -> Session:
    """Trusted ProducerRef -> Session. Never uses anything the model wrote."""
    pid = getattr(producer, "producerId", None) or ""
    sk = _producer_map().get(pid, pid)
    if sk and da.store.get_producer(sk) is not None:
        return Session(sk)
    return Session(f"external:{pid}", crop=getattr(producer, "crop", None),
                   entity_type=getattr(producer, "entityType", None))


# --------------------------------------------------------------------------- agent-facing functions
def get_my_history(producer, *, da: DataAccess | None = None) -> dict:
    """main: get_my_history() -> {"synthetic": True, "history": [...]}"""
    try:
        da = da or default_data_access()
        rec = impl_get_producer_record(da, session_for(da, producer))
    except Exception:  # backend down: same shape as main's "no history"
        return {"synthetic": True, "history": [], "note": "Producer history is not available right now."}
    if "error" in rec:
        return {"synthetic": True, "history": [], "note": "No FTUSA record is linked to this producer."}
    history = []
    for p in rec["projects"]:
        period = (p.get("start_date") or "")[:4] or "undated"
        note = f"Premium project: {p['name']} ({p.get('status', 'status unknown')})."
        if p.get("primary_goal"):
            note += f" Goal: {p['primary_goal'][:300]}"
        history.append({"period": period, "note": note, "citation": p["citation"]})
    s = rec.get("survey")
    if s:
        history.append({"period": str(s["survey_year"]),
                        "note": f"Household survey summary (n={s['n_responses']}, aggregated).",
                        "citation": s["citation"]})
    history.sort(key=lambda h: h["period"])
    return {"synthetic": True, "history": history, "profile": rec["profile"], "survey": s,
            "coverage_notes": rec["coverage_notes"]}


def get_peer_examples(producer, topic: str, *, da: DataAccess | None = None) -> dict:
    """main: get_peer_examples(topic) -> {"kind": "peer_examples", "topic", "status", "note"}"""
    topic = " ".join((topic or "").split())[:TOPIC_CHARS]
    base = {"kind": "peer_examples", "topic": topic}
    if not topic:
        return base | {"status": "unavailable", "note": NOTE_UNAVAILABLE}
    try:
        da = da or default_data_access()
        r = impl_find_similar_projects(da, session_for(da, producer), topic, same_crop=True, top_k=PEER_TOP_K)
    except Exception:  # backend down: degrade to main's placeholder, never invent
        return base | {"status": "unavailable", "note": NOTE_UNAVAILABLE}
    if "error" in r:
        return base | {"status": "unavailable", "note": NOTE_UNAVAILABLE, "error": r["error"]}
    if not r["results"]:
        return base | {"status": "no_match", "note": NOTE_PEERS_NONE, "coverage_notes": r["coverage_notes"]}
    return base | {"status": "ok", "note": NOTE_PEERS_OK, "examples": r["results"],
                   "relaxed": r["relaxed"], "coverage_notes": r["coverage_notes"]}


# --------------------------------------------------------------------------- factories
def local_data_access(tables=DEFAULT_TABLES) -> DataAccess:
    """DataAccess over the InMemoryStore (no AWS)."""
    from .catalog import Catalog
    from .items import build_all
    from .store_memory import InMemoryStore

    built = build_all(tables)
    return DataAccess(InMemoryStore(built), Catalog(stats=built["stats"]))


@lru_cache(maxsize=1)
def default_data_access() -> DataAccess:
    """FTUSA_C3_BACKEND=aws -> DynamoDB + S3 Vectors (FTUSA_C3_TABLE_PREFIX, FTUSA_C3_VECTOR_BUCKET,
    FTUSA_C3_STATS, AWS_REGION; NOT RUN in the build environment). Otherwise the in-memory store over
    FTUSA_TABLES (default ftusa-data/out/tables)."""
    if os.environ.get("FTUSA_C3_BACKEND") == "aws":
        from .catalog import Catalog
        from .store_aws import DynamoS3Store

        store = DynamoS3Store(os.environ.get("FTUSA_C3_TABLE_PREFIX", "ftusa_c3_"),
                              os.environ.get("FTUSA_C3_VECTOR_BUCKET", "ftusa-c3-vectors"),
                              region=os.environ.get("AWS_REGION"))
        return DataAccess(store, Catalog.with_stats_file(Path(os.environ.get("FTUSA_C3_STATS", "catalog_stats.json"))))
    return local_data_access(os.environ.get("FTUSA_TABLES", DEFAULT_TABLES))
