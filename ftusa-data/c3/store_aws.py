"""DynamoDB + S3 Vectors Store (boto3). Fetch-only: all rules live in access.DataAccess.

NOT RUN in the build environment (no boto3 / AWS there). API shapes follow the
boto3 docs for dynamodb (resource API), s3vectors and bedrock-runtime; smoke
test with `python -m c3.smoke --backend aws` before relying on it.
"""
from __future__ import annotations

import json
from decimal import Decimal

from .store_base import Filter

TITAN_MODEL = "amazon.titan-embed-text-v2:0"
DIM = 1024
MAX_PAGES = 10


def from_ddb(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, list):
        return [from_ddb(x) for x in v]
    if isinstance(v, dict):
        return {k: from_ddb(x) for k, x in v.items()}
    return v


class TitanEmbedder:
    def __init__(self, client, model_id: str = TITAN_MODEL, dim: int = DIM):
        self.c, self.model_id, self.dim = client, model_id, dim

    def embed(self, text: str) -> list[float]:
        body = json.dumps({"inputText": text[:8000], "dimensions": self.dim, "normalize": True})
        r = self.c.invoke_model(modelId=self.model_id, body=body, contentType="application/json", accept="application/json")
        return json.loads(r["body"].read())["embedding"]


class DynamoS3Store:
    def __init__(self, table_prefix: str, vector_bucket: str, vector_index: str = "peer-projects",
                 region: str | None = None, session=None):
        import boto3

        s = session or boto3.Session(region_name=region)
        ddb = s.resource("dynamodb")
        self.t_producers = ddb.Table(f"{table_prefix}producers")
        self.t_projects = ddb.Table(f"{table_prefix}projects")
        self.t_surveys = ddb.Table(f"{table_prefix}survey_summaries")
        self.ddb = ddb
        self.s3v = s.client("s3vectors")
        self.embedder = TitanEmbedder(s.client("bedrock-runtime"))
        self.vector_bucket, self.vector_index = vector_bucket, vector_index

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _filter_expr(filters: list[Filter]):
        from boto3.dynamodb.conditions import Attr

        expr = None
        for attr, op, val in filters:
            a = Attr(attr)
            c = {"eq": a.eq, "ne": a.ne, "ge": a.gte}[op](val)
            expr = c if expr is None else expr & c
        return expr

    def _paged_query(self, table, limit: int, **kw) -> list[dict]:
        """FilterExpression is applied after Limit in DynamoDB, so page until enough rows (bounded)."""
        out, start = [], None
        for _ in range(MAX_PAGES):
            if start:
                kw["ExclusiveStartKey"] = start
            r = table.query(Limit=max(limit * 2, 10), **kw)
            out += [from_ddb(i) for i in r.get("Items", [])]
            start = r.get("LastEvaluatedKey")
            if len(out) >= limit or not start:
                break
        return out[:limit]

    # ------------------------------------------------------------------ Store protocol
    def get_producer(self, account_sk):
        r = self.t_producers.get_item(Key={"account_sk": account_sk})
        return from_ddb(r["Item"]) if "Item" in r else None

    def list_projects(self, account_sk, limit):
        from boto3.dynamodb.conditions import Key

        r = self.t_projects.query(KeyConditionExpression=Key("account_sk").eq(account_sk), Limit=limit)
        return [from_ddb(i) for i in r.get("Items", [])]

    def list_surveys(self, account_sk):
        from boto3.dynamodb.conditions import Key

        r = self.t_surveys.query(KeyConditionExpression=Key("account_sk").eq(account_sk), ScanIndexForward=True)
        return [from_ddb(i) for i in r.get("Items", [])]

    def batch_get_projects(self, keys):
        if not keys:
            return []
        name = self.t_projects.name
        req = {name: {"Keys": [{"account_sk": a, "project_id": p} for a, p in keys[:100]]}}
        out = []
        for _ in range(5):  # retry unprocessed keys
            r = self.ddb.batch_get_item(RequestItems=req)
            out += [from_ddb(i) for i in r.get("Responses", {}).get(name, [])]
            req = r.get("UnprocessedKeys") or {}
            if not req:
                break
        return out

    def query_projects(self, index, pk, sk_prefix, filters, limit):
        from boto3.dynamodb.conditions import Key

        idx, pk_attr, sk_attr = {"country": ("peers_by_country_tag", "gsi_country", "gsi_country_sk"),
                                 "tag": ("peers_by_tag", "gsi_primary_tag", "gsi_tag_sk")}[index]
        kc = Key(pk_attr).eq(pk)
        if sk_prefix:
            kc = kc & Key(sk_attr).begins_with(sk_prefix)
        kw = {"IndexName": idx, "KeyConditionExpression": kc, "ScanIndexForward": index != "country"}
        fe = self._filter_expr(filters)
        if fe is not None:
            kw["FilterExpression"] = fe
        return self._paged_query(self.t_projects, limit, **kw)

    def query_producers(self, country, sk_prefix, filters, limit):
        from boto3.dynamodb.conditions import Key

        kc = Key("country").eq(country)
        if sk_prefix:
            kc = kc & Key("gsi_crop_sk").begins_with(sk_prefix)
        kw = {"IndexName": "by_country_crop", "KeyConditionExpression": kc}
        fe = self._filter_expr(filters)
        if fe is not None:
            kw["FilterExpression"] = fe
        return self._paged_query(self.t_producers, limit, **kw)

    def vector_search(self, text, vfilter, top_k):
        r = self.s3v.query_vectors(vectorBucketName=self.vector_bucket, indexName=self.vector_index,
                                   queryVector={"float32": self.embedder.embed(text)}, topK=min(top_k, 30),
                                   filter=vfilter, returnMetadata=True, returnDistance=True)
        return [(v["key"], 1.0 - float(v.get("distance", 1.0)), v.get("metadata", {})) for v in r.get("vectors", [])]
