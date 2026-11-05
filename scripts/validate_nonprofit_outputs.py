#!/usr/bin/env python3
"""Validate the COMMITTED outputs of the nonprofit ingestion (no raw source needed): provenance, no invented outcomes/standards, no internal account keys in the served subset."""
import json, sys
from pathlib import Path
R = Path(__file__).resolve().parent.parent
out = R / "data" / "nonprofit-public"; ld = lambda p: json.loads(p.read_text())
m, e, pr, d = ld(out / "manifest.json"), ld(out / "exception_report.json"), ld(out / "projects.json")["projects"], ld(out / "demo_accounts.json")["accounts"]
served = ld(R / "backend/src/data/public_projects.json")
errs = []
ck = lambda ok, msg: ok or errs.append(msg)
ck(all(f["sha256"] and f["rows"] > 0 for f in m["files"].values()), "every source file fingerprinted with rows")
ck(m["ingestionVersion"] == e["ingestionVersion"] == served["ingestionVersion"], "one ingestion version across outputs")
ck(all(p["outcome"] == "not_reported" and p["origin"] == "public_source_data" and p["curationStatus"] == "not_curated" for p in pr), "projects: outcome not_reported, public origin, not curated")
ck(all("standard" not in k.lower() for p in pr for k in p), "no standards fields")
ck(len({p["projectId"] for p in pr}) == len(pr), "unique project ids")
ck("account_sk" not in json.dumps(served) and "accountSk" not in json.dumps(served), "served subset has no account keys")
ck(len(served["projects"]) == sum(p["usableAsRegionalPrecedent"] for p in pr), "served = usable projects")
sc, mc = e["single_choice"], e["multi_choice"]
ck(sc["total"] == sum(sc["classification"].values()) and mc["total"] == sum(mc["classification"].values()), "classification totals add up")
ck(all(v["quarantinedRowsForThisAccount"] == {"single": 0, "multi": 0} for v in d.values()), "demo accounts have no conflicting rows")
ck(all(s["responsesInScope"] >= s["answered"] for v in d.values() for s in v["singleChoiceSummaries"]), "answered never exceeds responses in scope")
ck(all(o <= q["denominatorResponses"] for v in d.values() for q in v["multipleChoiceSummaries"].values() for o in q["options"].values()), "option counts never exceed their denominator")
print("quarantined:", {"single": sc["quarantinedRows"], "multi": mc["quarantinedRows"]})
if errs: print("FAILED:\n - " + "\n - ".join(errs)); sys.exit(1)
print("ok: nonprofit outputs valid, ingestion", m["ingestionVersion"])
