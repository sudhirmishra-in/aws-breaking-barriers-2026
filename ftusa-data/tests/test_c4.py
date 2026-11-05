"""Component 4 (standards RAG) on the offline lexical backend, plus the contract with main's tool."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from c4 import load as c4load
from c4.access import MAX_TOP_K, StandardsAccess
from c4.corpus import CROP_AMENDMENTS, applies, load_clauses
from c4.tools import get_standards_clause, local_standards_access

ROOT = Path(__file__).resolve().parents[1]
CLAUSES = Path(os.environ.get("C4_CLAUSES", ROOT / "out" / "standards" / "standard_clauses.jsonl"))
MAIN_TOOLS = ROOT.parent / "agent" / "app" / "exchange" / "tools.py"
pytestmark = pytest.mark.skipif(not CLAUSES.exists(), reason="run Stage A first")

COOP_COFFEE = SimpleNamespace(producerId="SYN-P-001", entityType="cooperative", location="x", crop="coffee")
SMALL_CACAO = SimpleNamespace(producerId="SYN-P-002", entityType="smallholder", location="x", crop="cacao")
FACTORY = SimpleNamespace(producerId="SYN-P-009", entityType="processing_operation", location="x", crop="coffee")
TOPICS = ["premium committee election", "pesticide use and storage", "child labor", "water use for irrigation",
          "workers wages", "deforestation", "grievance mechanism", "training for members", "waste management",
          "uso de pesticidas", "travail des enfants", "agua para riego", "occupational health and safety"]


@pytest.fixture(scope="module")
def sa():
    return local_standards_access(CLAUSES)


def call(sa, producer, topic, lang="en"):
    return get_standards_clause(producer, topic, sa=sa, language=lang)


def test_corpus_loads_both_standards():
    cs = load_clauses(CLAUSES)
    assert {c.standard for c in cs} == {"APS", "FPS"} and len(cs) >= 600
    assert sum(1 for c in cs if c.tags) > len(cs) // 2  # most clauses get at least one challenge tag


def test_keeps_main_evidence_shape(sa):
    r = call(sa, COOP_COFFEE, "pesticide use")
    assert {"kind", "topic", "status", "note"} <= r.keys() and r["kind"] == "standards"
    assert r["status"] == "ok" and 1 <= len(r["clauses"]) <= 3


def test_matches_main_placeholder_keys():
    """Our 'unavailable' result has every key main's placeholder has, so callers keep working."""
    pydantic = pytest.importorskip("pydantic")  # noqa: F841
    if not MAIN_TOOLS.exists():
        pytest.skip("agent/ not in this checkout")
    roots = [str(MAIN_TOOLS.parents[1]), str(ROOT.parent)]  # agent/app, and the repo root for external_data (C5)
    sys.path[:0] = roots
    try:
        from exchange.tools import evidence_unavailable
    except ModuleNotFoundError as e:
        pytest.skip(f"agent tools not importable here: {e}")
    finally:
        del sys.path[:len(roots)]
    main = evidence_unavailable("standards", "x")
    ours = call(local_standards_access(CLAUSES), COOP_COFFEE, "")
    assert ours["status"] == "unavailable" and set(main) <= set(ours) and ours["kind"] == main["kind"]


def test_farm_gets_aps_factory_gets_fps(sa):
    for t in TOPICS:
        for prod, std in ((COOP_COFFEE, "APS"), (FACTORY, "FPS")):
            r = call(sa, prod, t)
            assert r["standard"] == std
            assert all(c["standard"] == std for c in r.get("clauses", []))


def test_every_clause_applies_to_producer(sa):
    by_id = {c.clause_id: c for c in sa.clauses}
    for prod in (COOP_COFFEE, SMALL_CACAO, FACTORY):
        am = {CROP_AMENDMENTS[prod.crop]} if prod.crop in CROP_AMENDMENTS else set()
        for t in TOPICS:
            for c in call(sa, prod, t).get("clauses", []):
                assert applies(by_id[c["clause_id"]], prod.entityType, am), (prod.crop, t, c["clause_id"])


def test_variants_only_with_their_amendment(sa):
    by_id = {c.clause_id: c for c in sa.clauses}
    for t in TOPICS:
        for c in call(sa, COOP_COFFEE, t).get("clauses", []):
            assert not by_id[c["clause_id"]].is_variant  # coffee: no amendment derived


def test_citations_resolve_and_no_producer_ids(sa):
    ids = {c.clause_id for c in sa.clauses}
    for t in TOPICS:
        r = call(sa, SMALL_CACAO, t)
        for c in r.get("clauses", []):
            assert c["citation"]["source_id"] == c["clause_id"] in ids
        assert "SYN-P-002" not in str(r)


def test_spanish_topic_returns_spanish_text_for_aps(sa):
    r = call(sa, COOP_COFFEE, "uso de pesticidas en la finca", "es")
    assert r["status"] == "ok"
    assert any(c["text_language"] == "es" for c in r["clauses"])


def test_spanish_topic_reaches_fps_via_glossary(sa):
    r = call(sa, FACTORY, "salud y seguridad de los trabajadores", "es")
    assert r["status"] == "ok" and all(c["text_language"] == "en" for c in r["clauses"])  # FPS has EN only


def test_no_match_and_empty(sa):
    assert call(sa, COOP_COFFEE, "zxqv blorf")["status"] == "no_match"
    r = call(sa, COOP_COFFEE, "   ")
    assert r["status"] == "unavailable" and "clauses" not in r


def test_bounds(sa):
    r = sa.get_standards_clause(COOP_COFFEE, "x " * 500 + "pesticide", top_k=99)
    assert len(r["topic"]) <= 200 and len(r.get("clauses", [])) <= MAX_TOP_K
    assert all(len(c["intent"]) <= 600 for c in r.get("clauses", []))


def test_backend_failure_degrades_to_unavailable():
    class Boom:
        def search(self, *a, **k):
            raise RuntimeError("s3vectors down")

    sa = StandardsAccess(load_clauses(CLAUSES), Boom())
    r = sa.get_standards_clause(COOP_COFFEE, "pesticides")
    assert r["status"] == "unavailable" and "clauses" not in r and sa.call_log[-1]["status"] == "unavailable"


def test_calls_are_logged_with_citations(sa):
    n = len(sa.call_log)
    r = call(sa, COOP_COFFEE, "child labor")
    rec = sa.call_log[n]
    assert rec["tool"] == "get_standards_clause" and rec["citation_ids"] == [c["clause_id"] for c in r["clauses"]]


def test_loader_dry_run(tmp_path):
    m = c4load.main(["--clauses", str(CLAUSES), "--dry-run", "--dump", str(tmp_path)])
    assert m["vectors"] == len(load_clauses(CLAUSES)) and set(m["by_standard"]) == {"APS", "FPS"}
    assert (tmp_path / "standards_vectors.jsonl").exists()
