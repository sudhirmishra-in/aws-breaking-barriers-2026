"""Two Premium project files -> one premium_projects table.

pprojects-full-environmental-with-acct-detail.csv : translated text, region, sub-category, structure
Premium_Projects_Environmental.csv                : original-language description, dates, status

There is no shared project ID. Rows are matched on
(account_sk, project_name, region, sub-category); when that key repeats, rows
with identical description text are paired first, the rest in file order, and
the row is flagged merge_ambiguous.
"""
from __future__ import annotations

import pandas as pd

from .io import norm_country, stable_id

DOCS = {
    "project_id": "Stable ID derived from source fields (PRJ-xxxxxxxxxx)",
    "account_sk": "FK producers",
    "country": "Normalized country", "region": "Region as in source", "region_id": "FK regions",
    "name": "translated_project_name", "description": "translated_project_description_txt",
    "reason": "translated_project_reason_txt - the need the project responds to",
    "primary_goal": "translated_primary_goal_txt",
    "description_original": "project_description_txt (original language, from Premium_Projects_Environmental)",
    "category": "Always 'Environmental' in this extract", "subcategory": "FTUSA sub-category (normalized casing)",
    "start_date": "ISO date; blank if implausible (<2000)", "end_date": "ISO date", "start_year": "int",
    "status": "completed | in_progress | in_planning",
    "challenge_tags": "1-3 of the 11 tags, pipe-separated; first = primary",
    "primary_tag": "First tag", "tag_source": "subcategory_rule | keyword | llm | none",
    "tag_reason": "Why these tags (logged reasoning)", "tag_pending_confirmation": "Mapping awaits FTUSA confirmation",
    "pii_flag": "Possible PII in text (flag for review, text NOT redacted)", "pii_types": "e.g. phone|email|person_title",
    "is_test_record": "Looks like a test/placeholder row (name 'test', lorem ipsum text, or dropdown-default country)",
    "is_peer_eligible": "Usable as a peer example: completed/in progress, has text, tagged, no PII flag, not a test record",
    "merge_ambiguous": "Matched between the two source files by order within a duplicate key",
    "country_mismatch": "Project country differs from account country",
    "date_issue": "Start date dropped as implausible",
    "source": "FTUSA Premium projects export (Environmental)",
}

STATUS = {"Completed": "completed", "In Progress": "in_progress", "In Planning": "in_planning"}


def _key(df, name, region, sub):
    return (df.account_sk.fillna("") + "|" + df[name].fillna("") + "|" + df[region].fillna("") + "|"
            + df[sub].fillna("").str.strip().str.lower())


def merge(full: pd.DataFrame, env: pd.DataFrame) -> pd.DataFrame:
    full = full.copy().reset_index(drop=True)
    env = env.copy().reset_index(drop=True)
    full["_k"] = _key(full, "translated_project_name", "region", "subcategory")
    env["_k"] = _key(env, "project_name", "country_region_name", "sub_category_taxonomy_term_txt")
    pairs, ambiguous = {}, set()
    for k, fi in full.groupby("_k").groups.items():
        ei = list(env.index[env._k == k])
        fi = list(fi)
        if len(fi) != len(ei):
            raise ValueError(f"project key {k!r}: {len(fi)} rows in full file, {len(ei)} in env file")
        if len(fi) > 1:
            ambiguous.update(fi)
            for f in list(fi):  # exact description match first
                for e in list(ei):
                    if full.at[f, "translated_project_description_txt"] == env.at[e, "project_description_txt"]:
                        pairs[f] = e
                        fi.remove(f)
                        ei.remove(e)
                        break
        for f, e in zip(fi, ei):
            pairs[f] = e
    if len(pairs) != len(full) or len(set(pairs.values())) != len(env):
        raise ValueError("project merge did not produce a 1:1 match")
    e = env.loc[[pairs[i] for i in full.index]].reset_index(drop=True)
    m = full.drop(columns="_k").copy()
    for c in ["project_description_txt", "project_start_date", "project_end_date", "project_status_name", "country_name"]:
        m[c] = e[c].values
    m["merge_ambiguous"] = m.index.isin(ambiguous)
    return m


def build(full: pd.DataFrame, env: pd.DataFrame, account_country: dict) -> pd.DataFrame:
    m = merge(full, env)
    m["country"] = m.country.map(norm_country)
    from .io import iso3, slug

    start = pd.to_datetime(m.project_start_date, errors="coerce")
    bad = start.dt.year < 2000
    start = start.mask(bad)
    end = pd.to_datetime(m.project_end_date, errors="coerce")
    seq = m.groupby(["account_sk", "translated_project_name"]).cumcount()
    out = pd.DataFrame({
        "project_id": [stable_id("PRJ", a, n, r, s) for a, n, r, s in
                       zip(m.account_sk, m.translated_project_name, m.region.fillna(""), seq)],
        "account_sk": m.account_sk,
        "country": m.country,
        "region": m.region,
        "region_id": [f"{iso3(c)}-{slug(r)}" if isinstance(r, str) else None for c, r in zip(m.country, m.region)],
        "name": m.translated_project_name,
        "description": m.translated_project_description_txt,
        "reason": m.translated_project_reason_txt,
        "primary_goal": m.translated_primary_goal_txt,
        "description_original": m.project_description_txt,
        "category": m.category,
        "subcategory": m.subcategory.str.strip(),
        "start_date": start.dt.date.astype("string"),
        "end_date": end.dt.date.astype("string"),
        "start_year": start.dt.year.astype("Int64"),
        "status": m.project_status_name.map(STATUS).fillna(m.project_status_name),
        "merge_ambiguous": m.merge_ambiguous,
        "country_mismatch": [account_country.get(a) not in (None, c) for a, c in zip(m.account_sk, m.country)],
        "date_issue": bad.fillna(False),
        "source": "FTUSA Premium projects export (Environmental)",
    })
    if out.project_id.duplicated().any():
        raise ValueError("duplicate project_id")
    return out


def text_of(row) -> str:
    return " ".join(str(x) for x in [row.get("name"), row.get("description"), row.get("reason"), row.get("primary_goal")]
                    if isinstance(x, str))


TEST_NAME = r"(?i)\btest\b|^\s*t{3,}\s*$"
TEST_TEXT = r"(?i)lorem\s+l?ipsum|dolor sit amet|consectetur adipiscing"


def finalize(projects: pd.DataFrame) -> pd.DataFrame:
    from .config import SUSPECT_COUNTRIES

    p = projects.copy()
    has_text = p.description.fillna("").str.len() >= 40
    p["is_test_record"] = (p.name.fillna("").str.contains(TEST_NAME)
                           | p.description.fillna("").str.contains(TEST_TEXT)
                           | p.country.isin(SUSPECT_COUNTRIES))
    p["is_peer_eligible"] = (p.status.isin(["completed", "in_progress"]) & has_text
                             & (p.challenge_tags.fillna("") != "") & ~p.pii_flag & ~p.is_test_record)
    return p[list(DOCS)]
