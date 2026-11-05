"""Flag possible PII in free text. Never redacts (FTUSA policy: flag for human review).

Offline layer: regex for emails, phone numbers and "title + capitalized name".
Optional layer: Amazon Comprehend DetectPiiEntities (--comprehend), which is
what the grant names for production. Text is sent in <=4,500-byte chunks.
"""
from __future__ import annotations

import re

import pandas as pd

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"(?<![\w.,/])\+?\(?\d{2,4}\)?[\s-]?\d{3,4}[\s-]?\d{3,4}(?![\w.,/])")
TITLE_NAME = re.compile(r"\b(?:Mr|Mrs|Ms|Sr|Sra|Srta|Don|Doña|Dr|Ing|Lic)\.?\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)?")
YEARISH = re.compile(r"^(19|20)\d{2}[\s-](19|20)\d{2}$")

TEXT_COLS = ["name", "description", "reason", "primary_goal", "description_original"]


def regex_pii(text: str) -> list[str]:
    found = set()
    if EMAIL.search(text):
        found.add("email")
    for m in PHONE.finditer(text):
        s = m.group(0)
        if sum(ch.isdigit() for ch in s) >= 9 and not YEARISH.match(s.strip()):
            found.add("phone")
    if TITLE_NAME.search(text):
        found.add("person_title")
    return sorted(found)


def comprehend_pii(texts: list[str], region: str | None = None, min_score: float = 0.8) -> list[list[str]]:
    import boto3

    c = boto3.client("comprehend", region_name=region)
    out = []
    for t in texts:
        types = set()
        b = t.encode("utf-8")
        for i in range(0, len(b), 4500):
            chunk = b[i:i + 4500].decode("utf-8", errors="ignore")
            if chunk.strip():
                for e in c.detect_pii_entities(Text=chunk, LanguageCode="en")["Entities"]:
                    if e["Score"] >= min_score:
                        types.add(e["Type"].lower())
        out.append(sorted(types))
    return out


def apply(projects: pd.DataFrame, use_comprehend: bool = False, region: str | None = None) -> pd.DataFrame:
    p = projects.copy()
    texts = [" ".join(str(r[c]) for c in TEXT_COLS if isinstance(r.get(c), str)) for r in p.to_dict("records")]
    types = [regex_pii(t) for t in texts]
    if use_comprehend:
        types = [sorted(set(a) | set(b)) for a, b in zip(types, comprehend_pii(texts, region))]
    p["pii_types"] = ["|".join(t) for t in types]
    p["pii_flag"] = [bool(t) for t in types]
    return p
