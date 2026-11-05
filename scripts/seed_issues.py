#!/usr/bin/env python3
"""Seed the 12 SYNTHETIC issue histories (data/v2-synthetic/issues.json) as authoritative issue records. Conditional puts only: reruns never overwrite real activity.
Derived memory is NOT written here; it is rebuilt through the application path (POST /memory/reconcile) so memory always comes from authoritative records.
  AWS_PROFILE=breaking-barriers-ny uv run --project agent python scripts/seed_issues.py --stack FtusaExchange-sandbox [--apply]
"""
import argparse, json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import boto3

D = Path(__file__).resolve().parent.parent / "data" / "v2-synthetic"
ap = argparse.ArgumentParser(); ap.add_argument("--stack", required=True); ap.add_argument("--apply", action="store_true"); a = ap.parse_args()
assert "sandbox" in a.stack
sess = boto3.Session(region_name="us-west-2")
out = {o["OutputKey"]: o["OutputValue"] for o in sess.client("cloudformation").describe_stacks(StackName=a.stack)["Stacks"][0]["Outputs"]}
t = sess.resource("dynamodb").Table(out["OutcomesTable"])
issues = json.loads((D / "issues.json").read_text())["issues"]; convs = {c["conversationId"]: c for c in json.loads((D / "conversations.json").read_text())["conversations"]}
now = datetime.now(timezone.utc); iso = lambda d: (now - timedelta(days=d)).isoformat().replace("+00:00", "Z")
made = linked = 0
for i in issues:
    first = max(e["daysAgo"] for e in i["events"]); last_rep = min(e["daysAgo"] for e in i["events"] if e["type"] in ("reported", "recurrence"))
    linked_ids = ["seed-" + c for c in i["linkedConversations"]]
    c0 = convs[i["linkedConversations"][0]]
    events = []
    for n, e in enumerate(sorted(i["events"], key=lambda x: -x["daysAgo"]), 1):
        events.append({"eventId": f"evt-seed-{i['issueId']}-{n}", "type": e["type"], "at": iso(e["daysAgo"]), "source": "seed_synthetic", "synthetic": True,
                       **({"text": e["text"]} if e.get("text") else {}), **({"producerId": e["by"]} if e.get("by") else {})})
    rec = {"issueId": f"issue-{i['organizationId']}-{i['issueId']}", "organizationId": i["organizationId"], "reportingProducerIds": i["reporters"], "description": c0["summaryEn"] if c0.get("summaryEn") else c0["title"],
           "tags": i["tags"], "crop": i["crop"], "geography": i["geography"], "firstReportedAt": iso(first), "lastReportedAt": iso(last_rep), "status": i["status"], "linkedConversations": linked_ids,
           "events": events, "evidenceRefs": [], "visibility": "organization", "reviewStatus": "approved", "version": 1, "synthetic": True}
    print(("put " if a.apply else "plan"), rec["issueId"], rec["status"], len(events), "events")
    if not a.apply: continue
    try:
        t.put_item(Item={"outcomeId": rec["issueId"], "gsiKind": "issue", "organizationId": rec["organizationId"], "createdAt": rec["firstReportedAt"], "issue": rec}, ConditionExpression="attribute_not_exists(outcomeId)"); made += 1
    except t.meta.client.exceptions.ConditionalCheckFailedException:
        pass
    for cid in linked_ids:  # tie the seeded finalized records to their issue (only where a record exists and has no issue yet)
        try:
            t.update_item(Key={"outcomeId": f"rec-{cid}"}, UpdateExpression="SET issueId = :i, issueDecision = :d", ConditionExpression="attribute_exists(outcomeId) AND attribute_not_exists(issueId)",
                          ExpressionAttributeValues={":i": rec["issueId"], ":d": "linked"}); linked += 1
        except t.meta.client.exceptions.ConditionalCheckFailedException:
            pass
print(f"issues created {made}, records linked {linked}" if a.apply else "dry run")
