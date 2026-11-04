#!/usr/bin/env python3
"""Post-deploy smoke test against the REAL sandbox stack (no mocks).

Uses disposable synthetic identities minted through the IAM-gated admin API and the sandbox-only CI app client.
Tokens and passwords are never printed. Everything created is deleted in `finally`.

Usage: python scripts/smoke_sandbox.py --stack FtusaExchange-sandbox --expect-commit <sha>
"""
import argparse, base64, json, os, secrets, string, sys, time, urllib.error, urllib.request, uuid
from pathlib import Path

import boto3

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = ""):
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{' - ' + detail if detail else ''}", flush=True)
    return ok


def http(method, url, token=None, body=None, timeout=90):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None)
    if body is not None:
        req.add_header("content-type", "application/json")
    if token:
        req.add_header("authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw[:1] in (b"{", b"[") else raw.decode(errors="replace"))
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw.decode(errors="replace")


def password() -> str:
    a = string.ascii_letters + string.digits
    return "".join(secrets.choice(a) for _ in range(20)) + "aA1!"


def mask(v: str):
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::add-mask::{v}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stack", required=True)
    ap.add_argument("--expect-commit", required=True)
    ap.add_argument("--region", default=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"))
    a = ap.parse_args()
    sess = boto3.Session(region_name=a.region)
    out = {o["OutputKey"]: o["OutputValue"] for o in sess.client("cloudformation").describe_stacks(StackName=a.stack)["Stacks"][0]["Outputs"]}
    api, web = out["ApiUrl"].rstrip("/"), out["WebUrl"].rstrip("/")
    idp, ddb, ac = sess.client("cognito-idp"), sess.client("dynamodb"), sess.client("bedrock-agentcore")
    pool, ci_client, table = out["UserPoolId"], out["CiClientId"], out["ConversationsTable"]

    check("deployed commit output matches the tested commit", out.get("DeployedCommit") == a.expect_commit, f"stack={out.get('DeployedCommit', '?')[:12]}")

    # 1. frontend
    st, body = http("GET", web + "/")
    check("frontend loads", st == 200 and "Producer Exchange" in str(body), f"status={st}")
    st, cfg = http("GET", web + "/config.json")
    check("frontend config comes from deployment outputs", st == 200 and isinstance(cfg, dict) and cfg.get("apiBaseUrl") == out["ApiUrl"] and cfg.get("clientId") == out["UserPoolClientId"])

    # 2. unauthenticated rejection
    st, _ = http("POST", api + "/transcribe", body={"requestId": uuid.uuid4().hex, "language": "en", "audio": "AAAA"})
    check("unauthenticated POST /transcribe rejected", st == 401, f"status={st}")
    for path in ("/me", "/conversations/current", "/reviews"):
        st, _ = http("GET", api + path)
        check(f"unauthenticated GET {path} rejected", st == 401, f"status={st}")
    st, _ = http("GET", api + "/me", token="not-a-token")
    check("malformed token rejected", st == 401, f"status={st}")

    # 3. the agent that is running is the intended version (direct IAM ping to the runtime)
    arn = out["AgentRuntimeArn"]
    r = ac.invoke_agent_runtime(agentRuntimeArn=arn, runtimeSessionId="ftusa-smoke-ping-" + uuid.uuid4().hex, runtimeUserId="ci-smoke",
                                payload=json.dumps({"ping": True}).encode(), contentType="application/json", accept="application/json")
    ping = json.loads(r["response"].read())
    check("AgentCore runtime runs the intended commit", ping.get("version") == a.expect_commit, f"runtime={str(ping.get('version'))[:12]}")

    # 4. disposable identities
    run = uuid.uuid4().hex[:10]
    users, subs, conv_ids = {}, {}, []
    try:
        for tag, pid in (("a", "SYN-CI-A"), ("b", "SYN-CI-B")):
            name = f"ci-smoke-{run}-{tag}@example.com"
            pw = password(); mask(pw)
            idp.admin_create_user(UserPoolId=pool, Username=name, MessageAction="SUPPRESS", UserAttributes=[{"Name": "email", "Value": name}, {"Name": "email_verified", "Value": "true"}])
            idp.admin_set_user_password(UserPoolId=pool, Username=name, Password=pw, Permanent=True)
            idp.admin_add_user_to_group(UserPoolId=pool, Username=name, GroupName="producer")
            sub = next(x["Value"] for x in idp.admin_get_user(UserPoolId=pool, Username=name)["UserAttributes"] if x["Name"] == "sub")
            prof = {"producerId": pid, "displayName": f"Synthetic CI {tag.upper()}", "entityType": "cooperative", "location": "Synthetic CI Region", "crop": "coffee", "preferredLanguage": "en"}
            ddb.put_item(TableName=table, Item={"pk": {"S": f"PROFILE#{sub}"}, "sk": {"S": "META"}, "profile": {"M": {k: {"S": v} for k, v in prof.items()}}})
            tok = idp.admin_initiate_auth(UserPoolId=pool, ClientId=ci_client, AuthFlow="ADMIN_USER_PASSWORD_AUTH", AuthParameters={"USERNAME": name, "PASSWORD": pw})["AuthenticationResult"]["AccessToken"]
            mask(tok)
            users[tag], subs[tag] = tok, sub
            users[tag + "_name"] = name
        ta, tb = users["a"], users["b"]

        # 5. authorized identity reaches its profile
        st, me = http("GET", api + "/me", ta)
        check("authorized producer can read its trusted profile", st == 200 and me.get("profile", {}).get("displayName") == "Synthetic CI A" and "producer" in me.get("roles", []), f"status={st}")

        # 6. real conversation: agent (AgentCore + Bedrock), same conversation continues, retry de-duplicated
        st, c = http("POST", api + "/conversations", ta, {"requestId": uuid.uuid4().hex, "language": "es"})
        cid = c.get("conversation", {}).get("conversationId") if st == 200 else None
        if cid: conv_ids.append(cid)
        check("authenticated conversation created", st == 200 and bool(cid), f"status={st}")
        rid = uuid.uuid4().hex
        st, m1 = http("POST", f"{api}/conversations/{cid}/messages", ta, {"requestId": rid, "text": "Las lluvias llegaron tarde este año y la cosecha fue menor."})
        msgs = m1.get("messages", []) if st == 200 else []
        reply = msgs[-1]["text"] if msgs and msgs[-1]["role"] == "assistant" else ""
        # No fallback exists on this path: a 200 means the AgentCore runtime and Bedrock produced the reply.
        check("message reaches AgentCore Runtime and Bedrock returns a reply", st == 200 and len(reply) > 20, f"status={st} reply_chars={len(reply)}")
        st2, m2 = http("POST", f"{api}/conversations/{cid}/messages", ta, {"requestId": rid, "text": "Las lluvias llegaron tarde este año y la cosecha fue menor."})
        check("retry with the same requestId does not duplicate", st2 == 200 and m2 == m1 and sum(1 for x in m2["messages"] if x["role"] == "user") == 1)
        st, sp = http("POST", f"{api}/conversations/{cid}/messages/1/speech", ta, {})
        audio = base64.b64decode(sp.get("audio", "")) if st == 200 else b""
        check("read aloud returns real speech audio for the agent's reply", st == 200 and sp.get("contentType") == "audio/mpeg" and len(audio) > 2000, f"status={st} bytes={len(audio)}")
        st, _ = http("POST", f"{api}/conversations/{cid}/messages/1/speech", tb, {})
        check("another producer cannot have the reply read aloud", st == 404, f"status={st}")
        st, cur = http("GET", api + "/conversations/current", ta)
        check("same conversation is restored", st == 200 and cur.get("conversation", {}).get("conversationId") == cid)

        def listed(token):  # history is served from an eventually consistent index: allow a few seconds
            ids = []
            for _ in range(10):
                st_l, lst = http("GET", api + "/conversations", token)
                ids = [i["conversationId"] for i in lst.get("items", [])] if st_l == 200 else []
                if cid in ids: break
                time.sleep(1)
            return ids
        check("history lists the producer's own conversation", cid in listed(ta))
        st, lst_b = http("GET", api + "/conversations", tb)
        check("history never shows another producer's conversation", st == 200 and cid not in [i["conversationId"] for i in lst_b.get("items", [])], f"status={st}")
        st, ask = http("POST", api + "/ask", ta, {"requestId": uuid.uuid4().hex, "text": "Is there climate data for my region?", "language": "en"})
        check("ask returns a model answer and reports evidence as unavailable", st == 200 and len(ask.get("answer", "")) > 20 and ask.get("evidence", {}).get("status") == "unavailable", f"status={st}")

        # 6b. dictation: real Amazon Transcribe through the deployed API (synthetic speech, not stored)
        clip = base64.b64encode((Path(__file__).resolve().parent.parent / "fixtures" / "smoke-speech-en.pcm").read_bytes()).decode()
        st, tr = http("POST", api + "/transcribe", ta, {"requestId": uuid.uuid4().hex, "language": "en", "audio": clip})
        spoken = tr.get("text", "").lower() if st == 200 else ""
        check("dictation turns synthetic speech into text", st == 200 and "rain" in spoken and "harvest" in spoken, f"status={st} chars={len(spoken)}")
        clip_fr = base64.b64encode((Path(__file__).resolve().parent.parent / "fixtures" / "smoke-speech-fr.pcm").read_bytes()).decode()
        st, tr = http("POST", api + "/transcribe", ta, {"requestId": uuid.uuid4().hex, "language": "fr", "audio": clip_fr})
        said = tr.get("text", "").lower() if st == 200 else ""
        check("French dictation turns synthetic speech into text", st == 200 and "pluie" in said and "colte" in said, f"status={st} chars={len(said)}")
        st, ask_fr = http("POST", api + "/ask", ta, {"requestId": uuid.uuid4().hex, "text": "Existe-t-il des données climatiques pour ma région ?", "language": "fr"})
        check("French question gets a model answer", st == 200 and len(ask_fr.get("answer", "")) > 20, f"status={st}")
        st, _ = http("POST", api + "/transcribe", ta, {"requestId": uuid.uuid4().hex, "language": "en", "audio": "AAAA"})
        check("too-short recording is rejected", st == 400, f"status={st}")
        st, _ = http("POST", api + "/transcribe", ta, {"requestId": uuid.uuid4().hex, "language": "en", "audio": clip, "producerId": "SYN-CI-B"})
        check("dictation rejects unknown fields", st == 400, f"status={st}")

        # 7. authorization boundaries
        st, _ = http("GET", f"{api}/conversations/{cid}", tb)
        check("other producer cannot read the conversation", st == 404, f"status={st}")
        st, _ = http("POST", f"{api}/conversations/{cid}/messages", tb, {"requestId": uuid.uuid4().hex, "text": "hello"})
        check("other producer cannot append", st == 404, f"status={st}")
        st, _ = http("POST", f"{api}/conversations/{cid}/end", tb, {"requestId": uuid.uuid4().hex})
        check("other producer cannot end it", st == 404, f"status={st}")
        for method, path in (("GET", "/reviews"), ("GET", "/reviews/rec-x"), ("PUT", "/reviews/rec-x")):
            st, _ = http(method, api + path, ta, {"requestId": uuid.uuid4().hex, "decision": "approve"} if method == "PUT" else None)
            check(f"producer cannot use reviewer operation {method} {path}", st == 403, f"status={st}")
        st, _ = http("POST", f"{api}/conversations/{cid}/messages", ta, {"requestId": uuid.uuid4().hex, "text": "x", "producerId": "SYN-CI-B"})
        check("request-supplied producerId is rejected", st == 400, f"status={st}")

        # 8. end the conversation (narrative-free declined outcome)
        st, _ = http("POST", f"{api}/conversations/{cid}/end", ta, {"requestId": uuid.uuid4().hex})
        check("producer can end the conversation", st == 200, f"status={st}")
        gone = False
        for _ in range(10):
            st, lst = http("GET", api + "/conversations", ta)
            if st == 200 and cid not in [i["conversationId"] for i in lst.get("items", [])]: gone = True; break
            time.sleep(1)
        check("a declined conversation leaves the history", gone)
    except Exception as e:  # a crash is a failure, but never leak details beyond the type
        check("smoke run completed without errors", False, type(e).__name__)
    finally:
        for cid in conv_ids:  # remove disposable records
            try:
                q = ddb.query(TableName=table, KeyConditionExpression="pk = :p", ExpressionAttributeValues={":p": {"S": f"CONV#{cid}"}}, ProjectionExpression="pk, sk")
                for it in q.get("Items", []):
                    ddb.delete_item(TableName=table, Key={"pk": it["pk"], "sk": it["sk"]})
                ddb.delete_item(TableName=out["OutcomesTable"], Key={"outcomeId": {"S": f"dec-{cid}"}}) if "OutcomesTable" in out else None
            except Exception:
                pass
        for tag in ("a", "b"):
            if tag in subs:
                for fn in (lambda: ddb.delete_item(TableName=table, Key={"pk": {"S": f"PROFILE#{subs[tag]}"}, "sk": {"S": "META"}}),
                           lambda: ddb.delete_item(TableName=table, Key={"pk": {"S": f"ACTIVE#{subs[tag]}"}, "sk": {"S": "META"}}),
                           lambda: idp.admin_delete_user(UserPoolId=pool, Username=users[tag + "_name"])):
                    try: fn()
                    except Exception: pass
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
