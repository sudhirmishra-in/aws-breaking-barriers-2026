"""Backend-agnostic data-access layer for Component 5 (DA-1).

The **only** code that touches the store. Single target: DynamoDB
``environmental_facts`` (CACHE-1). Every read is a bounded partition query —
never a scan (DA-2). Sample and production use the same table; scaling is a
data-load change, not a backend swap.

Credential resolution: honours ``AWS_PROFILE`` / ``AWS_DEFAULT_REGION`` from the
environment (the demo runs under the ``breaking-barriers-ny`` profile,
``us-west-2``); explicit ``profile``/``region`` overrides are accepted.
"""
from __future__ import annotations

import datetime as dt
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key


def _num(x):
    """DynamoDB stores numbers as Decimal, never float. None passes through."""
    return None if x is None else Decimal(str(x))

# Default is the local/dev table; the deployed AgentCore runtime sets
# ENVIRONMENTAL_FACTS_TABLE to the CDK-managed table name in its environment.
TABLE_NAME = os.environ.get("ENVIRONMENTAL_FACTS_TABLE", "environmental_facts")
PK = "region_key"          # <country>#COUNTRY  (OPEN-7: country-level)
SK = "fact_key"            # <dataset>#<indicator>#<horizon>


def _dynamo(profile: str | None = None, region: str | None = None):
    # profile_name=None -> boto3 falls back to the AWS_PROFILE env var, then
    # the default credential chain.
    session = boto3.Session(profile_name=profile, region_name=region or "us-west-2")
    return session.resource("dynamodb")


def ensure_table(profile: str | None = None, region: str | None = None) -> None:
    """Create ``environmental_facts`` if absent (on-demand). Idempotent."""
    ddb = _dynamo(profile, region)
    if TABLE_NAME in {t.name for t in ddb.tables.all()}:
        print(f"table {TABLE_NAME} already exists")
        return
    ddb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[
            {"AttributeName": PK, "KeyType": "HASH"},
            {"AttributeName": SK, "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": PK, "AttributeType": "S"},
            {"AttributeName": SK, "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    ddb.Table(TABLE_NAME).wait_until_exists()
    print(f"created table {TABLE_NAME} (on-demand, us-west-2)")


def fact_key(dataset: str, indicator: str, horizon: str) -> str:
    return f"{dataset}#{indicator}#{horizon}"


def put_fact(
    region_key: str,
    dataset: str,
    indicator: str,
    horizon: str,
    *,
    value,
    unit: str,
    period: str,
    method: str,
    theme: str,
    baseline_value=None,
    baseline_delta_pct=None,
    baseline_period: str | None = None,
    is_projection: bool = False,
    is_stand_in: bool = False,
    profile: str | None = None,
) -> None:
    """Upsert one regional fact (ING-6: idempotent — same keys overwrite)."""
    item = {
        PK: region_key,
        SK: fact_key(dataset, indicator, horizon),
        "unit": unit,
        "period": period,
        "method": method,
        "theme": theme,
        "is_projection": is_projection,
        "is_stand_in": is_stand_in,
        "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    # A stand-in fact has no value (a 0 would be a false rainfall figure); the
    # value attribute is simply absent. Real facts always carry one.
    if value is not None:
        item["value"] = _num(value)
    if baseline_value is not None:
        item["baseline_value"] = _num(baseline_value)
    if baseline_delta_pct is not None:
        item["baseline_delta_pct"] = _num(baseline_delta_pct)
    if baseline_period is not None:
        item["baseline_period"] = baseline_period
    _dynamo(profile).Table(TABLE_NAME).put_item(Item=item)


def delete_fact(
    region_key: str,
    dataset: str,
    indicator: str,
    horizon: str,
    profile: str | None = None,
) -> None:
    """Remove one fact (idempotent — a missing item is a no-op). Used to clear a
    superseded indicator so a region never holds two competing figures."""
    _dynamo(profile).Table(TABLE_NAME).delete_item(
        Key={PK: region_key, SK: fact_key(dataset, indicator, horizon)}
    )


def get_facts(
    region_key: str,
    themes: set[str] | None = None,
    horizon: str = "current",
    profile: str | None = None,
) -> list[dict]:
    """Bounded partition read (CACHE-2/NFR-1): one Query on the region
    partition, then an in-code filter to the requested themes + horizon.

    Returns an **empty list** (not an error) when nothing matches, so the agent
    can say "no external data for that" rather than invent a figure.
    """
    resp = (
        _dynamo(profile)
        .Table(TABLE_NAME)
        .query(KeyConditionExpression=Key(PK).eq(region_key))
    )
    out = []
    for item in resp.get("Items", []):
        if themes and item.get("theme") not in themes:
            continue
        sk_horizon = item[SK].rsplit("#", 1)[-1]
        if horizon != "any" and sk_horizon != horizon:
            continue
        out.append(_shape(item))
    return out


def _f(x):
    """DynamoDB returns numbers as Decimal; the tool hands the agent JSON, so
    convert to float for the numeric fact fields."""
    return None if x is None else float(x)


def _shape(item: dict) -> dict:
    dataset, indicator, horizon = item[SK].split("#")
    return {
        "dataset": dataset,
        "theme": item.get("theme"),
        "indicator": indicator,
        "value": _f(item.get("value")),
        "unit": item.get("unit"),
        "period": item.get("period"),
        "method": item.get("method"),
        "baseline_value": _f(item.get("baseline_value")),
        "baseline_delta_pct": _f(item.get("baseline_delta_pct")),
        "baseline_period": item.get("baseline_period"),
        "is_projection": item.get("is_projection", False),
        "is_stand_in": item.get("is_stand_in", False),
        "horizon": horizon,
        "geographic_scope": "country",  # OPEN-7: the demo is country-level
    }
