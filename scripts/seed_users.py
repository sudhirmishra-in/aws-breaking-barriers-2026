#!/usr/bin/env python3
"""Create SYNTHETIC Cognito users (admin-created only) and their server-owned producer profiles.

Usage: AWS_PROFILE=breaking-barriers-ny python scripts/seed_users.py --stack FtusaExchange-sandbox
Temporary passwords are written to .seed-credentials.local (git-ignored), never printed.
"""
import argparse, json, secrets, string
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
DATA = json.loads((ROOT / "agent/app/exchange/data/producers.json").read_text())


def temp_password() -> str:
    a = string.ascii_letters + string.digits
    return "".join(secrets.choice(a) for _ in range(14)) + "Aa1"


def ensure_user(idp, pool, username, group):
    try:
        idp.admin_get_user(UserPoolId=pool, Username=username)
        existing = True
    except idp.exceptions.UserNotFoundException:
        existing = False
    pw = None
    if not existing:
        pw = temp_password()
        idp.admin_create_user(UserPoolId=pool, Username=username, TemporaryPassword=pw, MessageAction="SUPPRESS",
                              UserAttributes=[{"Name": "email", "Value": username}, {"Name": "email_verified", "Value": "true"}])
    idp.admin_add_user_to_group(UserPoolId=pool, Username=username, GroupName=group)
    user = idp.admin_get_user(UserPoolId=pool, Username=username)
    sub = next(a["Value"] for a in user["UserAttributes"] if a["Name"] == "sub")
    return sub, pw


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--stack", required=True); ap.add_argument("--region", default=None)
    a = ap.parse_args()
    sess = boto3.Session(region_name=a.region)
    out = {o["OutputKey"]: o["OutputValue"] for o in sess.client("cloudformation").describe_stacks(StackName=a.stack)["Stacks"][0]["Outputs"]}
    idp, ddb = sess.client("cognito-idp"), sess.client("dynamodb")
    creds = []
    for p in DATA["producers"]:
        sub, pw = ensure_user(idp, out["UserPoolId"], p["seedUsername"], "producer")
        profile = {k: p[k] for k in ("producerId", "displayName", "entityType", "location", "crop", "preferredLanguage")}
        ddb.put_item(TableName=out["ConversationsTable"], Item={"pk": {"S": f"PROFILE#{sub}"}, "sk": {"S": "META"}, "profile": {"M": {k: {"S": v} for k, v in profile.items()}}})
        if pw: creds.append(f"{p['seedUsername']}\t{pw}")
    for r in DATA["reviewers"]:
        sub, pw = ensure_user(idp, out["UserPoolId"], r["seedUsername"], "reviewer")
        if pw: creds.append(f"{r['seedUsername']}\t{pw}")
    if creds:
        (ROOT / ".seed-credentials.local").write_text("\n".join(creds) + "\n")
    print(f"Seeded {len(DATA['producers'])} producers and {len(DATA['reviewers'])} reviewer(s). New temporary passwords: {len(creds)} (see .seed-credentials.local).")


if __name__ == "__main__":
    main()
