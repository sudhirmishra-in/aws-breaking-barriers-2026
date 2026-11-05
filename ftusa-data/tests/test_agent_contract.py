"""Contract with main's agent (agent/app/exchange/tools.py::build_tools), read with AST so it needs no Strands.

For every agent tool we implement: our function is named the same, takes the trusted producer first and then
exactly the model arguments main's tool takes, and returns every key main's placeholder returns.
"""
import ast
import inspect
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from c3 import tools as c3tools
from c4 import tools as c4tools

ROOT = Path(__file__).resolve().parents[1]
MAIN_TOOLS = ROOT.parent / "agent" / "app" / "exchange" / "tools.py"
TABLES = Path(os.environ.get("C3_TABLES", ROOT / "out" / "tables"))
CLAUSES = ROOT / "out" / "standards" / "standard_clauses.jsonl"
OURS = {"get_my_history": c3tools.get_my_history, "get_peer_examples": c3tools.get_peer_examples,
        "get_standards_clause": c4tools.get_standards_clause}
NOT_OURS = {"get_regional_evidence", "get_environmental_context"}  # Component 5
DEMO = SimpleNamespace(producerId="SYN-P-001", entityType="cooperative", location="x", crop="coffee")

pytestmark = pytest.mark.skipif(not MAIN_TOOLS.exists(), reason="agent/ not in this checkout")


def main_tools() -> dict[str, list[str]]:
    tree = ast.parse(MAIN_TOOLS.read_text())
    build = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "build_tools")
    return {n.name: [a.arg for a in n.args.args] for n in build.body
            if isinstance(n, ast.FunctionDef) and any(ast.unparse(d) == "tool" for d in n.decorator_list)}


def model_params(f) -> list[str]:
    ps = list(inspect.signature(f).parameters.values())
    assert ps[0].name == "producer", f.__name__
    return [p.name for p in ps[1:] if p.kind is p.POSITIONAL_OR_KEYWORD]


def test_every_main_tool_is_covered():
    assert set(main_tools()) <= set(OURS) | NOT_OURS, sorted(set(main_tools()) - set(OURS) - NOT_OURS)


@pytest.mark.parametrize("name", sorted(OURS))
def test_same_name_and_model_args(name):
    m = main_tools()
    assert name in m, f"{name} is not an agent tool on main"
    assert model_params(OURS[name]) == m[name]


@pytest.fixture(scope="module")
def main_module():
    pytest.importorskip("pydantic")
    roots = [str(MAIN_TOOLS.parents[1]), str(ROOT.parent)]  # agent/app, and the repo root for external_data (C5)
    sys.path[:0] = roots
    try:
        from exchange import tools
    except ModuleNotFoundError as e:  # C5's ingest dependencies (shapely, boto3) are optional here
        pytest.skip(f"agent tools not importable here: {e}")
    finally:
        del sys.path[:len(roots)]
    return tools


@pytest.mark.skipif(not (TABLES.exists() and CLAUSES.exists()), reason="run Stage A first")
def test_results_keep_main_keys(main_module):
    ref = main_module.ProducerRef(producerId="SYN-P-001", entityType="cooperative", location="x", crop="coffee")
    placeholder = main_module.evidence_unavailable("x", "water")
    da, sa = c3tools.local_data_access(TABLES), c4tools.local_standards_access(CLAUSES)
    h = c3tools.get_my_history(ref, da=da)
    assert set(main_module.producer_history(ref)) <= set(h) and isinstance(h["history"], list)
    for r, kind in ((c3tools.get_peer_examples(ref, "water for irrigation", da=da), "peer_examples"),
                    (c4tools.get_standards_clause(ref, "pesticide storage", sa=sa), "standards")):
        assert set(placeholder) <= set(r) and r["kind"] == kind and r["status"] == "ok"


@pytest.mark.skipif(not TABLES.exists(), reason="run Stage A first")
def test_demo_producer_outside_ftusa_data():
    da = c3tools.local_data_access(TABLES)
    h = c3tools.get_my_history(DEMO, da=da)
    assert h["history"] == [] and h["synthetic"] is True
    r = c3tools.get_peer_examples(DEMO, "drought and water shortage", da=da)
    assert r["status"] == "ok" and r["examples"]
    assert all(e.get("crop") == "coffee" for e in r["examples"]) or "crop" in r["relaxed"]


@pytest.mark.skipif(not TABLES.exists(), reason="run Stage A first")
def test_ftusa_producer_history_and_peer_exclusion():
    da = c3tools.local_data_access(TABLES)
    sk = next(p["account_sk"] for p in da.store.producers.values() if p.get("project_count", 0) >= 1)
    me = SimpleNamespace(producerId=sk, entityType="cooperative", location="x", crop="coffee")
    h = c3tools.get_my_history(me, da=da)
    assert h["history"] and all({"period", "note", "citation"} <= set(x) for x in h["history"])
    own = {p["project_id"] for p in da.store.list_projects(sk, 100)}
    r = c3tools.get_peer_examples(me, "water", da=da)
    assert not own & {e["project_id"] for e in r.get("examples", [])}


@pytest.mark.skipif(not TABLES.exists(), reason="run Stage A first")
def test_empty_topic_and_backend_failure():
    da = c3tools.local_data_access(TABLES)
    assert c3tools.get_peer_examples(DEMO, "  ", da=da)["status"] == "unavailable"

    class Boom:
        def __getattr__(self, _):
            raise RuntimeError("ddb down")

    bad = SimpleNamespace(store=Boom())
    assert c3tools.get_peer_examples(DEMO, "water", da=bad)["status"] == "unavailable"
    assert c3tools.get_my_history(DEMO, da=bad)["history"] == []
