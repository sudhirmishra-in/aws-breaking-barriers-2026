"""export_lambda.py: the JSON bundles the API Lambda imports (backend/src/data/ftusa)."""
import json
from pathlib import Path

import pytest

import export_lambda as ex

ROOT = Path(__file__).resolve().parents[1]
TABLES, CLAUSES = ROOT / "out" / "tables", ROOT / "out" / "standards" / "standard_clauses.jsonl"
COMMITTED = ROOT.parent / "backend" / "src" / "data" / "ftusa"
pytestmark = pytest.mark.skipif(not (TABLES.exists() and CLAUSES.exists()), reason="run Stage A first")


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    d = tmp_path_factory.mktemp("bundles")
    ex.run(d, TABLES, CLAUSES)
    return d


def load(d, name):
    return json.loads((d / name).read_text(encoding="utf-8"))


def test_deterministic(out, tmp_path):
    ex.run(tmp_path, TABLES, CLAUSES)
    for f in ("ftusa_producers.json", "ftusa_projects.json", "ftusa_surveys.json", "standard_clauses.json", "manifest.json"):
        assert (out / f).read_bytes() == (tmp_path / f).read_bytes(), f


def test_committed_bundles_are_current(out):
    """The bundles committed for the Lambda must equal a fresh export (rerun export_lambda.py after a pipeline change)."""
    if not COMMITTED.exists():
        pytest.skip("backend/ not in this checkout")
    for f in ("ftusa_producers.json", "ftusa_projects.json", "ftusa_surveys.json", "standard_clauses.json", "manifest.json"):
        assert (COMMITTED / f).read_bytes() == (out / f).read_bytes(), f"{f} is stale: run python export_lambda.py"


def test_counts_and_joins(out):
    p, j, s = load(out, "ftusa_producers.json"), load(out, "ftusa_projects.json"), load(out, "ftusa_surveys.json")
    sks = {x["accountSk"] for x in p["producers"]}
    assert p["count"] == len(p["producers"]) == 146
    assert j["count"] == 349 and all(x["accountSk"] in sks for x in j["projects"])
    assert all(x["accountSk"] in sks for x in s["surveys"])
    by = {x["accountSk"]: x for x in p["producers"]}
    for sk, prod in by.items():
        assert prod["projectCount"] == sum(1 for x in j["projects"] if x["accountSk"] == sk)


def test_surveys_are_aggregates_only(out):
    s = load(out, "ftusa_surveys.json")
    allowed = {"summaryId", "accountSk", "surveyYear", "nResponses", "metrics", "topChoices"}
    for x in s["surveys"]:
        assert set(x) == allowed
        for v in x["metrics"].values():
            assert set(v) == {"pct", "n"}
        for opts in x["topChoices"].values():
            assert all(set(o) == {"label", "pct"} for o in opts)


def test_standards_bundle(out):
    c = load(out, "standard_clauses.json")
    ids = [x["clauseId"] for x in c["clauses"]]
    assert c["count"] == len(ids) == len(set(ids)) >= 600
    assert {x["standard"] for x in c["clauses"]} == {"APS", "FPS"}
    assert all(x["question"]["en"] for x in c["clauses"])
    assert all(set(x["question"]) <= {"en", "es", "fr"} for x in c["clauses"])
    assert c["origin"] == "ftusa_authored"


def test_producer_map_never_overwritten(tmp_path):
    (tmp_path / "ftusa_producer_map.json").write_text('{"map": {"SYN-P-001": "X"}}')
    ex.run(tmp_path, TABLES, CLAUSES)
    assert json.loads((tmp_path / "ftusa_producer_map.json").read_text()) == {"map": {"SYN-P-001": "X"}}


def test_catalog_describes_the_bundles():
    """Every field the repository catalog lists for C3/C4 exists in the committed bundle."""
    yaml = pytest.importorskip("yaml")
    cat = ROOT.parent / "catalog.yaml"
    if not (cat.exists() and COMMITTED.exists()):
        pytest.skip("catalog.yaml or backend/ not in this checkout")
    files = {"producer_accounts": ("ftusa_producers.json", "producers"), "premium_projects": ("ftusa_projects.json", "projects"),
             "survey_summaries": ("ftusa_surveys.json", "surveys"), "standard_clauses": ("standard_clauses.json", "clauses")}
    entries = {e["name"]: e for e in yaml.safe_load(cat.read_text())["datasets"]}
    for name, (f, key) in files.items():
        rec = load(COMMITTED, f)[key][0]
        assert set(entries[name]["fields"]) <= set(rec), name
