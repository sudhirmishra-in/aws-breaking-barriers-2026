"""In-memory Store built from the same items the loader writes (NFR-5).

Vector search uses a local TF-IDF embedder with a small Spanish/French -> English
term map instead of Titan, so tool logic can be tested offline. Semantic quality
is lower than Titan's; correctness rules (filters, bounds, exclusion) are identical.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

from .items import build_all, embed_text
from .store_base import Filter, passes, vector_filter_match

STOP = set("""a an the and or of to in on for with by is are be this that from as at it its their they them
we our was were will can has have been not no all de la el los las y o en con por para del al un una que se su sus
es son le les des et du au aux nos nuestro nuestra hay muy mas""".split())
XLATE = {  # tiny ES/FR -> EN map so local tests can use Spanish queries
    "agua": "water", "lluvia": "rain", "lluvias": "rain", "sequia": "drought", "riego": "irrigation",
    "bombeo": "pumping", "bomba": "pump", "solar": "solar", "energia": "energy", "suelo": "soil", "suelos": "soil",
    "erosion": "erosion", "abono": "compost", "compost": "compost", "reforestacion": "reforestation",
    "arboles": "trees", "bosque": "forest", "basura": "waste", "residuos": "waste", "reciclaje": "recycling",
    "plaga": "pest", "plagas": "pest", "roya": "rust", "precio": "price", "cosecha": "harvest", "clima": "climate",
    "calor": "heat", "eau": "water", "pluie": "rain", "secheresse": "drought", "sol": "soil", "arbres": "trees",
    "dechets": "waste", "cafe": "coffee", "cacao": "cocoa", "aguas": "water", "mieles": "honey", "tanque": "tank",
    "tanques": "tank", "paneles": "panels", "filtros": "filters", "potable": "drinking",
}


def tokenize(s: str) -> list[str]:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    out = []
    for t in re.findall(r"[a-z0-9]+", s):
        if t in STOP or len(t) < 3:
            continue
        t = XLATE.get(t, t)
        out.append(t[:-1] if len(t) > 4 and t.endswith("s") else t)
    return out


class LexicalEmbedder:
    def __init__(self, corpus: list[str]):
        docs = [Counter(tokenize(d)) for d in corpus]
        n = len(docs)
        df = Counter(t for d in docs for t in d)
        self.idf = {t: math.log((1 + n) / (1 + f)) + 1 for t, f in df.items()}

    def embed(self, text: str) -> dict[str, float]:
        tf = Counter(tokenize(text))
        v = {t: c * self.idf.get(t, 1.0) for t, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    @staticmethod
    def cosine(a: dict, b: dict) -> float:
        if len(a) > len(b):
            a, b = b, a
        return sum(x * b.get(t, 0.0) for t, x in a.items())


class InMemoryStore:
    def __init__(self, built: dict):
        self.producers = {p["account_sk"]: p for p in built["producers"]}
        self.projects = {(p["account_sk"], p["project_id"]): p for p in built["projects"]}
        self.surveys: dict[str, list[dict]] = {}
        for s in built["survey_summaries"]:
            self.surveys.setdefault(s["account_sk"], []).append(s)
        self.vectors = built["vectors"]
        self.embedder = LexicalEmbedder([v["text"] for v in self.vectors])
        self._vec = [(v["key"], self.embedder.embed(v["text"]), v["metadata"]) for v in self.vectors]

    @classmethod
    def from_tables(cls, tables: Path, **kw) -> "InMemoryStore":
        return cls(build_all(tables, **kw))

    # ------------------------------------------------------------------ Store protocol
    def get_producer(self, account_sk):
        return self.producers.get(account_sk)

    def list_projects(self, account_sk, limit):
        items = sorted((p for (a, _), p in self.projects.items() if a == account_sk), key=lambda p: p["project_id"])
        return items[:limit]

    def list_surveys(self, account_sk):
        return sorted(self.surveys.get(account_sk, []), key=lambda s: s["survey_year"])

    def batch_get_projects(self, keys):
        return [self.projects[k] for k in keys if k in self.projects]

    def query_projects(self, index, pk, sk_prefix, filters: list[Filter], limit):
        pk_attr, sk_attr = {"country": ("gsi_country", "gsi_country_sk"), "tag": ("gsi_primary_tag", "gsi_tag_sk")}[index]
        items = [p for p in self.projects.values() if p.get(pk_attr) == pk
                 and (sk_prefix is None or str(p.get(sk_attr, "")).startswith(sk_prefix))]
        items.sort(key=lambda p: p[sk_attr], reverse=(index == "country"))  # newest first on the country index
        return [p for p in items if passes(p, filters)][:limit]

    def query_producers(self, country, sk_prefix, filters, limit):
        items = [p for p in self.producers.values() if p.get("country") == country
                 and (sk_prefix is None or p["gsi_crop_sk"].startswith(sk_prefix))]
        items.sort(key=lambda p: p["gsi_crop_sk"])
        return [p for p in items if passes(p, filters)][:limit]

    def vector_search(self, text, vfilter, top_k):
        q = self.embedder.embed(text)
        scored = [(k, self.embedder.cosine(q, v), m) for k, v, m in self._vec if vector_filter_match(m, vfilter)]
        scored = [s for s in scored if s[1] > 0]
        return sorted(scored, key=lambda s: -s[1])[:top_k]


__all__ = ["InMemoryStore", "LexicalEmbedder", "embed_text"]
