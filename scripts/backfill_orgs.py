#!/usr/bin/env python3
"""Link the ORIGINAL synthetic demo accounts (profiles without organizationId) to a synthetic organization so the producer-information view has data.
Country, crop, entity type and member count come from data/team-synthetic/producers.json; the account reference and other source columns are synthetic placeholders.
Idempotent: skips profiles that already have an organization. Sandbox only.
  AWS_PROFILE=breaking-barriers-ny uv run --project agent python scripts/backfill_orgs.py --stack FtusaExchange-sandbox
"""
import argparse, json, zlib
from pathlib import Path
import boto3

ROOT = Path(__file__).resolve().parent.parent
TEAM = {p["producer_id"]: p for p in json.loads((ROOT / "data/team-synthetic/producers.json").read_text())}
CC = {"Colombia": "COL", "Peru": "PER", "Honduras": "HND", "Mexico": "MEX", "Côte d'Ivoire": "CIV"}

def org_for(pid, name):
    t = TEAM[pid]; coop = t["entity_type"] != "individual farm"
    sk = f"ACC-{CC.get(t['country'], 'XXX')}-{zlib.crc32(pid.encode()) % 10**10:010d}"
    return {"organizationId": f"ORG-{pid}", "name": name, "info": {
        "accountSk": sk, "accountCategoryName": "Cooperative" if coop else "Individual farm", "productCategoryName": [t["crop"].capitalize()],
        "accountTypeName": "Producer organization" if coop else "Individual producer", "certificationScopeName": "Small producer organization" if coop else "Individual smallholder",
        "certificationStatusName": "Certified", "countryName": t["country"], "rawSupplyChainRoleTxt": ["Grower", "Aggregator"] if coop else ["Grower"],
        "structureTxt": f"{t['entity_type'].capitalize()} with {t['members']} members (synthetic)" if coop else None}}

ap = argparse.ArgumentParser(); ap.add_argument("--stack", required=True); a = ap.parse_args()
sess = boto3.Session(region_name="us-west-2"); assert "sandbox" in a.stack
out = {o["OutputKey"]: o["OutputValue"] for o in sess.client("cloudformation").describe_stacks(StackName=a.stack)["Stacks"][0]["Outputs"]}
t = sess.resource("dynamodb").Table(out["ConversationsTable"]); n = 0
for i in t.scan(FilterExpression="begins_with(pk,:p)", ExpressionAttributeValues={":p": "PROFILE#"})["Items"]:
    p = i["profile"]
    if "organizationId" in p or p["producerId"] not in TEAM: continue
    org = org_for(p["producerId"], p["displayName"])
    try: t.put_item(Item={"pk": f"ORG#{org['organizationId']}", "sk": "META", "org": org}, ConditionExpression="attribute_not_exists(pk)")
    except t.meta.client.exceptions.ConditionalCheckFailedException: pass
    t.update_item(Key={"pk": i["pk"], "sk": "META"}, UpdateExpression="SET profile.organizationId = :o, profile.applicationUserId = :u",
                  ExpressionAttributeValues={":o": org["organizationId"], ":u": f"user-{p['producerId'].lower()}"}); n += 1
print(f"linked {n} existing profiles")
