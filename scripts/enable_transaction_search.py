#!/usr/bin/env python3
"""One-time, account-and-region level: send X-Ray trace segments to CloudWatch Logs (CloudWatch Transaction Search) so AgentCore/ADOT spans show up in the GenAI Observability dashboard.
Changes an account setting, so it is a separate, explicit step. Idempotent. Optional sampling percentage (default 1, the free tier).
  AWS_PROFILE=breaking-barriers-ny uv run --project agent python scripts/enable_transaction_search.py [--sampling 1]
"""
import argparse, json
import boto3

ap = argparse.ArgumentParser(); ap.add_argument("--sampling", type=float, default=1.0); a = ap.parse_args()
s = boto3.Session(region_name="us-west-2"); acct = s.client("sts").get_caller_identity()["Account"]
logs, xray = s.client("logs"), s.client("xray")
policy = {"Version": "2012-10-17", "Statement": [{"Sid": "TransactionSearchXRayAccess", "Effect": "Allow", "Principal": {"Service": "xray.amazonaws.com"}, "Action": "logs:PutLogEvents",
    "Resource": [f"arn:aws:logs:us-west-2:{acct}:log-group:aws/spans:*", f"arn:aws:logs:us-west-2:{acct}:log-group:/aws/application-signals/data:*"],
    "Condition": {"ArnLike": {"aws:SourceArn": f"arn:aws:xray:us-west-2:{acct}:*"}, "StringEquals": {"aws:SourceAccount": acct}}}]}
logs.put_resource_policy(policyName="TransactionSearchXRayAccess", policyDocument=json.dumps(policy))
cur = xray.get_trace_segment_destination().get("Destination")
if cur != "CloudWatchLogs": xray.update_trace_segment_destination(Destination="CloudWatchLogs")
xray.update_indexing_rule(Name="Default", Rule={"Probabilistic": {"DesiredSamplingPercentage": a.sampling}})
print("destination:", xray.get_trace_segment_destination().get("Destination"), "| sampling", a.sampling, "%")
