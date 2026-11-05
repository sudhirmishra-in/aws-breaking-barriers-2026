"""Export Component 3 + 4 data as JSON bundles the API Lambda imports (backend/src/data/ftusa/).

    python export_lambda.py                                  # writes ../backend/src/data/ftusa
    python export_lambda.py --out /some/dir --tables out/tables --clauses out/standards/standard_clauses.jsonl

The Lambda reads these bundles; the agent never does. Scope (which producer, which standard) is decided in
backend code from the caller's server-side identity, never from the request or the model.

Bundles (deterministic: same inputs -> byte-identical files; no timestamps):
  ftusa_producers.json   producer accounts (profile only)                     C3
  ftusa_projects.json    Premium projects, joined to producers by accountSk   C3
  ftusa_surveys.json     survey summaries per producer and year, aggregated   C3
  standard_clauses.json  APS / FPS clauses with applicability and tags        C4
  ftusa_producer_map.json  app producerId -> accountSk (written once, never overwritten)
  manifest.json          counts, data versions and the label of every bundle

`accountSk` is an internal join key: backend projections never return it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from c3.items import build_all
from c4.corpus import load_clauses

ROOT = Path(__file__).resolve().parent
DEFAULT_OUT = ROOT.parent / "backend" / "src" / "data" / "ftusa"
EXPORT_VERSION = "1.0.0"

# One place to change the label once the team agrees on it (see docs/LAMBDA_DATA.md).
ORIGIN = "ftusa_team_csv"
CURATION = "not_curated"
RECORDS_SOURCE = "FTUSA team CSV export, processed by ftusa-data"
STANDARDS_SOURCE = "Fair Trade USA APS and FPS criteria workbooks, parsed by ftusa-data"

_CHOICE = re.compile(r"^(.*)\((\d+(?:\.\d+)?)%\)\s*$")


def _version(records) -> str:
    return hashlib.sha256(json.dumps(records, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _bundle(dataset: str, source: str, key: str, records: list, **extra) -> dict:
    return {"dataset": dataset, "exportVersion": EXPORT_VERSION, "dataVersion": _version(records), "source": source,
            "origin": ORIGIN, "curationStatus": CURATION, **extra, "count": len(records), key: records}


def _choices(v) -> list[dict]:
    """'A (8%)|B (6%)' -> [{label: 'A', pct: 8.0}, ...] (labels are provisional: no survey codebook)."""
    out = []
    for part in (v or "").split("|"):
        m = _CHOICE.match(part.strip())
        if m:
            out.append({"label": m.group(1).strip(), "pct": float(m.group(2))})
    return out


def producers(built) -> list[dict]:
    return sorted(({
        "accountSk": p["account_sk"], "displayId": p["display_id"], "orgNameFictional": p["org_name_fictional"],
        "entityType": p["entity_type"], "crops": p["crops"], "primaryCrop": p["primary_crop"],
        "country": p["country"], "countryIso3": p["country_iso3"], "region": p["region"], "regionId": p["region_id"],
        "primaryLanguage": p["primary_language"], "applicableStandard": p["applicable_standard"],
        "certificationStatus": p["certification_status"], "certificationScope": p["certification_scope"],
        "projectCount": p["project_count"], "surveyYears": sorted(p["survey_years"]),
    } for p in built["producers"]), key=lambda x: x["accountSk"])


def projects(built) -> list[dict]:
    return sorted(({
        "projectId": p["project_id"], "accountSk": p["account_sk"], "name": p["name"],
        "description": p["description"], "primaryGoal": p["primary_goal"], "status": p["status"],
        "startDate": p["start_date"], "endDate": p["end_date"], "startYear": p["start_year"],
        "challengeTags": p["challenge_tags"], "subcategory": p["subcategory"], "crop": p["crop"],
        "country": p["country"], "region": p["region"], "peerEligible": bool(p["is_peer_eligible"]),
        "piiFlag": bool(p["pii_flag"]), "contentHash": p["text_sha1"],
    } for p in built["projects"]), key=lambda x: x["projectId"])


def surveys(built) -> list[dict]:
    return sorted(({
        "summaryId": s["summary_id"], "accountSk": s["account_sk"], "surveyYear": s["survey_year"],
        "nResponses": s["n_responses"], "metrics": s["metrics"],
        "topChoices": {k: _choices(v) for k, v in s["top_choices"].items()},
    } for s in built["survey_summaries"]), key=lambda x: (x["accountSk"], x["surveyYear"]))


def clauses(path) -> list[dict]:
    out = []
    for c in load_clauses(path):
        text = json.dumps([c.question, c.intent, c.objective], sort_keys=True, ensure_ascii=False)
        out.append({
            "clauseId": c.clause_id, "standard": c.standard, "code": c.code, "module": c.module,
            "subModule": c.sub_module, "objective": c.objective, "question": c.question, "intent": c.intent,
            "appliesTo": sorted(c.applies_to), "isVariant": c.is_variant, "showFor": sorted(c.show_for),
            "hideFor": sorted(c.hide_for), "timeline": c.timeline, "priority": c.priority, "tags": list(c.tags),
            "contentHash": hashlib.sha1(text.encode()).hexdigest()[:16],
        })
    return out  # source order: retrieval ties break by it, same as the Python retriever


def _write(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def run(out: Path, tables: Path, clause_path: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    built = build_all(tables)
    bundles = {
        "ftusa_producers.json": _bundle("producer_accounts", RECORDS_SOURCE, "producers", producers(built)),
        "ftusa_projects.json": _bundle("premium_projects", RECORDS_SOURCE, "projects", projects(built)),
        "ftusa_surveys.json": _bundle("survey_summaries", RECORDS_SOURCE, "surveys", surveys(built),
                                      labels="provisional (derived from column names; no survey codebook)"),
        "standard_clauses.json": {**_bundle("standard_clauses", STANDARDS_SOURCE, "clauses", clauses(clause_path)),
                                  "origin": "ftusa_authored", "curationStatus": "ftusa_curated"},
    }
    for name, b in bundles.items():
        _write(out / name, b)
    m = out / "ftusa_producer_map.json"
    if not m.exists():  # a team decision, edited by hand: never overwritten by a re-export
        _write(m, {"note": "App producerId -> FTUSA accountSk. Empty until the team decides which demo login maps to "
                           "which source account. Unmapped producers get no FTUSA records.", "map": {}})
    manifest = {"exportVersion": EXPORT_VERSION, "bundles": {
        n: {"dataset": b["dataset"], "dataVersion": b["dataVersion"], "count": b["count"], "origin": b["origin"],
            "curationStatus": b["curationStatus"], "bytes": (out / n).stat().st_size} for n, b in bundles.items()}}
    _write(out / "manifest.json", manifest)
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--tables", type=Path, default=ROOT / "out" / "tables")
    ap.add_argument("--clauses", type=Path, default=ROOT / "out" / "standards" / "standard_clauses.jsonl")
    a = ap.parse_args(argv)
    m = run(a.out, a.tables, a.clauses)
    print(json.dumps(m, indent=1))
    return m


if __name__ == "__main__":
    main()
