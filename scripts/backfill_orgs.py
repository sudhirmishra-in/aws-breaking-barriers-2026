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

REAL = {  # realistic synthetic organization records for the original demo accounts
 "P-MX-004": ("Producer organization (cooperative)", ["Coffee (green, washed arabica)", "Honey (secondary)"], "Small producer organization (SPO)", "Coffee production and cooperative wet milling", "Certified", ["Grower (member farms)", "Primary processor (wet mill)", "Exporter"], "Union of cooperatives with 980 members in 38 communities, general assembly and elected council"),
 "P-CO-001": ("Individual farm", ["Coffee (green, washed arabica)"], "Individual smallholder (via producer group)", "Coffee production", "Certified", ["Grower"], None),
 "P-CI-005": ("Producer organization (cooperative)", ["Cocoa (fermented, dried beans)"], "Small producer organization (SPO)", "Cocoa production, fermentation and bulk aggregation", "Certified", ["Grower (member farms)", "Aggregator", "Fermentation and drying"], "Cooperative of 1,150 members in 24 village sections, supervised by a management committee"),
}

def org_for(pid, name):
    t = TEAM[pid]; cat, prods, typ, scope, status, roles, struct = REAL[pid]
    sk = f"ACC-{CC.get(t['country'], 'XXX')}-{zlib.crc32(pid.encode()) % 10**10:010d}"
    return {"organizationId": f"ORG-{pid}", "name": name, "info": {"accountSk": sk, "accountCategoryName": cat, "productCategoryName": prods, "accountTypeName": typ,
        "certificationScopeName": scope, "certificationStatusName": status, "countryName": t["country"], "rawSupplyChainRoleTxt": roles, "structureTxt": struct}}

ap = argparse.ArgumentParser(); ap.add_argument("--stack", required=True); ap.add_argument("--refresh", action="store_true", help="overwrite organization records (synthetic values only)"); a = ap.parse_args()
sess = boto3.Session(region_name="us-west-2"); assert "sandbox" in a.stack
out = {o["OutputKey"]: o["OutputValue"] for o in sess.client("cloudformation").describe_stacks(StackName=a.stack)["Stacks"][0]["Outputs"]}
t = sess.resource("dynamodb").Table(out["ConversationsTable"]); n = 0
for i in t.scan(FilterExpression="begins_with(pk,:p)", ExpressionAttributeValues={":p": "PROFILE#"})["Items"]:
    p = i["profile"]
    if p["producerId"] not in TEAM or ("organizationId" in p and not a.refresh): continue
    org = org_for(p["producerId"], p["displayName"])
    t.put_item(Item={"pk": f"ORG#{org['organizationId']}", "sk": "META", "org": org})
    t.update_item(Key={"pk": i["pk"], "sk": "META"}, UpdateExpression="SET profile.organizationId = :o, profile.applicationUserId = :u",
                  ExpressionAttributeValues={":o": org["organizationId"], ":u": f"user-{p['producerId'].lower()}"}); n += 1
if a.refresh:
    for o in json.loads((ROOT / "data/v2-synthetic/organizations.json").read_text())["organizations"]: t.put_item(Item={"pk": f"ORG#{o['organizationId']}", "sk": "META", "org": o}); n += 1
print(f"wrote {n} organization links/records")
