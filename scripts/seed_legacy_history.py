#!/usr/bin/env python3
"""Add realistic SYNTHETIC history for the original demo accounts (and colleagues without logins) in their organizations. Conditional puts only: reruns never
overwrite activity. Requires scripts/backfill_orgs.py to have linked the accounts first. Sandbox only; dry run unless --apply.
  AWS_PROFILE=breaking-barriers-ny uv run --project agent python scripts/seed_legacy_history.py --stack FtusaExchange-sandbox [--apply]
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import boto3
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError
import seed_v2

ap = argparse.ArgumentParser(); ap.add_argument("--stack", required=True); ap.add_argument("--apply", action="store_true"); a = ap.parse_args()
assert "sandbox" in a.stack
sess = boto3.Session(region_name="us-west-2")
out = {o["OutputKey"]: o["OutputValue"] for o in sess.client("cloudformation").describe_stacks(StackName=a.stack)["Stacks"][0]["Outputs"]}
ddb = sess.client("dynamodb"); ser = TypeSerializer()
hist = json.loads((seed_v2.D / "legacy_history.json").read_text())
subs, owners = {}, {}
for i in sess.resource("dynamodb").Table(out["ConversationsTable"]).scan(FilterExpression="begins_with(pk,:p)", ExpressionAttributeValues={":p": "PROFILE#"})["Items"]:
    owners[i["profile"]["producerId"]] = (i["pk"].split("#", 1)[1], i["profile"])
producers = list(hist["producers"])
for c in hist["conversations"]:
    pid = c["producerId"]
    if pid in owners and not any(p["producerId"] == pid for p in producers):
        pr = owners[pid][1]; producers.append({**pr, "organizationId": pr["organizationId"]}); subs[pid] = owners[pid][0]
for p in hist["producers"]: subs[p["producerId"]] = f"seed-colleague-{p['producerId']}"
missing = [c["producerId"] for c in hist["conversations"] if c["producerId"] not in subs]
assert not missing, f"link accounts first (backfill_orgs.py): {set(missing)}"
doc = {"producers": producers, "orgs": [], "convs": hist["conversations"], "corrs": []}
ct, ot = seed_v2.build(datetime.now(timezone.utc), subs, doc)
# organizations of the colleagues' accounts already exist (backfill); nothing else to create
print(f"plan: {len(ct)} + {len(ot)} items ({'APPLY' if a.apply else 'dry run'})")
if a.apply:
    made = skipped = 0
    for table, items, cond in ((out["ConversationsTable"], ct, "attribute_not_exists(pk)"), (out["OutcomesTable"], ot, "attribute_not_exists(outcomeId)")):
        for it in items:
            try: ddb.put_item(TableName=table, Item={k: ser.serialize(v) for k, v in it.items()}, ConditionExpression=cond); made += 1
            except ClientError as e:
                if e.response["Error"]["Code"] != "ConditionalCheckFailedException": raise
                skipped += 1
    print(f"created {made}, left {skipped} untouched")
