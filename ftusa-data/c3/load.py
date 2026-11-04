"""Stage B loader: out/tables -> DynamoDB + S3 Vectors + S3/Athena (LOAD-1..7).

    # offline: build + validate every item and vector payload, write them to disk, no AWS calls
    python -m c3.load --tables out/tables --dry-run --dump out/load_dryrun

    # real load (needs boto3 + credentials)
    python -m c3.load --tables out/tables --region us-east-1 \
        --table-prefix ftusa_c3_ --vector-bucket ftusa-c3-vectors \
        --s3-bucket ftusa-c3-data --athena-output s3://ftusa-c3-data/athena-results/ [--create]

Idempotent (LOAD-6): deterministic keys + upserts; every item/vector is stamped
with load_id = sha1 of the input tables, and anything from a different load_id
that is not in the new input is deleted (stale sweep). Re-running on the same
input therefore changes nothing.

The AWS path is NOT RUN in the build environment (no boto3/AWS). The dry-run path is tested.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from decimal import Decimal
from pathlib import Path

from .items import VECTOR_NON_FILTERABLE, build_all, write_stats

TABLES = {
    "producers": {"keys": [("account_sk", "S", "HASH")],
                  "gsis": [("by_country_crop", [("country", "S", "HASH"), ("gsi_crop_sk", "S", "RANGE")])]},
    "projects": {"keys": [("account_sk", "S", "HASH"), ("project_id", "S", "RANGE")],
                 "gsis": [("peers_by_country_tag", [("gsi_country", "S", "HASH"), ("gsi_country_sk", "S", "RANGE")]),
                          ("peers_by_tag", [("gsi_primary_tag", "S", "HASH"), ("gsi_tag_sk", "S", "RANGE")])]},
    "survey_summaries": {"keys": [("account_sk", "S", "HASH"), ("survey_year", "N", "RANGE")], "gsis": []},
}
ATHENA_TABLES = ["producers", "certifications", "regions", "premium_projects", "survey_summary", "survey_choice_shares"]


def load_id_for(tables: Path) -> str:
    h = hashlib.sha1()
    for f in sorted(Path(tables).rglob("*.csv")):
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:12]


def to_ddb(v):
    """Python -> DynamoDB-safe: floats as Decimal, drop None and empty strings (sparse GSIs need absent attrs)."""
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return Decimal(str(v))
    if isinstance(v, dict):
        return {k: to_ddb(x) for k, x in v.items() if x is not None and x != ""}
    if isinstance(v, list):
        return [to_ddb(x) for x in v if x is not None]
    return v


def prepare(tables: Path) -> dict:
    built = build_all(tables)
    lid = load_id_for(tables)
    for name in ("producers", "projects", "survey_summaries"):
        built[name] = [to_ddb({**i, "load_id": lid}) for i in built[name]]
    for v in built["vectors"]:
        v["metadata"]["load_id"] = lid
    built["load_id"] = lid
    return built


def manifest(built: dict, extra: dict | None = None) -> dict:
    return {"load_id": built["load_id"],
            "tables": {n: {"rows_loaded": len(built[n]), "rows_rejected": len(built["rejects"].get(n, []))}
                       for n in ("producers", "projects", "survey_summaries")},
            "vectors": len(built["vectors"]), "rejects": built["rejects"], **(extra or {})}


# --------------------------------------------------------------------------- AWS
class AwsLoader:
    def __init__(self, region, table_prefix, vector_bucket, vector_index, s3_bucket, athena_output, athena_db):
        import boto3

        self.s = boto3.Session(region_name=region)
        self.ddb = self.s.resource("dynamodb")
        self.ddb_client = self.s.client("dynamodb")
        self.s3v = self.s.client("s3vectors")
        self.bedrock = self.s.client("bedrock-runtime")
        self.s3 = self.s.client("s3")
        self.athena = self.s.client("athena")
        self.prefix, self.vbucket, self.vindex = table_prefix, vector_bucket, vector_index
        self.s3_bucket, self.athena_output, self.athena_db = s3_bucket, athena_output, athena_db

    # -------------------------------------------------- create
    def create(self, dim: int):
        existing = set(self.ddb_client.list_tables()["TableNames"])
        for name, spec in TABLES.items():
            tname = self.prefix + name
            if tname in existing:
                continue
            attrs = {a: t for a, t, _ in spec["keys"]}
            for _, ks in spec["gsis"]:
                attrs.update({a: t for a, t, _ in ks})
            kw = dict(TableName=tname, BillingMode="PAY_PER_REQUEST",
                      KeySchema=[{"AttributeName": a, "KeyType": k} for a, _, k in spec["keys"]],
                      AttributeDefinitions=[{"AttributeName": a, "AttributeType": t} for a, t in attrs.items()])
            if spec["gsis"]:
                kw["GlobalSecondaryIndexes"] = [{"IndexName": g, "Projection": {"ProjectionType": "ALL"},
                                                 "KeySchema": [{"AttributeName": a, "KeyType": k} for a, _, k in ks]}
                                                for g, ks in spec["gsis"]]
            self.ddb_client.create_table(**kw)
            self.ddb_client.get_waiter("table_exists").wait(TableName=tname)
            print(f"created table {tname}")
        try:
            self.s3v.create_vector_bucket(vectorBucketName=self.vbucket)
        except self.s3v.exceptions.ConflictException:
            pass
        try:
            self.s3v.create_index(vectorBucketName=self.vbucket, indexName=self.vindex, dataType="float32",
                                  dimension=dim, distanceMetric="cosine",
                                  metadataConfiguration={"nonFilterableMetadataKeys": VECTOR_NON_FILTERABLE})
        except self.s3v.exceptions.ConflictException:
            pass

    # -------------------------------------------------- dynamodb
    def upsert(self, name: str, items: list[dict]):
        t = self.ddb.Table(self.prefix + name)
        keys = [a for a, _, _ in TABLES[name]["keys"]]
        with t.batch_writer(overwrite_by_pkeys=keys) as bw:
            for i in items:
                bw.put_item(Item=i)

    def sweep(self, name: str, load_id: str, keep: set) -> int:
        t = self.ddb.Table(self.prefix + name)
        keys = [a for a, _, _ in TABLES[name]["keys"]]
        n, start = 0, None
        while True:  # loader-only scan; never on the agent path
            kw = {"ProjectionExpression": ", ".join(keys + ["load_id"])}
            if start:
                kw["ExclusiveStartKey"] = start
            r = t.scan(**kw)
            with t.batch_writer() as bw:
                for i in r.get("Items", []):
                    k = tuple(i[a] for a in keys)
                    if i.get("load_id") != load_id and k not in keep:
                        bw.delete_item(Key={a: i[a] for a in keys})
                        n += 1
            start = r.get("LastEvaluatedKey")
            if not start:
                return n

    # -------------------------------------------------- vectors
    def existing_vectors(self) -> dict[str, dict]:
        out, token = {}, None
        while True:
            kw = dict(vectorBucketName=self.vbucket, indexName=self.vindex, returnMetadata=True, maxResults=500)
            if token:
                kw["nextToken"] = token
            r = self.s3v.list_vectors(**kw)
            for v in r.get("vectors", []):
                out[v["key"]] = v.get("metadata", {})
            token = r.get("nextToken")
            if not token:
                return out

    def embed(self, text: str, model_id: str, dim: int) -> list[float]:
        body = json.dumps({"inputText": text[:8000], "dimensions": dim, "normalize": True})
        r = self.bedrock.invoke_model(modelId=model_id, body=body, contentType="application/json", accept="application/json")
        return json.loads(r["body"].read())["embedding"]

    def load_vectors(self, vectors: list[dict], model_id: str, dim: int) -> dict:
        have = self.existing_vectors()
        batch, embedded, skipped = [], 0, 0
        for v in vectors:
            old = have.get(v["key"])
            if old and old.get("text_sha1") == v["metadata"].get("text_sha1") and old.get("load_id") == v["metadata"]["load_id"]:
                skipped += 1
                continue
            batch.append({"key": v["key"], "data": {"float32": self.embed(v["text"], model_id, dim)},
                          "metadata": v["metadata"]})
            embedded += 1
            if len(batch) == 100:
                self.s3v.put_vectors(vectorBucketName=self.vbucket, indexName=self.vindex, vectors=batch)
                batch = []
        if batch:
            self.s3v.put_vectors(vectorBucketName=self.vbucket, indexName=self.vindex, vectors=batch)
        stale = [k for k in have if k not in {v["key"] for v in vectors}]
        for i in range(0, len(stale), 100):
            self.s3v.delete_vectors(vectorBucketName=self.vbucket, indexName=self.vindex, keys=stale[i:i + 100])
        return {"embedded": embedded, "unchanged": skipped, "deleted": len(stale)}

    # -------------------------------------------------- s3 + athena
    def load_athena(self, tables: Path):
        import pandas as pd

        def run(sql):
            q = self.athena.start_query_execution(QueryString=sql, ResultConfiguration={"OutputLocation": self.athena_output})
            qid = q["QueryExecutionId"]
            while True:
                st = self.athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]["State"]
                if st in ("SUCCEEDED", "FAILED", "CANCELLED"):
                    if st != "SUCCEEDED":
                        raise RuntimeError(f"Athena {st}: {sql[:120]}")
                    return
                time.sleep(1)

        run(f"CREATE DATABASE IF NOT EXISTS {self.athena_db}")
        for name in ATHENA_TABLES:
            f = Path(tables) / name / f"{name}.csv"
            if not f.exists():
                continue
            key = f"c3/tables/{name}/{name}.csv"
            self.s3.upload_file(str(f), self.s3_bucket, key)
            cols = pd.read_csv(f, nrows=0).columns
            ddl_cols = ", ".join(f"`{c}` string" for c in cols)  # OpenCSVSerde reads strings; cast in queries
            run(f"DROP TABLE IF EXISTS {self.athena_db}.{name}")
            run(f"CREATE EXTERNAL TABLE {self.athena_db}.{name} ({ddl_cols}) "
                f"ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde' "
                f"LOCATION 's3://{self.s3_bucket}/c3/tables/{name}/' TBLPROPERTIES ('skip.header.line.count'='1')")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tables", default="out/tables")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dump", default="out/load_dryrun", help="dry-run output folder")
    ap.add_argument("--region")
    ap.add_argument("--table-prefix", default="ftusa_c3_")
    ap.add_argument("--vector-bucket", default="ftusa-c3-vectors")
    ap.add_argument("--vector-index", default="peer-projects")
    ap.add_argument("--embedding-model", default="amazon.titan-embed-text-v2:0")
    ap.add_argument("--dim", type=int, default=1024)
    ap.add_argument("--s3-bucket")
    ap.add_argument("--athena-output")
    ap.add_argument("--athena-db", default="ftusa_c3")
    ap.add_argument("--create", action="store_true", help="create tables / vector bucket / index if missing")
    a = ap.parse_args(argv)

    built = prepare(Path(a.tables))
    stats_file = Path(a.tables).parent / "catalog_stats.json"
    write_stats(built, stats_file)

    if a.dry_run:
        d = Path(a.dump)
        d.mkdir(parents=True, exist_ok=True)
        for n in ("producers", "projects", "survey_summaries"):
            (d / f"{n}.jsonl").write_text("\n".join(json.dumps(i, default=str, ensure_ascii=False, sort_keys=True)
                                                  for i in built[n]) + "\n", encoding="utf-8")
        (d / "vectors.jsonl").write_text("\n".join(json.dumps({k: v for k, v in x.items()}, ensure_ascii=False,
                                                              sort_keys=True) for x in built["vectors"]) + "\n")
        m = manifest(built, {"mode": "dry-run"})
        (d / "load_manifest.json").write_text(json.dumps(m, indent=2, default=str))
        print(json.dumps({k: m[k] for k in ("load_id", "tables", "vectors")}, indent=1))
        return m

    L = AwsLoader(a.region, a.table_prefix, a.vector_bucket, a.vector_index, a.s3_bucket, a.athena_output, a.athena_db)
    if a.create:
        L.create(a.dim)
    swept = {}
    for n in ("producers", "projects", "survey_summaries"):
        L.upsert(n, built[n])
        keys = [k for k, _, _ in TABLES[n]["keys"]]
        swept[n] = L.sweep(n, built["load_id"], {tuple(i[k] for k in keys) for i in built[n]})
    vec = L.load_vectors(built["vectors"], a.embedding_model, a.dim)
    if a.s3_bucket and a.athena_output:
        L.load_athena(Path(a.tables))
    m = manifest(built, {"mode": "aws", "stale_deleted": swept, "vector_stats": vec})
    Path(a.tables).parent.joinpath("load_manifest.json").write_text(json.dumps(m, indent=2, default=str))
    print(json.dumps({k: m[k] for k in ("load_id", "tables", "vectors", "stale_deleted", "vector_stats")}, indent=1))
    return m


if __name__ == "__main__":
    main()
