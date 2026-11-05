"""Standards access layer: the only code the tool calls.

Output keeps main's evidence shape (`kind`, `topic`, `status`, `note`; see
agent/app/exchange/tools.py::evidence_unavailable) and adds `clauses` when status is "ok".

status  "ok"           1..top_k clauses that apply to this producer
        "no_match"     nothing relevant found; the agent must not cite any clause
        "unavailable"  empty topic or backend error; same meaning as main's placeholder

Guarantees:
  * scope comes from the trusted producer (entity type, crop), never from the model
  * every returned clause applies to that producer's standard and amendments
  * bounded: top_k <= MAX_TOP_K, topic <= 200 chars, intent excerpt <= INTENT_CHARS
  * every clause carries a citation; every call is logged with args, size, latency, citation IDs
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

from .corpus import INTENT_CHARS, Clause, amendments_for, applicable_standard, applies
from .retriever import MAX_VECTOR_K, Retriever

log = logging.getLogger("c4.access")

KIND = "standards"
MAX_TOP_K = 5
DEFAULT_TOP_K = 3
TOPIC_CHARS = 200

NOTE_OK = ("Use only these clauses and cite each by clause_id. They state what the standard requires; they do not "
           "say whether this producer complies, and certification status is out of scope.")
NOTE_NO_MATCH = ("No standards clause matched this topic for this producer's standard. Do not quote or paraphrase "
                 "any standards clause; say none was found.")
NOTE_UNAVAILABLE = ("Standards search is not available right now. Do not state any standards clause. Tell the "
                    "producer this information is not available yet.")


def _excerpt(s: str, n: int = INTENT_CHARS) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


@dataclass
class StandardsAccess:
    clauses: list[Clause]
    retriever: Retriever
    min_score: float = 0.0
    call_log: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.by_id = {c.clause_id: c for c in self.clauses}

    def _log(self, args: dict, out: dict, t0: float) -> dict:
        rec = {"tool": "get_standards_clause", "args": args, "status": out["status"],
               "n_results": len(out.get("clauses", [])),
               "citation_ids": [c["citation"]["source_id"] for c in out.get("clauses", [])],
               "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
        self.call_log.append(rec)
        log.info(json.dumps(rec, default=str))
        return out

    def get_standards_clause(self, producer, topic: str, language: str = "en", top_k: int = DEFAULT_TOP_K,
                             extra_amendments: set[str] | None = None) -> dict:
        """`producer` is main's ProducerRef (or anything with .entityType and .crop)."""
        t0 = time.perf_counter()
        topic = " ".join((topic or "").split())[:TOPIC_CHARS]
        entity, crop = getattr(producer, "entityType", None), getattr(producer, "crop", None)
        standard = applicable_standard(entity)
        amendments = amendments_for(crop, extra_amendments)
        top_k = max(1, min(int(top_k or DEFAULT_TOP_K), MAX_TOP_K))
        lang = language if language in ("en", "es", "fr") else "en"
        args = {"topic": topic, "standard": standard, "amendments": sorted(amendments), "language": lang, "top_k": top_k}
        base = {"kind": KIND, "topic": topic, "standard": standard}

        if not topic:
            return self._log(args, base | {"status": "unavailable", "note": NOTE_UNAVAILABLE}, t0)
        try:
            hits = self.retriever.search(topic, standard, min(top_k * 6, MAX_VECTOR_K))
        except Exception as e:  # backend down: degrade to main's placeholder, never invent
            log.warning("standards retriever failed: %s", e)
            return self._log(args, base | {"status": "unavailable", "note": NOTE_UNAVAILABLE}, t0)

        out = []
        for cid, score in hits:
            c = self.by_id.get(cid)
            if c is None or score < self.min_score or not applies(c, entity, amendments):
                continue
            out.append(self._shape(c, score, lang))
            if len(out) == top_k:
                break
        if not out:
            return self._log(args, base | {"status": "no_match", "note": NOTE_NO_MATCH}, t0)
        return self._log(args, base | {"status": "ok", "note": NOTE_OK, "clauses": out}, t0)

    @staticmethod
    def _shape(c: Clause, score: float, lang: str) -> dict:
        text_lang = lang if lang in c.question else "en"
        return {
            "clause_id": c.clause_id,
            "standard": c.standard,
            "module": c.module,
            "objective": c.objective,
            "requirement": c.question[text_lang],
            "intent": _excerpt(c.intent.get(text_lang) or c.intent.get("en", "")),
            "text_language": text_lang,
            "timeline": c.timeline,
            "priority": c.priority,
            "challenge_tags": list(c.tags),
            "score": score,
            "citation": {"source_type": "standard_clause", "source_id": c.clause_id,
                         "label": f"Fair Trade USA {c.standard} {c.code}"},
        }
