"""Retrievers. Both return [(clause_id, score)] best first; all scoping happens in access.StandardsAccess.

LexicalRetriever       offline BM25 over EN + ES/FR clause text, with a small ES/FR -> EN glossary so a
                       Spanish or French topic still reaches FPS clauses (which have English text only).
S3VectorsRetriever     Titan Text Embeddings v2 + S3 Vectors index "standards" (same bucket as C3).
                       NOT RUN in the build environment (no AWS); load with `python -m c4.load`.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from typing import Protocol

from .corpus import LANGS, Clause

TITAN_MODEL = "amazon.titan-embed-text-v2:0"
DIM = 1024
INDEX = "standards"
MAX_VECTOR_K = 30

_STOP = set("""
a an and are as at be by for from has have in is it its of on or shall that the their this to with which who
whom will be been can may must not all any each other such than these those into per
el la los las de del y o en un una que por para con se su sus al es lo como mas
le les des du et ou un une que qui pour par avec sur dans au aux ce ces son sa ses est
""".split())

# Topic words a producer is likely to use, mapped to the English the standards use.
GLOSSARY = {
    "agua": "water", "eau": "water", "riego": "irrigation", "irrigation": "irrigation", "sequia": "drought",
    "secheresse": "drought", "lluvia": "rain", "pluie": "rain", "clima": "climate", "climat": "climate",
    "suelo": "soil", "sol": "soil", "erosion": "erosion", "fertilizante": "fertilizer", "engrais": "fertilizer",
    "plaga": "pest", "plagas": "pests", "ravageur": "pest", "plaguicida": "pesticide", "pesticida": "pesticide",
    "pesticide": "pesticide", "agroquimico": "agrochemical", "quimicos": "chemicals", "chimiques": "chemicals",
    "bosque": "forest", "foret": "forest", "deforestacion": "deforestation", "deforestation": "deforestation",
    "arboles": "trees", "arbres": "trees", "biodiversidad": "biodiversity", "biodiversite": "biodiversity",
    "residuos": "waste", "basura": "waste", "dechets": "waste", "trabajadores": "workers", "trabajador": "worker",
    "travailleurs": "workers", "salario": "wage", "salarios": "wages", "salaire": "wage", "trabajo": "work",
    "travail": "work", "infantil": "child", "ninos": "children", "enfants": "children", "mujeres": "women",
    "femmes": "women", "genero": "gender", "jovenes": "youth", "jeunes": "youth", "salud": "health",
    "sante": "health", "seguridad": "safety", "securite": "safety", "accidente": "accident", "capacitacion": "training",
    "formacion": "training", "formation": "training", "educacion": "education", "education": "education",
    "credito": "credit", "prestamo": "loan", "pret": "loan", "ahorro": "savings", "epargne": "savings",
    "prima": "premium", "prime": "premium", "comite": "committee", "asamblea": "assembly", "assemblee": "assembly",
    "precio": "price", "prix": "price", "mercado": "market", "marche": "market", "contrato": "contract",
    "contrat": "contract", "discriminacion": "discrimination", "acoso": "harassment", "harcelement": "harassment",
    "queja": "grievance", "quejas": "grievances", "plainte": "grievance", "vivienda": "housing", "logement": "housing",
    "cooperativa": "cooperative", "socios": "members", "membres": "members", "trazabilidad": "traceability",
    "tracabilite": "traceability", "cosecha": "harvest", "recolte": "harvest",
}


def fold(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(ch))


def tokens(s: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9]+", fold(s)):
        if len(w) < 3 or w in _STOP:
            continue
        out.append(w[:7])  # crude stem: training/trainings, worker/workers, fertilizer/fertilizers
    return out


def query_tokens(q: str) -> list[str]:
    toks = tokens(q)
    for w in re.findall(r"[a-z0-9]+", fold(q)):
        if w in GLOSSARY:
            toks += tokens(GLOSSARY[w])
    return toks


class Retriever(Protocol):
    def search(self, query: str, standard: str, top_k: int) -> list[tuple[str, float]]: ...


class LexicalRetriever:
    """BM25 per clause; one document = the clause text in all its languages."""

    def __init__(self, clauses: list[Clause], k1: float = 1.4, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = {}
        self.std = {}
        for c in clauses:
            text = " ".join(c.text(lang) for lang in LANGS if lang == "en" or lang in c.question)
            self.docs[c.clause_id] = Counter(tokens(text))
            self.std[c.clause_id] = c.standard
        self.avg = sum(sum(d.values()) for d in self.docs.values()) / max(len(self.docs), 1)
        df = Counter()
        for d in self.docs.values():
            df.update(d.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, standard: str, top_k: int) -> list[tuple[str, float]]:
        q = set(query_tokens(query))
        scores = []
        for cid, d in self.docs.items():
            if self.std[cid] != standard:
                continue
            dl = sum(d.values())
            s = 0.0
            for t in q:
                f = d.get(t)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avg))
            if s > 0:
                scores.append((cid, s))
        scores.sort(key=lambda x: -x[1])
        if not scores:
            return []
        top = scores[0][1]
        return [(cid, round(s / top, 4)) for cid, s in scores[:top_k]]  # 0..1, relative to best


class S3VectorsRetriever:
    def __init__(self, vector_bucket: str, index: str = INDEX, region: str | None = None, session=None,
                 model_id: str = TITAN_MODEL, dim: int = DIM):
        import boto3

        s = session or boto3.Session(region_name=region)
        self.s3v, self.br = s.client("s3vectors"), s.client("bedrock-runtime")
        self.bucket, self.index, self.model_id, self.dim = vector_bucket, index, model_id, dim

    def embed(self, text: str) -> list[float]:
        body = json.dumps({"inputText": text[:8000], "dimensions": self.dim, "normalize": True})
        r = self.br.invoke_model(modelId=self.model_id, body=body, contentType="application/json",
                                 accept="application/json")
        return json.loads(r["body"].read())["embedding"]

    def search(self, query: str, standard: str, top_k: int) -> list[tuple[str, float]]:
        r = self.s3v.query_vectors(vectorBucketName=self.bucket, indexName=self.index,
                                   queryVector={"float32": self.embed(query)}, topK=min(top_k, MAX_VECTOR_K),
                                   filter={"standard": {"$eq": standard}}, returnDistance=True)
        return [(v["key"], round(1.0 - float(v.get("distance", 1.0)), 4)) for v in r.get("vectors", [])]
