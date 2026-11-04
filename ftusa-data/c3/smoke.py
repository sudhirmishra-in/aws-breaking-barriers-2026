"""Call all four tools once against a backend and print the results.

    python -m c3.smoke --backend memory [--account-sk <sk>]
    python -m c3.smoke --backend aws --region us-east-1 --table-prefix ftusa_c3_ --vector-bucket ftusa-c3-vectors --vector-index peer-projects
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .access import DataAccess, Session
from .catalog import Catalog
from .tools import impl_describe_dataset, impl_find_similar_projects, impl_get_producer_record, impl_query


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["memory", "aws"], default="memory")
    ap.add_argument("--tables", default="out/tables")
    ap.add_argument("--account-sk")
    ap.add_argument("--region")
    ap.add_argument("--table-prefix", default="ftusa_c3_")
    ap.add_argument("--vector-bucket", default="ftusa-c3-vectors")
    ap.add_argument("--vector-index", default="peer-projects")
    a = ap.parse_args(argv)

    if a.backend == "memory":
        from .items import build_all
        from .store_memory import InMemoryStore

        built = build_all(a.tables)
        da = DataAccess(InMemoryStore(built), Catalog(stats=built["stats"]))
    else:
        from .store_aws import DynamoS3Store

        stats = Path(a.tables).parent / "catalog_stats.json"
        da = DataAccess(DynamoS3Store(a.table_prefix, a.vector_bucket, vector_index=a.vector_index, region=a.region), Catalog.with_stats_file(stats))

    sk = a.account_sk
    if not sk:
        import pandas as pd

        c = pd.read_csv(Path(a.tables).parent / "review" / "scenario_candidates.csv")
        sk = c[c.has_survey].iloc[0].account_sk
    s = Session(sk)
    rec = impl_get_producer_record(da, s)
    country = rec.get("profile", {}).get("country", "Colombia")
    for name, out in [
        ("get_producer_record", rec),
        ("find_similar_projects", impl_find_similar_projects(da, s, "sequía y falta de agua para riego", top_k=3)),
        ("query", impl_query(da, s, "projects", {"country": country, "primary_tag": "water"}, 3)),
        ("describe_dataset", impl_describe_dataset(da, "survey_summaries")),
    ]:
        print(f"\n=== {name}\n{json.dumps(out, ensure_ascii=False, indent=1, default=str)[:1500]}")


if __name__ == "__main__":
    main()
