#!/usr/bin/env python3
"""Retrieval smoke test against the real Knowledge Base: multilingual relevance, scope filter, metadata/provenance, citations resolving to the bundled validated rows.
  AWS_PROFILE=breaking-barriers-ny uv run --project agent python scripts/kb_smoke.py --stack FtusaExchange-sandbox
"""
import argparse, json, sys
from pathlib import Path
import boto3

ROOT = Path(__file__).resolve().parent.parent
bundle = {p["projectId"]: p for p in json.loads((ROOT / "backend/src/data/public_projects.json").read_text())["projects"]}
ap = argparse.ArgumentParser(); ap.add_argument("--stack", required=True); a = ap.parse_args()
s = boto3.Session(region_name="us-west-2")
o = {x["OutputKey"]: x["OutputValue"] for x in s.client("cloudformation").describe_stacks(StackName=a.stack)["Stacks"][0]["Outputs"]}
rt = s.client("bedrock-agent-runtime"); fails = []
def q(text, iso=None):
    cfg = {"numberOfResults": 5, **({"filter": {"equals": {"key": "countryIso2", "value": iso}}} if iso else {})}
    return rt.retrieve(knowledgeBaseId=o["KnowledgeBaseId"], retrievalQuery={"text": text}, retrievalConfiguration={"vectorSearchConfiguration": cfg})["retrievalResults"]
for lang, text in (("en", "shade trees and reforestation for coffee farms"), ("es", "árboles de sombra y reforestación para fincas de café"), ("fr", "arbres d'ombrage et reboisement pour les plantations de cacao")):
    r = q(text); ids = [x["metadata"].get("projectId") for x in r]
    known = [i for i in ids if i in bundle]
    print(lang, len(r), "results;", len(known), "resolve to validated rows")
    if not r or len(known) != len(ids): fails.append(f"{lang}: empty or unresolved ids")
    for x in r:
        m = x["metadata"]
        if m.get("curationStatus") != "not_curated" or m.get("origin") != "public_source_data": fails.append(f"{lang}: provenance metadata wrong")
r = q("water conservation", "CO")
if any(x["metadata"].get("countryIso2") != "CO" for x in r): fails.append("scope filter leaked another country")
print("scope filter CO:", len(r), "results")
print("FAILED: " + "; ".join(fails) if fails else "ok: retrieval verified"); sys.exit(1 if fails else 0)
