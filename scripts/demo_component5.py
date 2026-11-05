"""Component 5 handoff demo — proves the pipeline works with NO agent.

Run:  AWS_PROFILE=breaking-barriers-ny .venv/Scripts/python.exe scripts/demo_component5.py

This is the acceptance test for the handoff to Component 2 (the Strands agent).
It ensures the table exists, ingests any country that has no cached fact yet
(idempotent — no redundant API calls), then calls the tool directly and prints
the grounded, cited facts the agent will receive.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# NFR-4: surface the tool's observability logs; keep boto3's own chatter down.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("boto3").setLevel(logging.WARNING)

from external_data import access  # noqa: E402
from external_data.ingest import open_meteo  # noqa: E402
from external_data.tool import get_environmental_context  # noqa: E402


def main() -> int:
    access.ensure_table()

    # Ingest only the countries that don't already have a cached fact.
    missing = [c for c in _countries()
               if not access.get_facts(f"{c}#COUNTRY", horizon="any")]
    if missing:
        print(f"ingesting {len(missing)} country/countries: {missing}")
        for c in missing:
            open_meteo.ingest_country(c)
    else:
        print("all pilot countries already cached; skipping ingest")

    print("\n--- tool call: get_environmental_context ---")
    for label, loc, tags in [
        ("Peru / climate", {"country": "Peru", "region": "Cajamarca"}, ["climate and weather"]),
        ("Mexico / drought", {"country": "Mexico"}, ["drought"]),
        ("Vietnam / climate", {"country": "Vietnam"}, ["climate and weather"]),
    ]:
        print(f"\n[{label}]  location={loc}  tags={tags}")
        print(json.dumps(get_environmental_context(loc, tags), indent=2))
    return 0


def _countries() -> list[str]:
    from external_data import gazetteer
    return gazetteer.list_countries()


if __name__ == "__main__":
    raise SystemExit(main())
