"""Ingest module: Open-Meteo historical precipitation (ERA5 reanalysis).

Dataset theme: ``climate``. Provides country-level annual rainfall — the
current year's total and its delta against the 1981–2010 climatology — so the
agent can say "in your country, rainfall was X mm in 2025, Y% below the
1981–2010 average" (OPEN-10 → snapshot + baseline comparison).

Source note (honest attribution): the CHIRPS raster portal is a JS app with no
stable scriptable GeoTIFF URLs, so per the agreed fallback this ingest uses
Open-Meteo's open archive API (ERA5 reanalysis) at each country's centroid.
The fetch/aggregate interface is source-agnostic — a CHIRPS raster can drop in
later by swapping only the ``_fetch`` step.

Run:  AWS_PROFILE=breaking-barriers-ny .venv/Scripts/python.exe -m external_data.ingest.open_meteo
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
import urllib.request

from external_data import access, gazetteer as gaz

DATASET = "open_meteo"
THEME = "climate"
INDICATOR = "ytd_rainfall_mm"      # year-to-date total (renamed from annual_rainfall_mm)
OLD_INDICATOR = "annual_rainfall_mm"  # superseded; cleared on re-ingest
HORIZON = "current"
BASELINE_PERIOD = "1981-2010 (same window)"
DELAY_BUFFER_DAYS = 7  # safely past the ~5-day ERA5 archive delay
API = "https://archive-api.open-meteo.com/v1/archive"
UA = {"User-Agent": "ftusa-ingest/1.0 (hackathon)"}


def _centroid(country: str):
    """A representative point for the country: the centroid of its largest
    polygon part (islands excluded), so the estimate sits on mainland."""
    geom = gaz.get_geometry(country)
    if geom is None:
        return None
    parts = sorted(geom.geoms, key=lambda p: p.area, reverse=True) \
        if geom.geom_type == "MultiPolygon" else [geom]
    return parts[0].representative_point()


def _fetch(lat: float, lon: float, start: str, end: str, retries: int = 4) -> list[tuple[str, float]]:
    """(date, precipitation_sum) pairs for a date range, nulls dropped, with
    retry + backoff for the transient empty responses the archive API
    occasionally returns."""
    url = (f"{API}?latitude={lat:.3f}&longitude={lon:.3f}"
           f"&start_date={start}&end_date={end}&daily=precipitation_sum&timezone=auto")
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=180) as r:
                daily = json.load(r)["daily"]
            pairs = [(d, p) for d, p in zip(daily["time"], daily["precipitation_sum"])
                     if p is not None]
            if pairs:
                return pairs
            last_err = "empty precipitation response"
        except Exception as e:  # noqa: BLE001 - retry any transient failure
            last_err = e
        time.sleep(2 ** attempt)
    raise RuntimeError(f"Open-Meteo fetch failed after {retries} tries: {last_err}")


def _write_stand_in(rk: str, period: str, reason: str,
                    profile: str | None = None) -> None:
    """Write a flagged stand-in fact (ING-5): no value, `is_stand_in: True`, so
    the agent says 'no reliable data' instead of the ingest crashing or the
    agent inventing a figure."""
    access.put_fact(
        rk, DATASET, INDICATOR, HORIZON,
        value=None, unit="mm", period=period,
        method=f"STAND-IN: no reliable value ({reason}); the agent must say so",
        theme=THEME, is_stand_in=True, profile=profile,
    )


def ingest_country(country: str, profile: str | None = None) -> dict | None:
    """Aggregate one country's rainfall and write the fact. On a fetch failure
    it writes a flagged stand-in instead of raising (ING-5). Returns the shaped
    fact, or None if the country is unknown (GZ-3: no geometry, skip)."""
    pt = _centroid(country)
    if pt is None:
        print(f"  ! {country}: no gazetteer geometry, skipped")
        return None

    now = dt.datetime.now(dt.timezone.utc)
    current_year = now.year
    start = dt.date(current_year, 1, 1)
    end = (now - dt.timedelta(days=DELAY_BUFFER_DAYS)).date()  # past the ERA5 delay
    period = f"{current_year} YTD ({start:%m-%d} to {end:%m-%d})"
    em, ed = end.month, end.day
    rk = gaz.region_key(country)

    try:
        # current: the year-to-date total through the last safely-available day
        cur_pairs = _fetch(pt.y, pt.x, start.isoformat(), end.isoformat())
        current_total = round(sum(p for _, p in cur_pairs), 1)

        # baseline: the SAME calendar window, averaged over 1981-2010 — a fair
        # comparison (a partial year vs a full-year mean would falsely look dry)
        window: dict[str, float] = {}
        for d, p in _fetch(pt.y, pt.x, "1981-01-01", "2010-12-31"):
            if (int(d[5:7]), int(d[8:10])) <= (em, ed):
                window[d[:4]] = window.get(d[:4], 0.0) + p
        baseline = round(sum(window.values()) / len(window), 1)
        delta_pct = round((current_total - baseline) / baseline * 100, 1)

        access.put_fact(
            rk, DATASET, INDICATOR, HORIZON,
            value=current_total, unit="mm", period=period,
            method="ERA5 reanalysis via Open-Meteo archive API; YTD at country centroid vs same-window 1981-2010 average",
            theme=THEME, baseline_value=baseline, baseline_delta_pct=delta_pct,
            baseline_period=BASELINE_PERIOD, profile=profile,
        )
        # clear the superseded annual figure so the region holds one rainfall fact
        access.delete_fact(rk, DATASET, OLD_INDICATOR, HORIZON, profile=profile)
        print(f"  {country:10} {period}={current_total} mm | "
              f"1981-2010 same-window={baseline} mm | {delta_pct:+.1f}%")
    except Exception as e:  # noqa: BLE001 - stand-in instead of failing (ING-5)
        _write_stand_in(rk, period, f"fetch failed: {e}", profile)
        print(f"  {country:10} STAND-IN (fetch failed: {e})")
    return access.get_facts(rk, themes={THEME}, horizon=HORIZON, profile=profile)[0]


def ingest_all(profile: str | None = None) -> int:
    n = 0
    for c in gaz.list_countries():
        try:
            if ingest_country(c, profile=profile) is not None:
                n += 1
        except Exception as e:  # noqa: BLE001 - backstop; one country never kills the rest
            print(f"  ! {c}: unexpected ingest error: {e}")
    print(f"ingested {n} countries -> {access.TABLE_NAME}")
    return n


def main() -> None:
    ingest_all()


if __name__ == "__main__":
    sys.exit(0 if ingest_all() else 1)
