"""Load standards clauses into the S3 Vectors index "standards" (same bucket as C3's peer-projects).

    python -m c4.load --clauses out/standards/standard_clauses.jsonl --dry-run --dump out/load_dryrun
    python -m c4.load --clauses out/standards/standard_clauses.jsonl --region us-east-1 \
        --vector-bucket ftusa-c3-vectors --create

One vector per clause (key = clause_id), embedded from the English clause text with Titan Text
Embeddings v2 (multilingual, so ES/FR topics still match). Filterable metadata: standard, is_variant.
Re-runs embed only clauses whose text changed and delete clauses no longer in the file.
The AWS path is NOT RUN in the build environment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .corpus import load_clauses
from .retriever import DIM, INDEX, TITAN_MODEL

NON_FILTERABLE = ["module", "text_sha1"]


def build_vectors(path) -> list[dict]:
    out = []
    for c in load_clauses(path):
        text = c.embed_text()
        out.append({"key": c.clause_id, "text": text, "metadata": {
            "standard": c.standard, "is_variant": c.is_variant, "module": c.module[:200],
            "text_sha1": hashlib.sha1(text.encode()).hexdigest()}})
    return out


def manifest(vectors: list[dict], mode: str, extra: dict | None = None) -> dict:
    by_std = {}
    for v in vectors:
        by_std[v["metadata"]["standard"]] = by_std.get(v["metadata"]["standard"], 0) + 1
    return {"component": "c4", "index": INDEX, "mode": mode, "vectors": len(vectors), "by_standard": by_std,
            "corpus_sha1": hashlib.sha1("".join(v["metadata"]["text_sha1"] for v in vectors).encode()).hexdigest(),
            **(extra or {})}


class AwsLoader:
    def __init__(self, region, vector_bucket, index=INDEX, model_id=TITAN_MODEL, dim=DIM):
        import boto3

        s = boto3.Session(region_name=region)
        self.s3v, self.br = s.client("s3vectors"), s.client("bedrock-runtime")
        self.bucket, self.index, self.model_id, self.dim = vector_bucket, index, model_id, dim

    def create(self):
        try:
            self.s3v.create_vector_bucket(vectorBucketName=self.bucket)
        except self.s3v.exceptions.ConflictException:
            pass
        try:
            self.s3v.create_index(vectorBucketName=self.bucket, indexName=self.index, dataType="float32",
                                  dimension=self.dim, distanceMetric="cosine",
                                  metadataConfiguration={"nonFilterableMetadataKeys": NON_FILTERABLE})
        except self.s3v.exceptions.ConflictException:
            pass

    def embed(self, text: str) -> list[float]:
        body = json.dumps({"inputText": text[:8000], "dimensions": self.dim, "normalize": True})
        r = self.br.invoke_model(modelId=self.model_id, body=body, contentType="application/json",
                                 accept="application/json")
        return json.loads(r["body"].read())["embedding"]

    def existing(self) -> dict[str, dict]:
        out, token = {}, None
        while True:
            kw = dict(vectorBucketName=self.bucket, indexName=self.index, returnMetadata=True, maxResults=500)
            if token:
                kw["nextToken"] = token
            r = self.s3v.list_vectors(**kw)
            out.update({v["key"]: v.get("metadata", {}) for v in r.get("vectors", [])})
            token = r.get("nextToken")
            if not token:
                return out

    def load(self, vectors: list[dict]) -> dict:
        have, batch, embedded, skipped = self.existing(), [], 0, 0
        for v in vectors:
            if have.get(v["key"], {}).get("text_sha1") == v["metadata"]["text_sha1"]:
                skipped += 1
                continue
            batch.append({"key": v["key"], "data": {"float32": self.embed(v["text"])}, "metadata": v["metadata"]})
            embedded += 1
            if len(batch) == 100:
                self.s3v.put_vectors(vectorBucketName=self.bucket, indexName=self.index, vectors=batch)
                batch = []
        if batch:
            self.s3v.put_vectors(vectorBucketName=self.bucket, indexName=self.index, vectors=batch)
        keep = {v["key"] for v in vectors}
        stale = [k for k in have if k not in keep]
        for i in range(0, len(stale), 100):
            self.s3v.delete_vectors(vectorBucketName=self.bucket, indexName=self.index, keys=stale[i:i + 100])
        return {"embedded": embedded, "unchanged": skipped, "deleted": len(stale)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clauses", default="out/standards/standard_clauses.jsonl")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dump", default="out/load_dryrun")
    ap.add_argument("--region")
    ap.add_argument("--vector-bucket", default="ftusa-c3-vectors")
    ap.add_argument("--vector-index", default=INDEX)
    ap.add_argument("--embedding-model", default=TITAN_MODEL)
    ap.add_argument("--dim", type=int, default=DIM)
    ap.add_argument("--create", action="store_true", help="create the vector bucket / index if missing")
    a = ap.parse_args(argv)

    vectors = build_vectors(a.clauses)
    if a.dry_run:
        d = Path(a.dump)
        d.mkdir(parents=True, exist_ok=True)
        (d / "standards_vectors.jsonl").write_text(
            "\n".join(json.dumps(v, ensure_ascii=False, sort_keys=True) for v in vectors) + "\n", encoding="utf-8")
        m = manifest(vectors, "dry-run")
        (d / "standards_manifest.json").write_text(json.dumps(m, indent=2))
        print(json.dumps(m, indent=1))
        return m
    L = AwsLoader(a.region, a.vector_bucket, a.vector_index, a.embedding_model, a.dim)
    if a.create:
        L.create()
    m = manifest(vectors, "aws", {"vector_stats": L.load(vectors)})
    print(json.dumps(m, indent=1))
    return m


if __name__ == "__main__":
    main()
