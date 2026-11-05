"""Run against the real FTUSA files:  FTUSA_RAW=/path/to/files pytest -q"""
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from ftusa_data import run, surveys, tagging
from ftusa_data.config import CHALLENGE_TAGS, MIN_N
from ftusa_data.standards import StandardsIndex

RAW = Path(os.environ.get("FTUSA_RAW", "/mnt/user-data/attachments/3b792c7c-3b0d-5a0a-ba60-2950a8306169"))
pytestmark = pytest.mark.skipif(not any(RAW.glob("*Producer_Accounts.csv")), reason="raw FTUSA files not found")


@pytest.fixture(scope="session")
def out(tmp_path_factory):
    d = tmp_path_factory.mktemp("out")
    run.main(["--raw", str(RAW), "--out", str(d)])
    return d


def t(out, name):
    return pd.read_csv(out / "tables" / name / f"{name}.csv")


def test_projects_merge_is_one_to_one(out):
    p = t(out, "premium_projects")
    assert len(p) == 349 and p.project_id.is_unique
    assert p.status.notna().all()


def test_every_table_keys_into_producers_or_is_flagged(out):
    ids = set(t(out, "producers").account_sk)
    assert set(t(out, "premium_projects").account_sk) <= ids
    assert set(t(out, "certifications").account_sk) == ids
    s = t(out, "survey_summary")
    assert (s.account_sk.isin(ids) == s.in_producer_accounts).all()


def test_tags_are_valid_and_logged(out):
    p = t(out, "premium_projects")
    for tags in p.challenge_tags.dropna():
        parts = tags.split("|")
        assert 1 <= len(parts) <= 3 and set(parts) <= set(CHALLENGE_TAGS)
    assert p.tag_reason.notna().all()
    assert (p.tag_source == "none").sum() == p.challenge_tags.isna().sum()


def test_pii_never_redacts(out):
    p = t(out, "premium_projects")
    raw = pd.concat(pd.read_csv(f) for f in RAW.glob("*pprojects-full-environmental-with-acct-detail.csv"))
    assert set(raw.translated_project_description_txt.dropna()) == set(p.description.dropna())


def test_peer_eligibility_rules(out):
    p = t(out, "premium_projects")
    e = p[p.is_peer_eligible]
    assert e.status.isin(["completed", "in_progress"]).all() and not e.pii_flag.any() and e.challenge_tags.notna().all()


def test_survey_small_n_suppressed(out):
    s = t(out, "survey_summary")
    for m in [c for c in s.columns if c.startswith("pct_")]:
        n = s[f"n_{m[4:]}"]
        assert s.loc[n < MIN_N, m].isna().all(), m
        assert s[m].dropna().between(0, 100).all()


def test_survey_name_parser():
    r = surveys.parse_survey_name("COMSA_Coffee_SPO_Honduras_2021_V 1.4_HHS")
    assert r == {"survey_crop": "coffee", "survey_type_from_name": "SPO", "survey_year_from_name": 2021}


def test_standards_parsed(out):
    rows = [json.loads(l) for l in (out / "standards" / "standard_clauses.jsonl").read_text().splitlines()]
    ids = [r["clause_id"] for r in rows]
    assert len(ids) == len(set(ids))
    aps = [r for r in rows if r["standard"] == "APS" and not r["is_variant"]]
    assert len(aps) > 150 and all(r["module"] and r["objective"] and r["question"] for r in aps)
    assert sum(bool(r["question_es"]) for r in aps) / len(aps) > 0.9  # Spanish available for grounding
    assert all(r["applies_to"] == "processing_operation" for r in rows if r["standard"] == "FPS")


def test_standards_search_finds_water_clauses(out):
    idx = StandardsIndex.load(out / "standards" / "standard_clauses.jsonl")
    top = idx.search("water use efficiency drought", tags=["water"], entity_type="cooperative", k=3)
    assert top and all(c["module"].startswith("Module 4") for c, _ in top)
    assert all(c["standard"] == "APS" for c, _ in top)


def test_scope_pairs_are_distinct_producers(out):
    s = pd.read_csv(out / "review" / "scope_test_pairs.csv")
    assert len(s) > 0 and (s.session_account_sk != s.other_account_sk).all()


def test_rule_tagging_examples():
    r = tagging.rule_tags({"subcategory": "Clean Water", "name": "Water filters", "description": "Installed filters"})
    assert r["challenge_tags"].split("|")[0] == "water" and r["tag_source"] == "subcategory_rule"
    r = tagging.rule_tags({"subcategory": "Sustainability efforts", "name": "Reforestation with native trees",
                           "description": "Planting native trees to restore forest cover"})
    assert r["primary_tag"] == "biodiversity_conservation" and r["tag_source"] == "keyword"
