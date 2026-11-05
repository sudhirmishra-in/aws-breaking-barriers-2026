#!/usr/bin/env python3
"""Validate the V2 synthetic dataset against the acceptance shape (counts, scenario coverage, privacy rules). Exit 1 on any failure."""
import json, re, sys
from collections import Counter
from pathlib import Path

D = Path(__file__).resolve().parent.parent / "data" / "v2-synthetic"
load = lambda n: json.loads((D / n).read_text())
orgs = load("organizations.json")["organizations"]; people = load("people.json"); convs = load("conversations.json")["conversations"]
issues = load("issues.json")["issues"]; corr = load("corrections.json")["corrections"]; prem = load("premium_projects.json")["projects"]
sc = load("surveys_certifications.json"); ev = load("regional_evidence.json")["evidence"]
errs = []
def check(ok, msg):
    if not ok: errs.append(msg)

P = {p["displayName"]: p for p in people["producers"]}
check(len(orgs) == 3, "3 organizations"); check(len(people["producers"]) == 9, "9 producers"); check(len(people["reviewers"]) == 2, "2 reviewers")
check(20 <= len(convs) <= 28, "about 24 conversations"); check(10 <= len(issues) <= 14, "about 12 issues"); check(len(prem) == 12, "12 Premium projects")
check(len({s["organizationId"] for s in sc["surveys"]}) == 3 and len({s["organizationId"] for s in sc["certifications"]}) == 3, "survey and certification per organization")
check(len(corr) >= 6 and {"pending", "accepted_awaiting_source_update", "applied", "rejected"} <= {c["status"] for c in corr}, "6 corrections across statuses")
for n, (org, lang) in {"Ana": ("ORG-AND-COL", "es"), "Mateo": ("ORG-AND-COL", "es"), "Elena": ("ORG-AND-COL", "en"), "Lucía": ("ORG-COP-HON", "es"), "Diego": ("ORG-COP-HON", "en"),
                       "Rosa": ("ORG-COP-HON", "es"), "Awa": ("ORG-NAW-CIV", "fr"), "Koffi": ("ORG-NAW-CIV", "fr"), "Mariam": ("ORG-NAW-CIV", "en")}.items():
    check(P[n]["organizationId"] == org and P[n]["preferredLanguage"] == lang, f"{n} org/language")
approved_peer = [c for c in convs if c.get("publicationStatus") == "published" and c.get("sharingChoice") in ("share_summary", "share_conversation")]
check(len(approved_peer) >= 6, f">=6 approved peer cases (got {len(approved_peer)})")
check(any(c.get("sharingChoice") == "share_conversation" and c.get("identityPermitted") for c in convs), "wider named case")
check(any(c.get("sharingChoice") == "share_summary" for c in convs), "summary-only / anonymous case")
check(any(c.get("sharingChoice") == "ftusa_only" for c in convs), "FTUSA-only case")
check(any(c.get("reviewStatus") == "pending" for c in convs), "pending case"); check(any(c.get("publicationStatus") == "withdrawn" for c in convs), "withdrawn case")
check(any(c.get("publicationStatus") == "awaiting_reconfirmation" for c in convs), "summary correction awaiting re-confirmation")
check(any(c.get("kind") == "search" for c in convs) and any(c.get("kind") == "out_of_scope" for c in convs), "search-only and out-of-scope")
check(any(c.get("playbackCorrected") for c in convs), "playback correction (Ana)")
check(any(c.get("piiFlag") for c in convs if c["producerId"] == "PRD-KOFFI"), "Koffi PII mention")
check(all(c["sharingChoice"] == "ftusa_only" for c in convs if c["producerId"] == "PRD-ROSA" and c.get("sharingChoice")), "Rosa is FTUSA-only")
check({"open", "action_planned", "action_in_progress", "resolved", "recurring", "unknown"} <= {i["status"] for i in issues}, "all issue statuses")
check(any(len(i["reporters"]) > 1 for i in issues), "multiple reporters on one incident")
check(any(e["type"] == "recurrence" for i in issues for e in i["events"]), "recurrence")
check(all(i.get("resolutionConfirmed") for i in issues if i["status"] == "resolved"), "resolved only with confirmed resolution")
check(all(not any(e["type"] == "resolution_confirmed" for e in i["events"]) or i["status"] == "resolved" for i in issues), "resolution event only on resolved issues")
check(any(e.get("stale") for e in ev) and any(e.get("conflictsWith") for e in ev), "stale and conflicting evidence")
check(all(e.get("illustrative") for e in ev), "evidence labelled illustrative")
check(all(e["curationStatus"] in ("ftusa_curated", "not_curated") and e["origin"] in ("external_imported", "ftusa_authored") for e in ev), "origin and curation are separate fields")
check(any(e["origin"] == "external_imported" and e["curationStatus"] == "ftusa_curated" for e in ev), "external AND curated can both apply")
check(all(not e.get("standards") for e in ev) and all(not c.get("caseCard", {}).get("standards") for c in convs), "no invented APS/FPS clauses")
ids = [c["conversationId"] for c in convs]; check(len(ids) == len(set(ids)), "unique conversation ids")
check(all(re.fullmatch(r"[A-Za-z0-9-]{8,80}", "seed-" + i) for i in ids), "case id shape")
check(all(c["issueId"] in {i["issueId"] for i in issues} for c in convs if c.get("issueId")), "issue links")
check(all(p["seedUsername"].endswith("@example.com") for p in people["producers"] + people["reviewers"]), "example.com accounts only")
check("password" not in json.dumps([people, orgs]).lower(), "no credentials in dataset")
check(all(p.get("organizationId") for p in people["producers"]) and all(p["entityType"] != "smallholder" for p in people["producers"]), "every producer belongs to an organization; no individual-farmer entity type")
print(Counter(c.get("publicationStatus", "-") for c in convs))
if errs:
    print("FAILED:\n - " + "\n - ".join(errs)); sys.exit(1)
print(f"ok: dataset valid ({len(convs)} conversations, {len(issues)} issues, {len(approved_peer)} peer cases)")
