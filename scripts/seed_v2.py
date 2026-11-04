#!/usr/bin/env python3
"""Seed the V2 SYNTHETIC dataset into a deployed sandbox stack. Idempotent: every write is conditional (attribute_not_exists), so reruns never overwrite
demo activity. Default is a dry run. Cognito subjects are resolved/created through the admin API; temporary passwords go to .seed-credentials.local (git-ignored), never stdout.

  AWS_PROFILE=breaking-barriers-ny python scripts/seed_v2.py --stack FtusaExchange-sandbox [--apply]
  ... --reset-sandbox --apply    destructive and separate: deletes ONLY items this script created (ids prefixed 'seed-' / profile ids in the dataset)

Authoritative records are written first; derived memory is NOT written here. It is rebuilt through the application path (see docs/REDESIGN_V2.md, memory).
"""
import argparse, json, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
D = Path(__file__).resolve().parent.parent / "data" / "v2-synthetic"
load = lambda n: json.loads((D / n).read_text())
CONV_TTL, REC_TTL = 90 * 86400, 180 * 86400


def build(now: datetime, subs: dict[str, str]):
    """Pure: returns (conversation_table_items, outcome_table_items) as plain dicts. Unit-testable without AWS."""
    people, orgs, convs, corrs = load("people.json"), load("organizations.json")["organizations"], load("conversations.json")["conversations"], load("corrections.json")["corrections"]
    P = {p["producerId"]: p for p in people["producers"]}
    iso = lambda days: (now - timedelta(days=days)).isoformat().replace("+00:00", "Z")
    ts = int(now.timestamp())
    ct, ot = [], []
    for o in orgs: ct.append({"pk": f"ORG#{o['organizationId']}", "sk": "META", "org": o})
    for p in P.values():
        sub = subs[p["producerId"]]
        prof = {k: p[k] for k in ("producerId", "displayName", "entityType", "location", "crop", "preferredLanguage", "organizationId", "applicationUserId")}
        ct.append({"pk": f"PROFILE#{sub}", "sk": "META", "profile": prof})
    for c in convs:
        cid = "seed-" + c["conversationId"]; p = P[c["producerId"]]; sub = subs[p["producerId"]]
        created = iso(c["daysAgo"]); status = c["status"]
        workflow = "intake" if status == "active" else "closed"
        conv = {"conversationId": cid, "ownerSub": sub, "producerId": p["producerId"], "organizationId": c["organizationId"], "language": c["language"], "workflow": workflow,
                "confirmation": "none" if status == "active" else "confirmed", "consent": "granted" if status == "completed" and c["kind"] == "issue" else "unanswered",
                "status": status, "title": c["title"], "piiFlag": c["piiFlag"], "piiTypes": ["PHONE"] if c["piiFlag"] else [], "messageCount": len(c["messages"]),
                "userTurns": sum(m["role"] == "user" for m in c["messages"]), "version": 2, "createdAt": created, "updatedAt": created, "expiresAt": ts + CONV_TTL}
        if c.get("summaryEn"): conv.update(summaryOriginal=c["summaryOriginal"], summaryEn=c["summaryEn"], challengeTags=c["tags"])
        ct.append({"pk": f"CONV#{cid}", "sk": "META", "ownerSub": sub, "createdAt": created, "convStatus": status, "ttl": ts + CONV_TTL, "data": conv})
        for i, m in enumerate(c["messages"], 1):
            ct.append({"pk": f"CONV#{cid}", "sk": f"MSG#{i:06d}", "seq": i, "role": m["role"], "text": m["text"], "at": created, "ttl": ts + CONV_TTL})
        if status == "active": ct.append({"pk": f"ACTIVE#{sub}", "sk": "META", "conversationId": cid, "ttl": ts + 8 * 86400})
        if status == "stopped":
            ot.append({"outcomeId": f"dec-{cid}", "gsiKind": "declined", "kind": "declined", "ownerSub": sub, "producerId": p["producerId"], "conversationId": cid, "language": c["language"],
                       "createdAt": created, "producerName": p["displayName"], "declineReason": "ended_early", "organizationId": c["organizationId"]})
        if status == "completed" and c["kind"] == "issue":
            pub, share = c["publicationStatus"], c["sharingChoice"]
            v1 = {"version": 1, "kind": "producer_confirmed", "summaryOriginal": c["summaryOriginal"], "summaryEn": c["summaryEn"], "hash": "seed", "at": created, "by": p["producerId"]}
            o = {"outcomeId": f"rec-{cid}", "gsiKind": "record", "kind": "record", "ownerSub": sub, "producerId": p["producerId"], "conversationId": cid, "language": c["language"],
                 "createdAt": created, "source": "agent conversation", "entityType": p["entityType"], "summaryOriginal": c["summaryOriginal"], "summaryEn": c["summaryEn"],
                 "challengeTags": c["tags"], "agentChallengeTags": c["tags"], "producerName": p["displayName"], "crop": p["crop"], "location": p["location"],
                 "piiFlag": c["piiFlag"], "piiTypes": ["PHONE"] if c["piiFlag"] else [], "evidenceStatus": "unavailable", "reviewStatus": c["reviewStatus"],
                 "organizationId": c["organizationId"], "sharingChoice": share, "identityPermitted": bool(c.get("identityPermitted")), "confirmationHash": "seed",
                 "confirmedAt": created, "confirmedByProducerId": p["producerId"], "confirmedByName": p["displayName"], "summaryVersion": c.get("summaryVersion", 1),
                 "versions": [v1], "publicationStatus": pub, "caseCard": {k: v for k, v in c["caseCard"].items() if k != "standards_status"}, "ttl": ts + REC_TTL}
            if c["reviewStatus"] in ("approved", "corrected"): o.update(reviewedBy="REV-1", reviewedByName="Reviewer One", reviewedAt=created)
            if pub == "published":
                o["publication"] = {"version": 1, "approvedBy": "REV-1", "approvedAt": created, "payload": {"challenge": c["summaryEn"], "action": c["caseCard"]["action"], "result": c["caseCard"]["result"],
                                    "tags": c["tags"], "standards": [], "citations": []}}
                o.update(publishedVersion=1, publishedAt=created)
            if pub == "withdrawn": o["publication"] = {"version": 1, "approvedBy": "REV-1", "approvedAt": created, "payload": {"challenge": c["summaryEn"], "action": None, "result": None, "tags": c["tags"], "standards": [], "citations": []}}
            if pub == "awaiting_reconfirmation":
                rev = {"version": 2, "kind": "reviewer_revision", "summaryOriginal": c["summaryOriginal"], "summaryEn": c["pendingRevision"]["summaryEn"], "hash": "seed-rev", "at": created, "by": "REV-1"}
                o.update(pendingRevision=rev, versions=[v1, rev], summaryEn=rev["summaryEn"], summaryVersion=2)
            ot.append(o)
    for r in corrs:
        created = iso(r["daysAgo"]); sub = subs[r["requesterProducerId"]]
        item = {"outcomeId": r["correctionId"], "gsiKind": "correction", "correctionId": r["correctionId"], "organizationId": r["organizationId"], "requesterProducerId": r["requesterProducerId"],
                "requesterSub": sub, "createdAt": created, "updatedAt": created, "changes": r["changes"], "status": r["status"], "ttl": ts + REC_TTL}
        if r.get("explanation"): item["explanation"] = r["explanation"]
        if r.get("decidedBy"): item.update(decidedBy=r["decidedBy"], decidedAt=created)
        if r["status"] == "applied": item["appliedAt"] = created
        ot.append(item)
    return ct, ot


def main():
    import boto3
    from boto3.dynamodb.types import TypeSerializer
    from botocore.exceptions import ClientError
    from seed_users import ensure_user, ROOT
    ap = argparse.ArgumentParser(); ap.add_argument("--stack", required=True); ap.add_argument("--region"); ap.add_argument("--apply", action="store_true"); ap.add_argument("--reset-sandbox", action="store_true")
    a = ap.parse_args()
    sess = boto3.Session(region_name=a.region)
    out = {o["OutputKey"]: o["OutputValue"] for o in sess.client("cloudformation").describe_stacks(StackName=a.stack)["Stacks"][0]["Outputs"]}
    if "sandbox" not in a.stack: sys.exit("refusing: seeding is sandbox-only")
    idp, ddb = sess.client("cognito-idp"), sess.client("dynamodb"); ser = TypeSerializer()
    people = load("people.json"); subs, creds = {}, []
    for p in people["producers"]:
        sub, pw = (None, None) if not a.apply else ensure_user(idp, out["UserPoolId"], p["seedUsername"], "producer")
        subs[p["producerId"]] = sub or f"dryrun-{p['producerId']}"
        if pw: creds.append(f"{p['seedUsername']}\t{pw}")
    for r in people["reviewers"]:
        if a.apply:
            _, pw = ensure_user(idp, out["UserPoolId"], r["seedUsername"], "reviewer")
            if pw: creds.append(f"{r['seedUsername']}\t{pw}")
    ct, ot = build(datetime.now(timezone.utc), subs)
    print(f"plan: {len(ct)} conversation-table items, {len(ot)} outcome-table items ({'APPLY' if a.apply else 'dry run'})")
    if a.reset_sandbox:
        if not a.apply: print("reset needs --apply"); return
        for table, items, key in ((out["ConversationsTable"], ct, ("pk", "sk")), (out["OutcomesTable"], ot, ("outcomeId",))):
            for it in items: ddb.delete_item(TableName=table, Key={k: ser.serialize(it[k]) for k in key})
        print("sandbox seed items removed (only items this dataset defines)"); return
    if not a.apply: return
    created = skipped = 0
    for table, items, cond in ((out["ConversationsTable"], ct, "attribute_not_exists(pk)"), (out["OutcomesTable"], ot, "attribute_not_exists(outcomeId)")):
        for it in items:
            try:
                ddb.put_item(TableName=table, Item={k: ser.serialize(v) for k, v in it.items()}, ConditionExpression=cond); created += 1
            except ClientError as e:
                if e.response["Error"]["Code"] != "ConditionalCheckFailedException": raise
                skipped += 1
    if creds:
        with (ROOT / ".seed-credentials.local").open("a") as f: f.write("\n".join(creds) + "\n")
    print(f"created {created}, left {skipped} existing items untouched. New temporary passwords: {len(creds)} (see .seed-credentials.local)")


if __name__ == "__main__":
    main()
