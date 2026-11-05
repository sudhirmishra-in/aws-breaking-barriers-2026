#!/usr/bin/env python3
"""Deterministic validation + normalization pipeline for the supplied public nonprofit CSVs (stdlib only; Parquet output needs pyarrow).

Raw files are never modified or copied into git. Outputs:
  data/nonprofit-public/   committed, small: manifest, exception report, accounts, projects, survey definitions, demo account summaries
  build/nonprofit/         git-ignored: Parquet serving tables and the quarantine (excluded rows, kept, never served)
The data is public (stated by the user). Public is NOT conversation-sharing consent and NOT FTUSA curation: every record carries
origin="public_source_data" and curationStatus="not_curated".

  uv run --with pyarrow python scripts/nonprofit_ingest.py --src "<dir>" [--out data/nonprofit-public] [--build build/nonprofit]
"""
from __future__ import annotations

import argparse, collections, csv, datetime as dt, gzip, hashlib, json, re, sys
from pathlib import Path

PIPELINE_VERSION = "1.0.1"
SCHEMA_VERSION = "nonprofit-csv-2026-10-29"
FILES = {
    "accounts": "Producer Accounts.csv", "projects": "Premium Projects Environmental.csv", "survey_defs": "Household Survey Header.csv",
    "headers": "Survey Response Header.csv", "single": "Survey Response Questions Single Choice.csv", "multi": "Survey Response Questions Multiple Choice.csv",
}
ORIGIN = {"origin": "public_source_data", "curationStatus": "not_curated", "consentToShare": "not_applicable_public_source", "synthetic": False}

# ---- reviewed country mapping (raw values are always retained next to the normalized one) ---------------------------------------------
COUNTRY_ISO = {"Colombia": "CO", "Peru": "PE", "Mexico": "MX", "Guatemala": "GT", "Indonesia": "ID", "Honduras": "HN", "Ecuador": "EC", "Philippines": "PH", "Brazil": "BR",
    "Côte d'Ivoire": "CI", "Sri Lanka": "LK", "Rwanda": "RW", "India": "IN", "Vietnam": "VN", "Nicaragua": "NI", "Paraguay": "PY", "China": "CN", "Belize": "BZ", "Costa Rica": "CR",
    "New Zealand": "NZ", "Haiti": "HT", "Solomon Islands": "SB", "Morocco": "MA", "Kenya": "KE", "Andorra": "AD", "Åland Islands": "AX", "Ghana": "GH", "Bolivia": "BO",
    "Thailand": "TH", "Afghanistan": "AF", "Ethiopia": "ET", "United States": "US"}
COUNTRY_ALIAS = {  # reviewed: alias -> canonical
    "cote d'ivoire": "Côte d'Ivoire", "côte d'ivoire": "Côte d'Ivoire", "côte d’ivoire": "Côte d'Ivoire", "cote d’ivoire": "Côte d'Ivoire",
    "bolivia (plurinational state of)": "Bolivia", "usa": "United States", "united states of america": "United States",
}
# Geographies that need human review before use as regional precedents (account/geography consistency is not established by the data).
REVIEW_GEOGRAPHIES = {"Andorra", "Åland Islands", "Afghanistan"}


def normalize_country(raw: str | None) -> dict:
    raw = (raw or "").strip()
    if not raw: return {"raw": raw, "normalized": None, "iso2": None, "status": "missing"}
    canon = COUNTRY_ALIAS.get(raw.lower())
    name = canon or raw
    status = "alias" if canon and canon != raw else "exact"
    if name not in COUNTRY_ISO: return {"raw": raw, "normalized": None, "iso2": None, "status": "unmapped"}
    return {"raw": raw, "normalized": name, "iso2": COUNTRY_ISO[name], "status": status}


def country_link_status(project_raw: str, account_raw: str) -> str:
    """'same' | 'alias' (textual difference only after reviewed normalization) | 'conflict' | 'unreviewed'."""
    p, a = normalize_country(project_raw), normalize_country(account_raw)
    if p["status"] in ("unmapped", "missing") or a["status"] in ("unmapped", "missing"): return "unreviewed"
    if p["normalized"] != a["normalized"]: return "conflict"
    return "same" if project_raw.strip() == account_raw.strip() else "alias"


# ---- dates -----------------------------------------------------------------------------------------------------------------------------
def parse_date(s: str | None):
    try: return dt.date.fromisoformat((s or "").strip())
    except ValueError: return None


def date_flags(start: str, end: str) -> list[str]:
    """Flags only; values are never rewritten. 1970-01-01 is an unresolved suspicious value (not a real 1970 project, not silently null)."""
    flags, s, e = [], parse_date(start), parse_date(end)
    if (start or "").strip() and s is None: flags.append("start_unparseable")
    if (end or "").strip() and e is None: flags.append("end_unparseable")
    if s and s == dt.date(1970, 1, 1): flags.append("start_epoch_placeholder")
    elif s and s.year < 1990: flags.append("start_before_1990")
    if s and e and e < s: flags.append("end_before_start")
    if e and e.year > 2035: flags.append("end_after_2035")
    return flags


# ---- stable project ids (the source has no project id column) --------------------------------------------------------------------------
def project_id(row: dict, taken: set[str]) -> str:
    """Hash of (account_sk, project_name, start, end). Stable if the description is edited; changes if name/dates/account change (then a new id is issued and the
    old one is retired in the manifest). A second identical row gets a -2 suffix by source order. Description changes surface as a new contentHash, not a new id."""
    base = hashlib.sha256("|".join((row.get(k) or "").strip() for k in ("account_sk", "project_name", "project_start_date", "project_end_date")).encode()).hexdigest()[:12].upper()
    pid, n = f"PRJ-{base}", 1
    while pid in taken:
        n += 1; pid = f"PRJ-{base}-{n}"
    taken.add(pid); return pid


# ---- answer-row classification ------------------------------------------------------------------------------------------------------------
def classify_answer(row: dict, headers: dict[str, dict], account_ids: set[str]) -> str:
    """Never prefers one table's account over the other: any disagreement is quarantined."""
    h = headers.get(row.get("survey_response_sk", ""))
    if h is None: return "no_header"
    if h["account_sk"] != row.get("account_sk"): return "account_conflict"
    if h["survey_sk"] != row.get("survey_sk"): return "survey_conflict"
    if h["response_id"] != row.get("response_id"): return "response_id_conflict"
    return "consistent" if row["account_sk"] in account_ids else "consistent_account_not_supplied"


def classify_value(v: str | None) -> str:
    """Distinct states; nothing is interpreted. A raw 0 is kept as 'zero_raw' (could be real, default or not-applicable)."""
    v = (v or "").strip()
    if v == "": return "missing"
    low = v.lower().replace("’", "'")
    if low in ("refused",): return "refused"
    if low in ("don't know", "i don't know", "dont know"): return "dont_know"
    if low in ("n/a", "not applicable", "none of the above applies"): return "not_applicable_label"
    try:
        if float(v) == 0.0: return "zero_raw"
    except ValueError: pass
    return "value"


def aggregate_multi(rows: list[dict]) -> dict[tuple[str, str], list[str]]:
    """(survey_response_sk, question) -> sorted distinct selected options. Selected-option rows are NOT respondents; collapse before joining."""
    out: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    for r in rows: out[(r["survey_response_sk"], r["question_label_txt"])].add(r["question_choice_txt"])
    return {k: sorted(v) for k, v in out.items()}


def multi_distribution(per_response: dict[tuple[str, str], list[str]]) -> dict[str, dict]:
    """Per question: denominator = distinct responses with at least one selection (a response that skipped or was not asked is indistinguishable: stated);
    each option's count = distinct responses selecting it (an option count can never exceed the denominator)."""
    q: dict[str, dict] = {}
    for (resp, label), choices in per_response.items():
        d = q.setdefault(label, {"responses": set(), "options": collections.defaultdict(set)})
        d["responses"].add(resp)
        for c in choices: d["options"][c].add(resp)
    return {label: {"denominatorResponses": len(d["responses"]), "denominatorBasis": "responses with at least one selection for this question",
                    "options": {c: len(rs) for c, rs in sorted(d["options"].items(), key=lambda kv: (-len(kv[1]), kv[0]))}} for label, d in q.items()}


def single_distribution(rows: list[dict], column: str) -> dict:
    n = len(rows); kinds = collections.Counter(classify_value(r.get(column)) for r in rows)
    vals = collections.Counter(r[column].strip() for r in rows if classify_value(r.get(column)) == "value")
    return {"responsesInScope": n, "states": dict(kinds), "answered": kinds["value"], "options": dict(vals.most_common(15)),
            "note": "missing, zero_raw, refused and dont_know are kept separate; none is treated as a respondent answer unless state is 'value'"}


def project_card(p: dict, ingestion_version: str) -> tuple[str, dict]:
    """One Markdown evidence card per servable project row plus Bedrock KB metadata. The source account reference stays in metadata (internal), never in the text
    a model could quote. Status/goal wording is reproduced as recorded: no outcome is derived from 'Completed' and nothing is called curated."""
    prod = ", ".join(p["products"]) or "not recorded"; c = p["country"]
    text = (f"# {p['title']}\n\n**Source record**: public project record (not an agent conversation, not FTUSA-curated)\n\n**Description as recorded**: {p['description']}\n\n"
            f"- Country: {c['normalized'] or c['raw']}" + (f" (recorded as: {c['raw']})" if c["status"] == "alias" else "") + f"\n- Region: {p['region'] or 'not recorded'}\n- Products: {prod}\n"
            f"- Dates: {p['startDate'] or 'not recorded'} to {p['endDate'] or 'not recorded'}" + (f" (date flags: {', '.join(p['dateFlags'])})" if p["dateFlags"] else "") + "\n"
            f"- Recorded status: {p['recordedStatus']}\n- Taxonomy: {p['category']} / {p['subCategory']}\n- Measured outcome: not reported in the source\n"
            f"- Reference: {p['projectId']} (ingestion {ingestion_version}, content {p['contentHash']})\n")
    meta = {"metadataAttributes": {"projectId": p["projectId"], "countryIso2": c["iso2"] or "", "region": p["region"], "products": ";".join(p["products"]).lower(), "category": p["category"],
            "subCategory": p["subCategory"], "recordedStatus": p["recordedStatus"], "startYear": int(p["startDate"][:4]) if p["startDate"][:4].isdigit() else 0,
            "origin": "public_source_data", "curationStatus": "not_curated", "sourceAccountSk": p["sourceRef"]["accountSk"], "contentHash": p["contentHash"], "ingestionVersion": ingestion_version}}
    # Bedrock KB rejects empty-string attribute values (71 cards failed ingestion on a live run): absent is the correct representation of "not recorded".
    meta["metadataAttributes"] = {k: v for k, v in meta["metadataAttributes"].items() if v != ""}
    return text, meta


def write_cards(projects: list[dict], ingestion_version: str, build: Path) -> int:
    d = build / "cards"; d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("*"): old.unlink()  # cards are derived; the directory always reflects exactly the current ingestion
    n = 0
    for p in projects:
        if not p["usableAsRegionalPrecedent"]: continue  # conflicting geography, review-pending countries and epoch-placeholder dates are not served as precedents
        text, meta = project_card(p, ingestion_version)
        (d / f"{p['projectId']}.md").write_text(text, encoding="utf-8"); (d / f"{p['projectId']}.md.metadata.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8"); n += 1
    return n


def provisional_label(column: str) -> str:
    s = re.sub(r"_(code|name|nbr|txt|ms_core|core)$", "", column).replace("_", " ").strip()
    return s[:1].upper() + s[1:]


# ---- IO ----------------------------------------------------------------------------------------------------------------------------------
csv.field_size_limit(10**9)
def read(p: Path) -> list[dict]:
    with p.open(encoding="utf-8-sig", newline="") as f: return list(csv.DictReader(f))
def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""): h.update(chunk)
    return h.hexdigest()
def dump(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


DEMO_ACCOUNTS = {  # source-account references (not people); explicit fictional display aliases are applied by the demo seed, never here
    "691F055F8DA798187584F41E6871D1AF": "coffee, Huila, Colombia", "A7F700B04BCE55512CB026A71121426C": "coffee, Cajamarca, Peru",
    "FA9ADCCE1553D4FADD64C87CA6219F97": "cocoa, Bas-Sassandra, Côte d'Ivoire", "CED2DEE8ED99922FA5C6244DEF177AF3": "coffee, La Paz, Honduras",
}
SUMMARY_COLUMNS = ["has_hired_labor_code", "harvest_changed_code", "has_water_conservation_practices_code", "has_soil_conservation_practices_code",
                   "has_forest_protection_practices_code", "has_received_fertilizer_training_code", "has_integrated_pest_management_practices_name", "water_access_distance_name"]


def run(src: Path, out: Path, build: Path, serve: Path | None = None) -> dict:
    files = {k: src / v for k, v in FILES.items()}
    for k, p in files.items():
        if not p.exists(): sys.exit(f"missing source file: {p}")
    fp = {k: {"file": FILES[k], "sha256": sha256(p), "bytes": p.stat().st_size} for k, p in files.items()}
    data = {k: read(p) for k, p in files.items()}
    for k in fp: fp[k]["rows"] = len(data[k]); fp[k]["columns"] = list(data[k][0].keys()) if data[k] else []
    ingestion_version = hashlib.sha256((PIPELINE_VERSION + "|" + "|".join(fp[k]["sha256"] for k in sorted(fp))).encode()).hexdigest()[:16]
    manifest = {"pipelineVersion": PIPELINE_VERSION, "schemaVersion": SCHEMA_VERSION, "ingestionVersion": ingestion_version, "files": fp, "provenance": ORIGIN,
                "attribution": "Supplied public nonprofit data files; the user states they are public and usable for the demo. Not FTUSA-curated."}

    accounts = {r["account_sk"]: r for r in data["accounts"]}
    headers = {r["survey_response_sk"]: r for r in data["headers"]}
    exc: dict = {"ingestionVersion": ingestion_version, "uniqueness": {"accounts": len(accounts) == len(data["accounts"]), "responseHeaders": len(headers) == len(data["headers"])}}

    # projects
    taken: set[str] = set(); projects, p_exc = [], collections.Counter(); samples = collections.defaultdict(list)
    for i, r in enumerate(data["projects"], start=2):  # row 1 is the header
        a = accounts.get(r["account_sk"])
        if a is None: p_exc["project_without_account"] += 1; continue
        cl = country_link_status(r["country_name"], a["country_name"]); flags = date_flags(r["project_start_date"], r["project_end_date"])
        c = normalize_country(r["country_name"])
        if cl in ("alias", "conflict", "unreviewed"): p_exc[f"country_{cl}"] += 1; samples[f"country_{cl}"].append(i)
        for f in flags: p_exc[f"date_{f}"] += 1; samples[f"date_{f}"].append(i)
        if c["normalized"] in REVIEW_GEOGRAPHIES: p_exc["geography_needs_review"] += 1; samples["geography_needs_review"].append(i)
        content = hashlib.sha256(json.dumps(r, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        projects.append({"projectId": project_id(r, taken), "sourceRef": {"file": FILES["projects"], "row": i, "accountSk": r["account_sk"]}, "contentHash": content,
            "title": r["project_name"], "description": r["project_description_txt"], "country": c, "region": r["country_region_name"], "accountCountry": normalize_country(a["country_name"]),
            "countryLink": cl, "products": [x for x in a["product_category_name"].split(";") if x], "category": r["category_taxonomy_term_txt"], "subCategory": r["sub_category_taxonomy_term_txt"],
            "startDate": r["project_start_date"], "endDate": r["project_end_date"], "dateFlags": flags, "recordedStatus": r["project_status_name"],
            "outcome": "not_reported",  # the source has no measured-outcome field; a Completed status is never turned into a result
            "usableAsRegionalPrecedent": cl != "conflict" and c["normalized"] not in REVIEW_GEOGRAPHIES and "start_epoch_placeholder" not in flags, **ORIGIN})
    exc["projects"] = {"total": len(data["projects"]), "served": len(projects), "flags": dict(p_exc), "sampleRows": {k: v[:10] for k, v in samples.items()}}

    # answers
    acct_ids = set(accounts)
    answers = {}
    for k in ("single", "multi"):
        by = collections.defaultdict(list); cnt = collections.Counter()
        for r in data[k]:
            c = classify_answer(r, headers, acct_ids); cnt[c] += 1; by[c].append(r)
        answers[k] = by; exc[f"{k}_choice"] = {"total": len(data[k]), "classification": dict(cnt), "servedRows": cnt["consistent"],
            "quarantinedRows": sum(v for c, v in cnt.items() if c != "consistent")}
    # header coverage
    exc["headers"] = {"total": len(data["headers"]), "accountsInHeaders": len({h["account_sk"] for h in data["headers"]}),
        "accountsAlsoSupplied": len({h["account_sk"] for h in data["headers"]} & acct_ids), "headersWithUnknownSurvey": sum(h["survey_sk"] not in {s["survey_sk"] for s in data["survey_defs"]} for h in data["headers"])}
    exc["note"] = "Quarantine means not served for account-scoped answers; the rows are kept in build/nonprofit/quarantine and may represent a different export scope or account mapping."

    # demo accounts
    demo = {}
    surveys = {s["survey_sk"]: s for s in data["survey_defs"]}
    multi_by_acct = collections.defaultdict(list)
    for r in answers["multi"]["consistent"]: multi_by_acct[r["account_sk"]].append(r)
    single_by_acct = collections.defaultdict(list)
    for r in answers["single"]["consistent"]: single_by_acct[r["account_sk"]].append(r)
    for sk, label in DEMO_ACCOUNTS.items():
        a = accounts.get(sk)
        if not a: demo[sk] = {"error": "account not in Producer Accounts"}; continue
        hs = [h for h in data["headers"] if h["account_sk"] == sk]; srows = single_by_acct[sk]
        years = collections.Counter((h["end_date"] or h["start_date"] or "")[:4] for h in hs)
        conflicts_single = sum(1 for r in data["single"] if r["account_sk"] == sk and classify_answer(r, headers, acct_ids) != "consistent")
        conflicts_multi = sum(1 for r in data["multi"] if r["account_sk"] == sk and classify_answer(r, headers, acct_ids) != "consistent")
        demo[sk] = {"sourceContext": label, "account": {**{k: a[k] for k in a}, "country": normalize_country(a["country_name"])},
            "projects": [p["projectId"] for p in projects if p["sourceRef"]["accountSk"] == sk], "responseHeaders": len(hs), "consistentSingleChoiceResponses": len(srows),
            "consistentMultipleChoiceOptionRows": len(multi_by_acct[sk]), "quarantinedRowsForThisAccount": {"single": conflicts_single, "multi": conflicts_multi},
            "surveyYears": dict(sorted(years.items())), "surveys": sorted({surveys[h["survey_sk"]]["survey_name"] for h in hs if h["survey_sk"] in surveys}),
            "singleChoiceSummaries": [{"column": c, "labelStatus": "provisional_from_column_name", "label": provisional_label(c), **single_distribution(srows, c)} for c in SUMMARY_COLUMNS],
            "multipleChoiceSummaries": {q: {"labelStatus": "provisional_from_question_label", **d} for q, d in sorted(multi_distribution(aggregate_multi(multi_by_acct[sk])).items())},
            "codebook": "unavailable: labels are coded identifiers; wording and applicability are provisional", **ORIGIN}
    manifest["demoAccounts"] = list(DEMO_ACCOUNTS)

    # outputs
    exc["projectCards"] = write_cards(projects, ingestion_version, build)
    # Serving subset bundled with the API: usable project rows only, WITHOUT the internal source account reference.
    if serve: dump(serve, {"ingestionVersion": ingestion_version, "source": FILES["projects"], "projects": [
        {"projectId": p["projectId"], "title": p["title"], "description": p["description"], "country": p["country"]["normalized"], "countryRaw": p["country"]["raw"], "countryIso2": p["country"]["iso2"],
         "region": p["region"], "products": p["products"], "startDate": p["startDate"], "endDate": p["endDate"], "recordedStatus": p["recordedStatus"], "category": p["category"],
         "subCategory": p["subCategory"], "contentHash": p["contentHash"], "sourceRow": p["sourceRef"]["row"], "dateFlags": p["dateFlags"]} for p in projects if p["usableAsRegionalPrecedent"]]})
    dump(out / "manifest.json", manifest); dump(out / "exception_report.json", exc)
    dump(out / "accounts.json", {"ingestionVersion": ingestion_version, "accounts": [{**r, "country": normalize_country(r["country_name"]), **ORIGIN} for r in data["accounts"]]})
    dump(out / "projects.json", {"ingestionVersion": ingestion_version, "projects": projects})
    dump(out / "survey_definitions.json", {"ingestionVersion": ingestion_version, "surveys": [{**s, **ORIGIN} for s in data["survey_defs"]]})
    dump(out / "demo_accounts.json", {"ingestionVersion": ingestion_version, "accounts": demo})
    # quarantine (non-serving) + serving tables
    qdir = build / "quarantine"; qdir.mkdir(parents=True, exist_ok=True)
    for k in ("single", "multi"):
        rows = [dict(r, _quarantine_reason=c) for c, rs in answers[k].items() if c != "consistent" for r in rs]
        if rows:
            with gzip.open(qdir / f"{k}_choice_quarantine.csv.gz", "wt", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    try:
        import pyarrow as pa, pyarrow.parquet as pq
        def tbl(name, rows, cols):
            (build / "parquet").mkdir(parents=True, exist_ok=True)
            pq.write_table(pa.table({c: [str(r.get(c, "")) for r in rows] for c in cols}), build / "parquet" / f"{name}.parquet", compression="zstd")
        tbl("projects", [{**p, "country_raw": p["country"]["raw"], "country_iso2": p["country"]["iso2"] or "", "account_sk": p["sourceRef"]["accountSk"], "date_flags": ",".join(p["dateFlags"])} for p in projects],
            ["projectId", "account_sk", "title", "description", "country_raw", "country_iso2", "region", "category", "subCategory", "startDate", "endDate", "date_flags", "recordedStatus", "outcome", "contentHash", "origin", "curationStatus"])
        tbl("survey_definitions", data["survey_defs"], list(data["survey_defs"][0].keys()))
        tbl("response_headers", data["headers"], list(data["headers"][0].keys()))
        tbl("single_choice_answers", answers["single"]["consistent"], list(data["single"][0].keys()))
        tbl("multiple_choice_selections", answers["multi"]["consistent"], list(data["multi"][0].keys()))
        exc["parquet"] = "written"
    except ImportError:
        exc["parquet"] = "skipped: pyarrow not installed"
    dump(out / "exception_report.json", exc)
    return {"manifest": manifest, "exceptions": exc}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--src", required=True)
    root = Path(__file__).resolve().parent.parent
    ap.add_argument("--out", default=str(root / "data" / "nonprofit-public")); ap.add_argument("--build", default=str(root / "build" / "nonprofit")); a = ap.parse_args()
    r = run(Path(a.src), Path(a.out), Path(a.build), root / "backend" / "src" / "data" / "public_projects.json"); e = r["exceptions"]
    print("ingestionVersion", r["manifest"]["ingestionVersion"])
    print("projects", e["projects"]["served"], "/", e["projects"]["total"], e["projects"]["flags"])
    for k in ("single_choice", "multi_choice"): print(k, e[k]["classification"])
    print("parquet:", e["parquet"])
