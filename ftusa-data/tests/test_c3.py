"""Component 3 acceptance + scope tests on the InMemory backend.

Needs Stage A output in out/ (python -m ftusa_data.run --raw ... --out out), or
set C3_TABLES to another tables folder.
"""
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from c3 import load
from c3.access import MAX_LIMIT, PUBLIC_PRODUCER_FIELDS, PUBLIC_PROJECT_FIELDS, Session
from c3.catalog import Catalog
from c3.tools import (impl_describe_dataset, impl_find_similar_projects, impl_get_producer_record, impl_query,
                      local_data_access)

ROOT = Path(__file__).resolve().parents[1]
TABLES = Path(os.environ.get("C3_TABLES", ROOT / "out" / "tables"))
REVIEW = TABLES.parent / "review"
pytestmark = pytest.mark.skipif(not (TABLES / "producers" / "producers.csv").exists(), reason="run Stage A first")


@pytest.fixture(scope="module")
def da():
    return local_data_access(TABLES)


@pytest.fixture(scope="module")
def ids():
    p = pd.read_csv(TABLES / "producers" / "producers.csv")
    c = pd.read_csv(REVIEW / "scenario_candidates.csv")
    return {"with_survey": c[c.has_survey].iloc[0].account_sk, "without_survey": c[~c.has_survey].iloc[0].account_sk,
            "all": list(p.account_sk)}


def walk(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k, v
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)


def all_citations(o):
    return [v for k, v in walk(o) if k == "citation"]


# ---------------------------------------------------------------- ACC-1
def test_record_with_survey(da, ids):
    r = impl_get_producer_record(da, Session(ids["with_survey"]))
    assert r["profile"]["citation"]["source_id"] == ids["with_survey"]
    assert r["projects"] and all(p["citation"]["source_id"] == p["project_id"] for p in r["projects"])
    s = r["survey"]
    assert s and s["n_responses"] >= 10 and s["citation"]["source_type"] == "survey_summary"
    assert all(m["n"] >= 10 for m in s["metrics"].values())  # small-n suppressed upstream


def test_record_without_survey_is_not_an_error(da, ids):
    r = impl_get_producer_record(da, Session(ids["without_survey"]))
    assert "error" not in r and r["survey"] is None and r["projects"]
    assert any("No household survey" in n for n in r["coverage_notes"])


def test_record_needs_session(da):
    assert impl_get_producer_record(da, None)["error"] == "no_session_producer"
    assert impl_get_producer_record(da, Session("NOPE"))["error"] == "no_session_producer"


def test_all_survey_years(da, ids):
    r = impl_get_producer_record(da, Session(ids["with_survey"]), include_all_survey_years=True)
    assert isinstance(r["survey"], list) and len(r["survey"]) >= 1


# ---------------------------------------------------------------- ACC-2
def test_similar_projects_spanish_query(da, ids):
    me = ids["with_survey"]
    r = impl_find_similar_projects(da, Session(me), "bombeo solar de agua", top_k=5)
    assert 1 <= len(r["results"]) <= 5
    for x in r["results"]:
        assert x["citation"]["source_type"] == "peer_project"
        assert set(x) <= set(PUBLIC_PROJECT_FIELDS) | {"citation", "similarity"}


def test_similar_projects_finds_the_solar_pump_project(da, ids):
    r = impl_find_similar_projects(da, Session(ids["with_survey"]), "bombeo solar de agua", same_crop=False, top_k=3)
    assert any("solar" in (x["name"] + x.get("description", "")).lower() for x in r["results"])


def test_similar_projects_bounds_and_validation(da, ids):
    s = Session(ids["with_survey"])
    assert impl_find_similar_projects(da, s, "water", top_k=50)["error"] == "bad_top_k"
    assert impl_find_similar_projects(da, s, "water", tags=["waste"])["error"] == "unknown_tag"
    assert impl_find_similar_projects(da, s, "  ")["error"] == "empty_challenge"


def test_similar_projects_never_returns_test_or_pii_rows(da, ids):
    p = pd.read_csv(TABLES / "premium_projects" / "premium_projects.csv")
    bad = set(p[p.is_test_record | p.pii_flag | ~p.is_peer_eligible].project_id)
    for q in ["clean water project", "lorem ipsum", "test project", "reforestation", "solar"]:
        r = impl_find_similar_projects(da, Session(ids["with_survey"]), q, same_crop=False, top_k=10)
        assert not {x["project_id"] for x in r["results"]} & bad


# ---------------------------------------------------------------- ACC-3
def test_query_peru_water(da, ids):
    r = impl_query(da, Session(ids["with_survey"]), "projects", {"country": "Peru", "primary_tag": "water"}, 5)
    assert len(r["results"]) <= 5
    assert all(x["country"] == "Peru" and x["challenge_tags"][0] == "water" for x in r["results"])


@pytest.mark.parametrize("dataset,filters,limit,code", [
    ("projects", {"country": "Peru"}, None, "bad_limit"),
    ("projects", {"country": "Peru"}, MAX_LIMIT + 1, "bad_limit"),
    ("projects", {"category": "Water"}, 5, "unknown_filter"),
    ("projects", {"crop": "coffee"}, 5, "needs_indexed_filter"),
    ("projects", {"primary_tag": "waste"}, 5, "unknown_tag"),
    ("producers", {"primary_crop": "coffee"}, 5, "needs_indexed_filter"),
    ("surveys", {"country": "Peru"}, 5, "unknown_dataset"),
    ("producers", {"country": "Peru", "account_sk": "X"}, 5, "unknown_filter"),
])
def test_query_rejections(da, ids, dataset, filters, limit, code):
    assert impl_query(da, Session(ids["with_survey"]), dataset, filters, limit)["error"] == code


def test_query_by_tag_and_crop(da, ids):
    r = impl_query(da, Session(ids["with_survey"]), "projects", {"primary_tag": "water", "crop": "coffee"}, 10)
    assert r["results"] and all(x["crop"] == "coffee" for x in r["results"])


def test_query_producers_public_fields_only(da, ids):
    r = impl_query(da, Session(ids["with_survey"]), "producers", {"country": "Colombia", "primary_crop": "coffee"}, 20)
    assert r["results"]
    for x in r["results"]:
        assert set(x) <= set(PUBLIC_PRODUCER_FIELDS) | {"citation"}


# ---------------------------------------------------------------- ACC-4
def test_describe_dataset(da):
    d = impl_describe_dataset(da, "projects")
    assert d["fields"]["reason"] and "cannot_answer" in d and "{" not in d["coverage"]
    assert impl_describe_dataset(da, "nope")["error"] == "no_such_dataset"


def test_catalog_fields_exist_in_items():
    from c3.items import ProducerItem, ProjectItem, SurveyItem

    c = Catalog()
    attrs = {"producers": set(ProducerItem.model_fields), "projects": set(ProjectItem.model_fields),
             "survey_summaries": set(SurveyItem.model_fields)}
    for name in c.names():
        missing = set(c.field_names(name)) - attrs[name]
        assert not missing, (name, missing)


def test_prompt_summary_is_small(da):
    s = da.catalog.prompt_summary()
    assert len(s) < 2000 and all(n in s for n in da.catalog.names())


# ---------------------------------------------------------------- ACC-5 scope (SCOPE-5)
def test_scope_pairs(da):
    pairs = pd.read_csv(REVIEW / "scope_test_pairs.csv")
    assert len(pairs) > 0
    for a, b in zip(pairs.session_account_sk, pairs.other_account_sk):
        sa = Session(a)
        rec = impl_get_producer_record(da, sa)
        blob = json.dumps(rec)
        assert b not in blob, "own record leaks another producer"
        assert all(p["citation"]["source_id"] in {x["project_id"] for x in rec["projects"]} for p in rec["projects"])
        peers = impl_find_similar_projects(da, sa, "water shortage and drought", same_crop=False, top_k=10)
        q1 = impl_query(da, sa, "projects", {"country": rec["profile"].get("country", "Colombia")}, 20)
        q2 = impl_query(da, sa, "producers", {"country": rec["profile"].get("country", "Colombia")}, 20)
        own_projects = {x["project_id"] for x in rec["projects"]}
        for out in (peers, q1, q2):
            s = json.dumps(out)
            assert a not in s and b not in s, "account_sk exposed in cross-producer output"
            assert not {x.get("project_id") for x in out.get("results", [])} & own_projects, "caller's projects returned"
        assert rec["profile"]["display_id"] not in {x["display_id"] for x in q2["results"]}, "caller in directory"


def test_scope_cannot_be_overridden_by_arguments(da, ids):
    """The model can only pass the documented arguments; extra IDs are not parameters at all."""
    import inspect

    from c3 import tools

    for f in (tools.impl_get_producer_record, tools.impl_find_similar_projects, tools.impl_query):
        params = set(inspect.signature(f).parameters) - {"da", "session"}
        assert not params & {"account_sk", "producer_id", "location", "region"}, f.__name__
    # an injected ID inside filters is rejected
    r = impl_query(da, Session(ids["with_survey"]), "projects", {"country": "Peru", "account_sk": ids["without_survey"]}, 5)
    assert r["error"] == "unknown_filter"


def test_every_tool_call_is_logged_with_citations(da, ids):
    n = len(da.call_log)
    impl_get_producer_record(da, Session(ids["with_survey"]))
    last = da.call_log[-1]
    assert len(da.call_log) == n + 1 and last["tool"] == "get_producer_record" and last["citation_ids"]


# ---------------------------------------------------------------- ACC-6 load (dry-run)
def test_load_dry_run_is_idempotent(tmp_path):
    m1 = load.main(["--tables", str(TABLES), "--dry-run", "--dump", str(tmp_path / "a")])
    m2 = load.main(["--tables", str(TABLES), "--dry-run", "--dump", str(tmp_path / "b")])
    assert m1["load_id"] == m2["load_id"]
    for f in ("producers.jsonl", "projects.jsonl", "survey_summaries.jsonl", "vectors.jsonl"):
        assert (tmp_path / "a" / f).read_text() == (tmp_path / "b" / f).read_text()
    assert all(v["rows_rejected"] == 0 for v in m1["tables"].values())


def test_dynamo_items_are_sparse_and_typed(tmp_path):
    load.main(["--tables", str(TABLES), "--dry-run", "--dump", str(tmp_path)])
    rows = [json.loads(l) for l in (tmp_path / "projects.jsonl").read_text().splitlines()]
    for r in rows:
        assert ("gsi_country" in r) == r["is_peer_eligible"], "GSI attrs only on peer-eligible items"
        assert None not in r.values() and "" not in r.values()
    vec = [json.loads(l) for l in (tmp_path / "vectors.jsonl").read_text().splitlines()]
    assert len(vec) == sum(r["is_peer_eligible"] for r in rows)
    assert all({"account_sk", "crop", "primary_tag", "load_id"} <= set(v["metadata"]) for v in vec)
