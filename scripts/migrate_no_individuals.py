#!/usr/bin/env python3
"""One-time sandbox migration: there is no individual-farmer entity; every producer belongs to an organization.
 1. Profiles and record snapshots with entityType 'smallholder' become the type of their organization (cooperative or association).
 2. The organization of the original account P-CO-001 (was 'Individual farm') becomes a producer association.
Idempotent; sandbox only; dry run unless --apply.
  AWS_PROFILE=breaking-barriers-ny uv run --project agent python scripts/migrate_no_individuals.py --stack FtusaExchange-sandbox [--apply]
"""
import argparse
import boto3

ap = argparse.ArgumentParser(); ap.add_argument("--stack", required=True); ap.add_argument("--apply", action="store_true"); a = ap.parse_args()
assert "sandbox" in a.stack
sess = boto3.Session(region_name="us-west-2")
out = {o["OutputKey"]: o["OutputValue"] for o in sess.client("cloudformation").describe_stacks(StackName=a.stack)["Stacks"][0]["Outputs"]}
conv, outc = (sess.resource("dynamodb").Table(out[k]) for k in ("ConversationsTable", "OutcomesTable"))
def scan(t, **kw):
    r = t.scan(**kw); items = r["Items"]
    while "LastEvaluatedKey" in r: r = t.scan(ExclusiveStartKey=r["LastEvaluatedKey"], **kw); items += r["Items"]
    return items
orgs = {i["org"]["organizationId"]: i["org"] for i in scan(conv, FilterExpression="begins_with(pk,:p)", ExpressionAttributeValues={":p": "ORG#"})}
orgtype = lambda oid: "association" if "association" in orgs.get(oid, {}).get("info", {}).get("accountCategoryName", "").lower() else "cooperative"
n = 0
if "ORG-P-CO-001" in orgs and "Individual" in orgs["ORG-P-CO-001"]["info"]["accountCategoryName"]:
    o = orgs["ORG-P-CO-001"]; o["info"].update(accountCategoryName="Producer association", accountTypeName="Producer organization", certificationScopeName="Coffee production" if False else "Small producer organization (SPO)",
        rawSupplyChainRoleTxt=["Grower (member farms)"], structureTxt="Association of member farms in Cauca (synthetic)")
    print("org ORG-P-CO-001 -> producer association"); n += 1
    if a.apply: conv.put_item(Item={"pk": "ORG#ORG-P-CO-001", "sk": "META", "org": o})
for i in scan(conv, FilterExpression="begins_with(pk,:p)", ExpressionAttributeValues={":p": "PROFILE#"}):
    p = i["profile"]
    if p.get("entityType") == "smallholder":
        t = orgtype(p.get("organizationId")); print("profile", p["producerId"], "->", t); n += 1
        if a.apply: conv.update_item(Key={"pk": i["pk"], "sk": "META"}, UpdateExpression="SET profile.entityType = :t", ExpressionAttributeValues={":t": t})
for i in scan(outc, FilterExpression="entityType = :s", ExpressionAttributeValues={":s": "smallholder"}):
    t = orgtype(i.get("organizationId")); n += 1
    if a.apply: outc.update_item(Key={"outcomeId": i["outcomeId"]}, UpdateExpression="SET entityType = :t", ExpressionAttributeValues={":t": t})
print(("applied" if a.apply else "dry run"), n, "changes")
