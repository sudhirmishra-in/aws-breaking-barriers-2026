#!/usr/bin/env python3
"""Start a Knowledge Base ingestion job for the project cards and report created/updated/failed counts. The KB is NOT ready until this reports zero failures.
  AWS_PROFILE=breaking-barriers-ny uv run --project agent python scripts/kb_sync.py --stack FtusaExchange-sandbox
"""
import argparse, sys, time
import boto3

ap = argparse.ArgumentParser(); ap.add_argument("--stack", required=True); a = ap.parse_args()
assert "sandbox" in a.stack
s = boto3.Session(region_name="us-west-2")
o = {x["OutputKey"]: x["OutputValue"] for x in s.client("cloudformation").describe_stacks(StackName=a.stack)["Stacks"][0]["Outputs"]}
if "KnowledgeBaseId" not in o: sys.exit("stack has no Knowledge Base (deploy with -c enableKnowledgeBase=true)")
c = s.client("bedrock-agent")
job = c.start_ingestion_job(knowledgeBaseId=o["KnowledgeBaseId"], dataSourceId=o["KnowledgeBaseDataSourceId"])["ingestionJob"]
while job["status"] in ("STARTING", "IN_PROGRESS"):
    time.sleep(10); job = c.get_ingestion_job(knowledgeBaseId=o["KnowledgeBaseId"], dataSourceId=o["KnowledgeBaseDataSourceId"], ingestionJobId=job["ingestionJobId"])["ingestionJob"]
st = job.get("statistics", {})
print("status", job["status"], {k: st.get(k) for k in ("numberOfDocumentsScanned", "numberOfNewDocumentsIndexed", "numberOfModifiedDocumentsIndexed", "numberOfDocumentsDeleted", "numberOfDocumentsFailed")})
if job.get("failureReasons"): print("failure reasons (first of %d):" % len(job["failureReasons"]), job["failureReasons"][0][:400])
sys.exit(0 if job["status"] == "COMPLETE" and not st.get("numberOfDocumentsFailed") else 1)
