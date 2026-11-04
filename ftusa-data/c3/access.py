"""Data-access layer (DA-1..4) + scope enforcement (SCOPE-1..4).

The ONLY code tools call. Backend-agnostic: give it any Store.

Guarantees, whatever the backend returns:
  * every call is bounded (MAX_LIMIT / MAX_TOP_K)
  * own-record reads use the session account_sk only
  * cross-producer results never include the caller, never include account_sk,
    and expose only PUBLIC_* fields
  * every fact carries a citation {source_type, source_id, label}
  * every call is logged with args, result size, latency and citation IDs
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

from ftusa_data.config import CHALLENGE_TAGS

from .catalog import Catalog
from .store_base import Store

log = logging.getLogger("c3.access")

MAX_LIMIT = 20
MAX_TOP_K = 10
MAX_OWN_PROJECTS = 50
STATUSES = {"completed", "in_progress", "in_planning"}
ENTITY_TYPES = {"cooperative", "smallholder", "estate", "processing_operation", "unknown"}

PUBLIC_PROJECT_FIELDS = ["project_id", "org_name_fictional", "country", "region", "crop", "entity_type", "name",
                         "description", "reason", "challenge_tags", "status", "start_year"]
PUBLIC_PRODUCER_FIELDS = ["display_id", "org_name_fictional", "country", "region", "primary_crop", "entity_type",
                          "project_count"]
OWN_PROFILE_FIELDS = ["display_id", "org_name_fictional", "entity_type", "org_level", "primary_crop", "crops", "country",
                      "region", "primary_language", "applicable_standard", "certification_scope", "project_count"]
OWN_PROJECT_FIELDS = ["project_id", "name", "description", "reason", "primary_goal", "challenge_tags", "primary_tag",
                      "subcategory", "status", "start_date", "end_date", "country", "region"]
ENV_ONLY_NOTE = "Premium project data covers Environmental projects only."

QUERY_FILTERS = {
    "projects": {"country", "primary_tag", "crop", "status", "start_year_from"},
    "producers": {"country", "primary_crop", "entity_type"},
}


@dataclass(frozen=True)
class Session:
    account_sk: str


def err(code: str, message: str, **extra) -> dict:
    return {"error": code, "message": message, **extra}


def _cite(source_type: str, source_id: str, label: str) -> dict:
    return {"source_type": source_type, "source_id": source_id, "label": label}


def _pick(d: dict, fields: list[str]) -> dict:
    return {k: d.get(k) for k in fields if d.get(k) not in (None, "", [])}


@dataclass
class DataAccess:
    store: Store
    catalog: Catalog
    call_log: list[dict] = field(default_factory=list)

    # ------------------------------------------------------------------ logging
    def _log(self, tool: str, session: Session | None, args: dict, result: dict, t0: float | None = None):
        t0 = t0 if t0 is not None else getattr(self, "_t0", time.perf_counter())  # latency only
        cites = _collect_citations(result)
        rec = {"tool": tool, "session": session.account_sk if session else None, "args": args,
               "error": result.get("error") if isinstance(result, dict) else None,
               "n_results": len(result.get("results", result.get("projects", []))) if isinstance(result, dict) else None,
               "citation_ids": cites, "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
        self.call_log.append(rec)
        log.info(json.dumps(rec, default=str))
        return result

    # ------------------------------------------------------------------ own record
    def producer_record(self, session: Session | None, include_all_survey_years: bool = False) -> dict:
        t0 = self._t0 = time.perf_counter()  # noqa: F841
        args = {"include_all_survey_years": include_all_survey_years}
        if session is None or not session.account_sk:
            return self._log("get_producer_record", session, args, err("no_session_producer", "No producer in session."))
        p = self.store.get_producer(session.account_sk)
        if p is None:
            return self._log("get_producer_record", session, args,
                             err("no_session_producer", "Session producer not found."))
        label = f"{p['org_name_fictional']} producer record"
        profile = _pick(p, OWN_PROFILE_FIELDS) | {"citation": _cite("producer_record", p["account_sk"], label)}
        projects = []
        for pr in self.store.list_projects(session.account_sk, MAX_OWN_PROJECTS):
            if pr["account_sk"] != session.account_sk:  # belt and braces
                continue
            projects.append(_pick(pr, OWN_PROJECT_FIELDS) | {
                "citation": _cite("producer_record", pr["project_id"], f"Own Premium project: {pr['name']}")})
        notes = [ENV_ONLY_NOTE]
        if p.get("has_survey"):
            years = self.store.list_surveys(session.account_sk) if include_all_survey_years else [p["survey_latest"]]
            survey = [self._shape_survey(s) for s in years if s]
            survey = survey if include_all_survey_years else (survey[0] if survey else None)
        else:
            survey = None
            notes.append("No household survey data for this producer.")
        if not projects:
            notes.append("No Premium projects on record for this producer.")
        out = {"profile": profile, "projects": projects, "survey": survey, "coverage_notes": notes}
        return self._log("get_producer_record", session, args, out)

    @staticmethod
    def _shape_survey(s: dict) -> dict:
        metrics = {k: v for k, v in s["metrics"].items() if v.get("pct") is not None}
        suppressed = sorted(k for k, v in s["metrics"].items() if v.get("pct") is None and v.get("n", 0) > 0)
        return {"survey_year": s["survey_year"], "n_responses": s["n_responses"], "metrics": metrics,
                "top_choices": {k: v for k, v in s.get("top_choices", {}).items() if v},
                "suppressed_small_n": suppressed,
                "citation": _cite("survey_summary", s["summary_id"],
                                  f"Household survey {s['survey_year']} (n={s['n_responses']}, aggregated)")}

    # ------------------------------------------------------------------ peers
    def similar_projects(self, session: Session | None, challenge: str, tags: list[str] | None = None,
                         same_crop: bool = True, same_entity_type: bool = False, top_k: int = 5) -> dict:
        t0 = self._t0 = time.perf_counter()  # noqa: F841
        args = {"challenge": challenge, "tags": tags, "same_crop": same_crop, "same_entity_type": same_entity_type,
                "top_k": top_k}
        if session is None or not session.account_sk:
            return self._log("find_similar_projects", session, args, err("no_session_producer", "No producer in session."))
        me = self.store.get_producer(session.account_sk)
        if me is None:
            return self._log("find_similar_projects", session, args, err("no_session_producer", "Session producer not found."))
        if not isinstance(top_k, int) or not 1 <= top_k <= MAX_TOP_K:
            return self._log("find_similar_projects", session, args,
                             err("bad_top_k", f"top_k must be an integer 1..{MAX_TOP_K}"))
        bad = [t for t in (tags or []) if t not in CHALLENGE_TAGS]
        if bad:
            return self._log("find_similar_projects", session, args,
                             err("unknown_tag", f"Unknown tags {bad}", allowed=CHALLENGE_TAGS))
        if not (challenge or "").strip():
            return self._log("find_similar_projects", session, args, err("empty_challenge", "Describe the challenge."))

        def run(use_crop: bool, use_entity: bool):
            conds = [{"account_sk": {"$ne": session.account_sk}}]
            if use_crop and me.get("primary_crop"):
                conds.append({"crop": {"$eq": me["primary_crop"]}})
            if use_entity and me.get("entity_type") not in (None, "unknown"):
                conds.append({"entity_type": {"$eq": me["entity_type"]}})
            if tags:
                conds.append({"primary_tag": {"$in": list(tags)}})
            hits = self.store.vector_search(challenge, {"$and": conds}, top_k * 3)
            hits = [h for h in hits if h[2].get("account_sk") != session.account_sk]  # SCOPE-4 re-check
            return hits

        relaxed = []
        hits = run(same_crop, same_entity_type)
        if len(hits) < 2 and same_entity_type:
            relaxed.append("entity_type")
            hits = run(same_crop, False)
        if len(hits) < 2 and same_crop:
            relaxed.append("crop")
            hits = run(False, False)
        score = {k: s for k, s, _ in hits}
        keys = [(m["account_sk"], k) for k, _, m in hits]
        items = [p for p in self.store.batch_get_projects(keys)
                 if p["account_sk"] != session.account_sk and p.get("is_peer_eligible") and not p.get("pii_flag")]
        items.sort(key=lambda p: -score.get(p["project_id"], 0))
        results = [self._shape_peer(p) | {"similarity": round(score[p["project_id"]], 3)} for p in items[:top_k]]
        notes = [ENV_ONLY_NOTE]
        if relaxed:
            notes.append(f"Few close matches; relaxed: {', '.join(relaxed)}.")
        if not results:
            notes.append("No comparable projects found.")
        return self._log("find_similar_projects", session, args,
                         {"results": results, "relaxed": relaxed, "coverage_notes": notes})

    @staticmethod
    def _shape_peer(p: dict) -> dict:
        return _pick(p, PUBLIC_PROJECT_FIELDS) | {"citation": _cite(
            "peer_project", p["project_id"], f"{p.get('org_name_fictional')}, {p.get('country')}: {p['name']}")}

    # ------------------------------------------------------------------ query
    def query(self, session: Session | None, dataset: str, filters: dict | None, limit: int | None) -> dict:
        t0 = self._t0 = time.perf_counter()  # noqa: F841
        args = {"dataset": dataset, "filters": filters, "limit": limit}
        L = lambda r: self._log("query", session, args, r)  # noqa: E731
        if session is None or not session.account_sk:
            return L(err("no_session_producer", "No producer in session."))
        if dataset not in QUERY_FILTERS:
            return L(err("unknown_dataset", f"query supports {sorted(QUERY_FILTERS)}", allowed=sorted(QUERY_FILTERS)))
        if limit is None or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
            return L(err("bad_limit", f"limit is required and must be an integer 1..{MAX_LIMIT}"))
        filters = dict(filters or {})
        unknown = set(filters) - QUERY_FILTERS[dataset]
        if unknown:
            return L(err("unknown_filter", f"Unknown filters {sorted(unknown)}", allowed=sorted(QUERY_FILTERS[dataset])))
        caller = ("account_sk", "ne", session.account_sk)

        if dataset == "projects":
            tag, country = filters.get("primary_tag"), filters.get("country")
            if tag is not None and tag not in CHALLENGE_TAGS:
                return L(err("unknown_tag", f"Unknown tag {tag!r}", allowed=CHALLENGE_TAGS))
            if filters.get("status") is not None and filters["status"] not in STATUSES:
                return L(err("unknown_status", "Unknown status", allowed=sorted(STATUSES)))
            if not (tag or country):
                return L(err("needs_indexed_filter", "projects query needs 'country' or 'primary_tag'"))
            extra = [caller]
            for k in ("crop", "status"):
                if filters.get(k) is not None and not (k == "crop" and not country):
                    extra.append((k, "eq", filters[k]))
            if filters.get("start_year_from") is not None:
                extra.append(("start_year", "ge", int(filters["start_year_from"])))
            if country:
                rows = self.store.query_projects("country", country, f"{tag}#" if tag else None, extra, limit)
            else:
                prefix = f"{filters['crop']}#" if filters.get("crop") else None
                rows = self.store.query_projects("tag", tag, prefix, extra, limit)
            rows = [r for r in rows if r["account_sk"] != session.account_sk and r.get("is_peer_eligible")]
            results = [self._shape_peer(r) for r in rows[:limit]]
            return L({"results": results, "coverage_notes": [ENV_ONLY_NOTE]})

        if not filters.get("country"):
            return L(err("needs_indexed_filter", "producers query needs 'country'"))
        if filters.get("entity_type") is not None and filters["entity_type"] not in ENTITY_TYPES:
            return L(err("unknown_entity_type", "Unknown entity_type", allowed=sorted(ENTITY_TYPES)))
        extra = [caller] + ([("entity_type", "eq", filters["entity_type"])] if filters.get("entity_type") else [])
        prefix = f"{filters['primary_crop']}#" if filters.get("primary_crop") else None
        rows = [r for r in self.store.query_producers(filters["country"], prefix, extra, limit)
                if r["account_sk"] != session.account_sk]
        results = [_pick(r, PUBLIC_PRODUCER_FIELDS) | {"citation": _cite(
            "producer_directory", r["display_id"], f"{r['org_name_fictional']} (directory entry)")} for r in rows[:limit]]
        return L({"results": results, "coverage_notes": []})

    # ------------------------------------------------------------------ catalog
    def describe(self, name: str) -> dict:
        t0 = self._t0 = time.perf_counter()  # noqa: F841
        return self._log("describe_dataset", None, {"name": name}, self.catalog.describe(name))


def _collect_citations(obj) -> list[str]:
    out = []
    if isinstance(obj, dict):
        c = obj.get("citation")
        if isinstance(c, dict) and "source_id" in c:
            out.append(c["source_id"])
        for k, v in obj.items():
            if k != "citation":
                out += _collect_citations(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _collect_citations(v)
    return out
