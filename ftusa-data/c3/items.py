"""Stage A outputs (out/tables/*) -> store items for Stage B.

The same items feed the InMemoryStore (tests, local runs) and the DynamoDB /
S3 Vectors loader, so what is tested locally is exactly what gets loaded.
Every item is validated with Pydantic (LOAD-2); rejects are reported, never
silently dropped.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Literal, Optional

import pandas as pd
from pydantic import BaseModel, Field, ValidationError

from ftusa_data.config import CHALLENGE_TAGS, MIN_N

EntityType = Literal["cooperative", "smallholder", "estate", "processing_operation", "unknown"]


# --------------------------------------------------------------------------- item models
class SurveyItem(BaseModel):
    account_sk: str
    survey_year: int
    summary_id: str
    n_responses: int = Field(ge=0)
    survey_types: list[str] = []
    survey_crops: list[str] = []
    metrics: dict[str, dict]  # {"harvest_decreased": {"pct": 44.9, "n": 312}, ...}
    top_choices: dict[str, Optional[str]] = {}


class ProducerItem(BaseModel):
    account_sk: str
    display_id: str
    org_name_fictional: str
    entity_type: EntityType
    org_level: Optional[int] = None
    crops: list[str] = []
    primary_crop: Optional[str] = None
    country: Optional[str] = None
    country_iso3: Optional[str] = None
    region: Optional[str] = None
    region_id: Optional[str] = None
    primary_language: str
    certification_status: Optional[str] = None
    certification_scope: Optional[str] = None
    applicable_standard: Literal["APS", "FPS"]
    supply_chain_roles: list[str] = []
    project_count: int = Field(ge=0)
    has_survey: bool
    survey_years: list[int] = []
    survey_latest: Optional[dict] = None
    gsi_crop_sk: str  # GSI by_country_crop sort key: <primary_crop>#<account_sk>


class ProjectItem(BaseModel):
    account_sk: str
    project_id: str
    name: str
    description: Optional[str] = None
    reason: Optional[str] = None
    primary_goal: Optional[str] = None
    description_original: Optional[str] = None
    subcategory: Optional[str] = None
    challenge_tags: list[str] = []
    primary_tag: Optional[str] = None
    status: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    start_year: Optional[int] = None
    country: Optional[str] = None
    region: Optional[str] = None
    region_id: Optional[str] = None
    tag_source: Optional[str] = None
    tag_reason: Optional[str] = None
    pii_flag: bool
    is_peer_eligible: bool
    # denormalized owner profile (peer matching)
    crop: Optional[str] = None
    entity_type: EntityType = "unknown"
    org_name_fictional: Optional[str] = None
    text_sha1: str
    # sparse GSI attributes: present only when is_peer_eligible
    gsi_country: Optional[str] = None
    gsi_country_sk: Optional[str] = None
    gsi_primary_tag: Optional[str] = None
    gsi_tag_sk: Optional[str] = None


class VectorRecord(BaseModel):
    key: str
    text: str
    metadata: dict  # filterable + non-filterable


VECTOR_FILTERABLE = ["account_sk", "country", "crop", "entity_type", "primary_tag", "status", "start_year", "text_sha1"]
VECTOR_NON_FILTERABLE = ["name", "org_name_fictional", "region"]


# --------------------------------------------------------------------------- helpers
def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if hasattr(v, "item"):  # numpy scalar
        v = v.item()
    return v


def _records(path: Path) -> list[dict]:
    df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])
    return [{k: _clean(v) for k, v in r.items()} for r in df.to_dict("records")]


def _list(v, sep="|") -> list[str]:
    return [x for x in str(v).split(sep) if x] if v else []


def _int(v):
    return None if v in (None, "") else int(float(v))


def _float(v):
    return None if v in (None, "") else float(v)


def _bool(v) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes")


def embed_text(p: dict) -> str:
    return " ".join(x for x in [p.get("name"), p.get("description"), p.get("reason")] if x)


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- builders
def build_surveys(rows: list[dict], producer_ids: set[str], include_unknown: bool) -> list[dict]:
    out = []
    for r in rows:
        if not include_unknown and r["account_sk"] not in producer_ids:
            continue
        metrics = {}
        for k, v in r.items():
            if k.startswith("pct_"):
                m = k[4:]
                metrics[m] = {"pct": _float(v), "n": _int(r.get(f"n_{m}")) or 0}
        top = {k[4:]: v for k, v in r.items() if k.startswith("top_")}
        out.append(dict(account_sk=r["account_sk"], survey_year=_int(r["survey_year"]), summary_id=r["summary_id"],
                        n_responses=_int(r["n_responses"]), survey_types=_list(r.get("survey_types")),
                        survey_crops=_list(r.get("survey_crops")), metrics=metrics, top_choices=top))
    return out


def build_all(tables: Path, include_unknown_survey_accounts: bool = False) -> dict:
    tables = Path(tables)
    prod_rows = _records(tables / "producers" / "producers.csv")
    proj_rows = _records(tables / "premium_projects" / "premium_projects.csv")
    surv_rows = _records(tables / "survey_summary" / "survey_summary.csv")
    pids = {p["account_sk"] for p in prod_rows}
    rejects: dict[str, list] = {"producers": [], "projects": [], "survey_summaries": []}

    surveys = []
    for s in build_surveys(surv_rows, pids, include_unknown_survey_accounts):
        try:
            surveys.append(SurveyItem(**s).model_dump())
        except ValidationError as e:
            rejects["survey_summaries"].append({"key": s.get("summary_id"), "error": str(e)[:300]})
    by_acct: dict[str, list[dict]] = {}
    for s in surveys:
        by_acct.setdefault(s["account_sk"], []).append(s)

    producers = []
    for p in prod_rows:
        mine = sorted(by_acct.get(p["account_sk"], []), key=lambda s: s["survey_year"])
        # latest year with enough responses to say anything; else simply the latest
        usable = [s for s in mine if s["n_responses"] >= MIN_N] or mine
        latest = {k: v for k, v in usable[-1].items() if k != "account_sk"} if usable else None
        item = dict(
            account_sk=p["account_sk"], display_id=p["display_id"], org_name_fictional=p["org_name_fictional"],
            entity_type=p["entity_type"], org_level=_int(p.get("org_level")), crops=_list(p.get("crops")),
            primary_crop=p.get("primary_crop"), country=p.get("country"), country_iso3=p.get("country_iso3"),
            region=p.get("region"), region_id=p.get("region_id"), primary_language=p["primary_language"],
            certification_status=p.get("certification_status"), certification_scope=p.get("certification_scope"),
            applicable_standard=p["applicable_standard"], supply_chain_roles=_list(p.get("supply_chain_roles")),
            project_count=_int(p.get("n_projects")) or 0, has_survey=bool(mine),
            survey_years=[s["survey_year"] for s in mine], survey_latest=latest,
            gsi_crop_sk=f"{p.get('primary_crop') or 'none'}#{p['account_sk']}")
        try:
            producers.append(ProducerItem(**item).model_dump())
        except ValidationError as e:
            rejects["producers"].append({"key": p.get("account_sk"), "error": str(e)[:300]})
    pmap = {p["account_sk"]: p for p in producers}

    projects, vectors = [], []
    for r in proj_rows:
        owner = pmap.get(r["account_sk"], {})
        tags = [t for t in _list(r.get("challenge_tags")) if t in CHALLENGE_TAGS]
        elig = _bool(r.get("is_peer_eligible")) and bool(owner)
        sy = _int(r.get("start_year"))
        text = embed_text(r)
        item = dict(
            account_sk=r["account_sk"], project_id=r["project_id"], name=r.get("name") or "(untitled)",
            description=r.get("description"), reason=r.get("reason"), primary_goal=r.get("primary_goal"),
            description_original=r.get("description_original"), subcategory=r.get("subcategory"),
            challenge_tags=tags, primary_tag=tags[0] if tags else None, status=r.get("status") or "unknown",
            start_date=r.get("start_date"), end_date=r.get("end_date"), start_year=sy, country=r.get("country"),
            region=r.get("region"), region_id=r.get("region_id"), tag_source=r.get("tag_source"),
            tag_reason=r.get("tag_reason"), pii_flag=_bool(r.get("pii_flag")), is_peer_eligible=elig,
            crop=owner.get("primary_crop") or "unknown", entity_type=owner.get("entity_type", "unknown"),
            org_name_fictional=owner.get("org_name_fictional"), text_sha1=sha1(text))
        if elig:
            item.update(gsi_country=item["country"],
                        gsi_country_sk=f"{item['primary_tag']}#{sy or 0:04d}#{item['project_id']}",
                        gsi_primary_tag=item["primary_tag"],
                        gsi_tag_sk=f"{item['crop']}#{item['country']}#{item['project_id']}")
        try:
            projects.append(ProjectItem(**item).model_dump())
        except ValidationError as e:
            rejects["projects"].append({"key": r.get("project_id"), "error": str(e)[:300]})
            continue
        if elig:
            meta = {k: item[k] for k in VECTOR_FILTERABLE + VECTOR_NON_FILTERABLE if item.get(k) is not None}
            vectors.append(VectorRecord(key=item["project_id"], text=text, metadata=meta).model_dump())

    countries = pd.Series([p["country"] for p in projects]).value_counts().head(4)
    years = sorted({s["survey_year"] for s in surveys})
    stats = {
        "n_producers": len(producers),
        "n_unknown_entity": sum(p["entity_type"] == "unknown" for p in producers),
        "n_with_survey": sum(p["has_survey"] for p in producers),
        "n_projects": len(projects),
        "n_project_producers": len({p["account_sk"] for p in projects}),
        "n_peer_eligible": len(vectors),
        "top_countries": ", ".join(f"{c} {n}" for c, n in countries.items()),
        "survey_years": f"{years[0]}-{years[-1]}" if years else "none",
        "min_n": MIN_N,
    }
    return {"producers": producers, "projects": projects, "survey_summaries": surveys, "vectors": vectors,
            "stats": stats, "rejects": rejects}


def write_stats(built: dict, path: Path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(built["stats"], indent=2, ensure_ascii=False))
