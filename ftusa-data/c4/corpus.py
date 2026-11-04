"""Standards corpus: load parsed clauses, decide which apply to a producer, build retrieval text.

Input is `standards/standard_clauses.jsonl` from Stage A (ftusa_data.standards).

Applicability (all derived from trusted producer context, never from the model):
  * standard   APS for farms (cooperative / smallholder / estate / unknown), FPS for processing_operation;
               the clause's own `applies_to` is the source of truth.
  * amendments variants (`is_variant`) are shown only when one of their `show_for_amendments` applies;
               base clauses listing an active amendment in `hide_for_amendments` are hidden.
               The only amendment derived automatically is "Cocoa or Palm producer" (from crop).
               Others (Coffee Producer GCP, US Amendment, PMT Adaptation, ...) need facts we do not
               hold, so they are off unless passed explicitly.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ftusa_data.config import CHALLENGE_TAGS, KEYWORD_TAGS, MAX_TAGS

LANGS = ("en", "es", "fr")
INTENT_CHARS = 600
_KW = {t: re.compile(p, re.I) for t, p in KEYWORD_TAGS.items()}
CROP_AMENDMENTS = {
    "cocoa": "Cocoa or Palm producer",
    "cacao": "Cocoa or Palm producer",
    "palm": "Cocoa or Palm producer",
    "palm oil": "Cocoa or Palm producer",
}


def _split(v) -> set[str]:
    if not v:
        return set()
    return {s.strip() for s in str(v).split(";") if s.strip()}


@dataclass(frozen=True)
class Clause:
    clause_id: str
    standard: str
    code: str
    module: str
    sub_module: str
    objective: str
    question: dict           # lang -> text (en always present)
    intent: dict             # lang -> text
    applies_to: frozenset
    is_variant: bool
    show_for: frozenset
    hide_for: frozenset
    timeline: str | None
    priority: bool
    tags: tuple = field(default=())

    def text(self, lang: str = "en") -> str:
        """Retrieval text in one language (falls back to English pieces)."""
        q = self.question.get(lang) or self.question["en"]
        i = self.intent.get(lang) or self.intent.get("en", "")
        return f"{self.module}. {self.sub_module}. {self.objective}. {q} {i}"

    def embed_text(self) -> str:
        return (f"{self.standard} {self.code} | {self.module} | {self.sub_module} | Objective: {self.objective} | "
                f"Requirement: {self.question['en']} | Intent: {self.intent.get('en', '')}")[:8000]

    def visible(self, amendments: set[str]) -> bool:
        if self.is_variant and not (self.show_for & amendments):
            return False
        return not (self.hide_for & amendments)


def tag_clause(text: str) -> tuple:
    """Same keyword rules as Premium projects (ftusa_data.config.KEYWORD_TAGS), up to MAX_TAGS."""
    hits = {t: len(rx.findall(text)) for t, rx in _KW.items()}
    ranked = sorted((t for t, n in hits.items() if n), key=lambda t: (-hits[t], CHALLENGE_TAGS.index(t)))
    return tuple(ranked[:MAX_TAGS])


def _row_to_clause(r: dict) -> Clause:
    q = {"en": r.get("question") or ""}
    i = {"en": r.get("intent") or ""}
    for lang in ("es", "fr"):
        if r.get(f"question_{lang}"):
            q[lang] = r[f"question_{lang}"]
        if r.get(f"intent_{lang}"):
            i[lang] = r[f"intent_{lang}"]
    applies = frozenset(s for s in str(r.get("applies_to") or "").split("|") if s)
    en = f"{r.get('objective') or ''} {q['en']} {i['en']}"
    return Clause(
        clause_id=r["clause_id"], standard=r["standard"], code=r.get("code") or r["clause_id"],
        module=r.get("module") or "", sub_module=r.get("sub_module") or "", objective=r.get("objective") or "",
        question=q, intent=i, applies_to=applies, is_variant=bool(r.get("is_variant")),
        show_for=frozenset(_split(r.get("show_for_amendments"))), hide_for=frozenset(_split(r.get("hide_for_amendments"))),
        timeline=r.get("timeline"), priority=bool(r.get("priority")), tags=tag_clause(en),
    )


def load_clauses(path: str | Path) -> list[Clause]:
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    clauses = [_row_to_clause(r) for r in rows if r.get("clause_id") and r.get("question")]
    ids = [c.clause_id for c in clauses]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate clause_id in standards corpus")
    return clauses


def applicable_standard(entity_type: str | None) -> str:
    return "FPS" if (entity_type or "").strip().lower() == "processing_operation" else "APS"


def amendments_for(crop: str | None, extra: set[str] | None = None) -> set[str]:
    out = set(extra or ())
    a = CROP_AMENDMENTS.get((crop or "").strip().lower())
    if a:
        out.add(a)
    return out


def applies(c: Clause, entity_type: str | None, amendments: set[str]) -> bool:
    et = (entity_type or "unknown").strip().lower() or "unknown"
    if c.standard != applicable_standard(et):
        return False
    if c.applies_to and et not in c.applies_to:
        return False
    return c.visible(amendments)
