"""One-time build of the country gazetteer cache (GZ-2).

Downloads Natural Earth admin-0 (open, no account), extracts the pilot
countries, and writes a minimal cached GeoJSON to
``external_data/data/countries.geojson``. Re-running is idempotent.

Run:  .venv/Scripts/python.exe scripts/build_gazetteer.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import urllib.request
from pathlib import Path

# Natural Earth admin-0 countries, GeoJSON. The GitHub mirror is the reliable
# open copy (the official CDN 403s non-browser clients).
SOURCES = [
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_countries.geojson",
    "https://www.naturalearthdata.com/http//www.naturalearthdata.com/download/10m/cultural/ne_10m_admin_0_countries.geojson",
]

# Pilot countries (CON-4): Colombia / Peru / Mexico / Honduras (+ Vietnam).
PILOT = {"colombia", "peru", "mexico", "honduras", "vietnam", "ivory coast"}  # Natural Earth calls Cote d'Ivoire "Ivory Coast" (the demo's cocoa country)
DISPLAY = {"ivory coast": "Côte d'Ivoire"}

OUT = Path(__file__).resolve().parent.parent / "external_data" / "data" / "countries.geojson"
UA = {"User-Agent": "ftusa-gazetteer-build/1.0 (hackathon)"}


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def main() -> int:
    raw, used = None, None
    for url in SOURCES:
        try:
            raw = _download(url)
            used = url
            break
        except Exception as e:  # noqa: BLE001 - try the next mirror
            print(f"  ! {url}\n    {e}", file=sys.stderr)
    if raw is None:
        print("ERROR: could not download Natural Earth admin-0 from any source", file=sys.stderr)
        return 1
    print(f"downloaded admin-0 ({len(raw)//1024} KB) from {used}")

    with tempfile.NamedTemporaryFile(suffix=".geojson", delete=False) as f:
        f.write(raw)
        tmp = f.name
    with open(tmp, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    feats, found = [], set()
    for feat in data["features"]:
        props = feat["properties"]
        # Natural Earth uses uppercase keys. The country's own name is in
        # ``NAME`` (title case); ``SOVEREIGNT`` holds the lowercase sovereign
        # state, which equals the country name for our pilot set.
        display = (props.get("NAME") or props.get("SOVEREIGNT") or "").strip()
        match_key = display.lower()
        if match_key not in PILOT:
            sov = (props.get("SOVEREIGNT") or "").strip().lower()
            match_key = sov if sov in PILOT else match_key
        if match_key in PILOT:
            found.add(match_key)
            feats.append({
                "type": "Feature",
                "properties": {
                    "name": DISPLAY.get(match_key, display),
                    "iso_n3": props.get("ISO_N3"),
                },
                "geometry": feat["geometry"],
            })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": feats}, fh)

    missing = PILOT - found
    print(f"wrote {len(feats)} country geometries -> {OUT}")
    print(f"found: {sorted(found)}")
    if missing:
        print(f"MISSING (will fall back / be unavailable): {sorted(missing)}")
    return 0 if not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
