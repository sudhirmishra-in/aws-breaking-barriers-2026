# Component 5 — External Datasets (Climate, Soil, Water, Biodiversity, Tenure, Prices, Elevation)

**Status:** v1.0 (detailed). Component-level requirements. The system overview lives in `OVERALL.md` (this folder); cross-component requirements, constraints, and acceptance criteria are in `../REQUIREMENTS.md`. The dataset set is folded in from `../notes.txt`.

---

## Architecture (at a glance)

```
   COMPONENT 5 — EXTERNAL DATA, PRE-EXTRACTED & CACHED
═══════════════════════════════════════════════════════════════════

  OFFLINE — ingest (pre-extract; run once / on refresh)
  ──────────────────────────────────────────────────────────────────
   open external datasets
   CHIRPS (now) · SoilGrids · WDPA · World Bank · … (later)
                      │ fetch
                      ▼
   ┌──────────────────────────────────────────┐
   │ INGEST MODULE (one per dataset)          │
   │ fetch → aggregate to country → cache     │
   │ rasterio / shapely — heavy geospatial    │
   │ compute HERE, never on the hot path      │
   │ baseline (1981-2010) at ingest           │
   └──────────────────────────────────────────┘
                        │ region geometry
                        ▼
   ┌──────────────────────────────────────────┐
   │ REGION GAZETTEER (the keystone)          │
   │ country → boundary (no coords in data)   │
   │ producer data has no coordinates         │
   └──────────────────────────────────────────┘
                        │ upsert (idempotent)
                        ▼
   ┌──────────────────────────────────────────┐
   │ DynamoDB  environmental_facts            │
   │ PK region_key   SK dataset#indicator     │
   │ #horizon · value · baseline_* · flags    │
   └──────────────────────────────────────────┘

  ONLINE — read (hot path, every producer turn)
  ──────────────────────────────────────────────────────────────────
   STRANDS AGENT  (Bedrock Claude)
   │  picks a tool by name + args — Strands built the
   │  tool's JSON schema from its Python signature
   │  + docstring (no hand-written schema)
   ▼
   ┌──────────────────────────────────────────┐
   │ TOOL  get_environmental_context(         │
   │        location, tags, horizon)          │
   │ plain Python fn · Strands runs the call  │
   │ loop, executes it, returns the result    │
   │ to the model                             │
   └──────────────────────────────────────────┘
                        │  one partition query + in-code
                        │  theme/horizon filter (bounded, cited)
                        ▼
   Query(environmental_facts, region_key)
   ▼
   shaped facts  (value + baseline + attribution + flags)
   →  no network fetch · no geospatial compute on the hot path
```

The agent↔data integration is **tool-based**: the model never queries a store directly — it calls the `get_environmental_context` tool (a plain Python function whose JSON schema Strands generates from the signature + docstring), and Strands runs the call loop. All geospatial work — fetch, country aggregation, baseline — runs once at ingest; the tool itself is a single DynamoDB partition query plus an in-code theme/horizon filter, which is the entire hot path.

---

## 1. Purpose

Ground the agent's answers in **real external geospatial/climate data** for the producer's region — not just weather, but soil, water, forest, protected areas, community lands, commodity prices, and elevation. This is the "what does the environment/climate data show for this challenge, crop, and region" part of the agent's answer. The component supports both **current-condition** statements and **forward-looking** projections (e.g. "water stress is projected to worsen by 2030"), and every figure is attributable (dataset, period, method).

## 2. Scope

**In scope (this component):**
- The dataset set from `notes.txt` (climate, soil/land, water, biodiversity/tenure, market, elevation, satellite)
- A region gazetteer that bridges the anonymized producer data (names, no coordinates) to gridded data
- Ingest modules that aggregate each dataset to per-region indicators
- A cached store of regional facts
- The `get_environmental_context` tool
- The theme → challenge-tag mapping
- Current-vs-forward-looking (horizon) handling

**Out of scope (this component):** the agent that calls the tool (C2); the structured producer/project/survey data (C3); standards RAG (C4); conversation save/KB (C6); the UI (C1).

**Demo scope (decided 2026-11-04):** start with **CHIRPS only**, aggregated at **country level**, from **open** sources only. Extend to the other open datasets (SoilGrids, WDPA, World Bank, Open-Meteo, JRC, LandMark) only if there is time. Account-gated sources (Aqueduct, ERA5/Copernicus) are deferred — no credentials are available (OPEN-8/7/9, §13).

---

## 3. The dataset set (folded in from `notes.txt`)

| Dataset | Theme | Provides | Horizon | Access |
|---|---|---|---|---|
| **CHIRPS** | Climate | Rainfall averages (precipitation) | Current | Open (GeoTIFFs, data portal / GCS) |
| **ERA5** | Climate | Temperature / precipitation reanalysis; flags shifting rainfall & heat patterns | Current + trend | Copernicus (account) |
| **ISRIC SoilGrids** | Soil & land | Soil carbon, pH, texture, degradation | Current | Open (raster) |
| **JRC Tropical Moist Forest** | Land | Forest cover, loss, degradation | Current + trend | Open |
| **WRI Aqueduct Water Risk Atlas** | Water | Water stress — current **and** projected 2030 / 2050 | Current + forward | Account |
| **WDPA** (World Database on Protected Areas) | Biodiversity | Protected areas (cover, extent) | Current | Open (shapefile) |
| **LandMark** | Tenure | Indigenous / community lands (FPIC context) | Current | Open |
| **World Bank** | Market | Commodity prices (coffee, cocoa, …) | Current + trend | Open |
| **Open-Meteo** | Elevation | Elevation / topography | Static | Open (API) |
| **Satellite imagery** | Land | Forest, land-use, fire monitoring | Current | Varies |

**Themes** (each maps to challenge tags, §4): `climate`, `soil_land`, `water`, `biodiversity`, `tenure`, `market`, `elevation`.

---

## 4. Theme → challenge-tag mapping

Each dataset theme maps to one or more of the 11 challenge tags, so `get_environmental_context` returns only the data relevant to the challenge the producer is describing.

| Theme | Challenge tag(s) it supports |
|---|---|
| `climate` (CHIRPS, ERA5) | climate and weather |
| `water` (Aqueduct) | water |
| `soil_land` (SoilGrids, JRC, satellite) | soil and land; biodiversity and conservation |
| `biodiversity` (WDPA) | biodiversity and conservation |
| `tenure` (LandMark) | social and community |
| `market` (World Bank) | market and price |
| `elevation` (Open-Meteo) | (context for climate / infrastructure) |

The mapping is data-driven (in the catalog), not in the prompt — the model never has to know which dataset backs which tag.

---

## 5. The region gazetteer (the keystone)

The producer data carries **country + region name, but no coordinates** (CON-1). External datasets are geographic (gridded rasters, vector polygons). The bridge is a **region gazetteer**:

- **GZ-1.** A gazetteer maps `(country, region_name)` → a geometry (bounding box or polygon) for every pilot region that appears in the producer data.
- **GZ-2.** The gazetteer is built once (from an open administrative-boundary source, e.g. GeoNames / GADM) and checked into the repo or cached. It is the only place that knows region geometry.
- **GZ-3.** A region with no gazetteer entry falls back to **country-level** aggregation (coarser, but always available) and is labeled as such.
- **GZ-4.** Because the producer data has no coordinates, the environmental context is resolved at the **named-region or country level** — never a precise point. The agent states the geographic scope it's citing ("in your region" / "in your country").

---

## 6. Ingest modules

One module per dataset. Each: **fetch → aggregate to region → write to cache.**

- **ING-1 (Fetch.)** Pull the raw data. Raster datasets (CHIRPS, ERA5, SoilGrids, JRC, Aqueduct, Open-Meteo) via their data portals / buckets; vector datasets (WDPA, LandMark) as shapefiles/GeoJSON; tabular (World Bank prices) as CSV/API.
- **ING-2 (Aggregate.)** Using the gazetteer geometry (§5), reduce the dataset to a **per-region indicator** — e.g. mean rainfall over the region's cells, water-stress score for the region, % forest cover, count/area of protected areas intersecting the region, farmgate price for the crop. Raster aggregation via `rasterio`; vector via `shapely`/`geopandas`.
- **ING-3 (Horizon + baseline.)** Capture the horizon. The demo produces only `current` facts (OPEN-10 → snapshot + baseline comparison, §13). Each `current` fact also stores its **baseline comparison**: the long-term reference value and the delta against it (e.g. `value: 820 mm`, `baseline_value: 1052 mm`, `baseline_delta_pct: -22`, `baseline_period: '1981–2010 average'`). Projections (`2030`/`2050`) and `trend` remain schema dimensions that yield no rows in the demo — reserved, not populated.
- **ING-4 (Attribution.)** Every fact stores its `dataset`, `indicator`, `value`, `period`, `method`, and `is_projection` / `is_stand_in` flags.
- **ING-5 (Open vs account.)** Open datasets (CHIRPS, SoilGrids, WDPA, LandMark, Open-Meteo, World Bank) need no auth. Account-gated ones (Aqueduct, ERA5/Copernicus) need credentials; if a credential is absent, the module writes a clearly-flagged **stand-in** value instead of failing (the agent must say so if it cites one).
- **ING-6 (Idempotent + cache.)** Ingest writes to the cache (§7); re-running overwrites the same region/dataset/indicator/horizon keys. It's a pre-extract, not a per-call pull.

---

## 7. Cache / store

- **CACHE-1 (DynamoDB `environmental_facts`).** One item per `(region, dataset, indicator, horizon)`. **PK = `region_key`** (`country#region_name`, or `country#COUNTRY` for the country-level fallback), **SK = `dataset#indicator#horizon`**. Attributes: `value`, `unit`, `period`, `method`, `baseline_value`, `baseline_delta_pct`, `baseline_period`, `is_projection`, `is_stand_in`, `theme`, `retrieved_at`.
- **CACHE-2 (Read path.)** `get_environmental_context` reads by the region's partition key, then filters in code by the requested themes — a single partition query, no scan.
- **CACHE-3 (Bounded.)** A region has a small, fixed set of facts (a handful of datasets × indicators × horizons). The tool returns at most the facts matching the requested themes.

---

## 8. The tool

### `get_environmental_context(location, tags, horizon="current")`
- **Purpose:** the external environmental/climate context for a producer's region, filtered to the challenge being addressed.
- **Input:** `location` (the session's country + region — never free model text), `tags` (the challenge tag(s) from the conversation), `horizon` (`current` | `2030` | `2050` | `trend`; the demo stores only `current`, §13).
- **Implementation:** map `tags` → themes (§4) → `Query(environmental_facts, region_key)` → filter to the matched themes and horizon.
- **Output:**
  ```json
  [ { "dataset", "theme", "indicator", "value", "unit", "period",
      "method", "baseline_value", "baseline_delta_pct", "baseline_period",
      "is_projection", "is_stand_in", "geographic_scope": "region" | "country" } ]
  ```
- **Attribution (CLIM-4).** Every returned fact carries its dataset, period, and method; projections carry `is_projection: true`; stand-ins carry `is_stand_in: true`. The agent must state the source and label projections/stand-ins.
- **Bounded.** Returns only the facts for the requested themes + horizon for that region — never the whole cache.
- **Empty case.** If a region/theme has no cached fact, the tool returns an empty list (not an error), so the agent can say "no external data for that" rather than invent a figure.

---

## 9. Current vs forward-looking

- **FWD-1.** The horizon is a first-class dimension (§6 ING-3, §7 SK). Current-condition facts and projected-future facts are separate rows.
- **FWD-2 (reserved in demo).** The agent may make **forward-looking statements** ("water stress is projected to worsen by 2030") only from `is_projection` facts, and must label them as projections. No `is_projection` rows are produced in the demo (OPEN-9, no Aqueduct/ERA5), so the rule is armed but never fires.
- **FWD-3 (reserved in demo).** Trend facts (ERA5 rainfall/heat shift, World Bank price trend, JRC forest-loss trend) would be stored as a horizon=`trend` row with the period of the trend. OPEN-10 excluded `trend` from the demo, so no `trend` rows are produced; the dimension is reserved.

---

## 10. Constraints & assumptions

- **CON-1 (No coordinates.)** The producer data has country + region name only. Environmental context is resolved via the gazetteer at named-region or country level (§5) — never a precise point.
- **CON-4 (Geography.)** Pilot regions are in Colombia / Peru / Mexico / Honduras (+ Vietnam). The gazetteer and pre-extract cover those.
- **CON-6 (Model access.)** Any model use (e.g. summarizing a fact) goes through Bedrock.
- **EXT-1 (Open vs account.)** Some datasets are open; Aqueduct and ERA5 are account-gated. Missing credentials → flagged stand-in, never a silent failure (§6 ING-5).
- **EXT-2 (Pre-extract, not live.)** All external data is pre-aggregated and cached; the tool never pulls a dataset on a call.

---

## 11. Non-functional requirements

- **NFR-1 (Latency.)** The tool is a single DynamoDB partition query + in-code filter — no network fetch, no geospatial compute on the hot path (all aggregation happens at ingest).
- **NFR-2 (Scale.)** Adding a dataset = a new ingest module + catalog entry + theme mapping; the tool and cache schema are unchanged.
- **NFR-3 (Cost.)** Account-gated datasets (Aqueduct, ERA5) may have usage limits; the pre-extract pulls a bounded set of pilot regions, not the globe.
- **NFR-4 (Observability.)** Log each tool call, the region/tags/horizon requested, and the facts returned (with their attribution flags).

---

## 12. Acceptance criteria (component-level)

- **ACC-1.** A producer in a known drought region gets a real rainfall figure with its source, period, and method; the agent cites it. *In the demo the figure is ERA5 reanalysis via Open-Meteo at the country centroid (OPEN-11), attributed honestly — not the CHIRPS raster, whose portal is not scriptable.*
- **ACC-2 (deferred — no Aqueduct access).** *When* water-stress data is available, a forward-looking statement uses the projected horizon and is labeled a projection (`is_projection`), not stated as current fact.
- **ACC-3.** A soil-health / agroforestry challenge gets **SoilGrids** carbon/pH and **JRC** forest-cover facts.
- **ACC-4.** A stewardship / community-lands claim gets **WDPA** protected-area and **LandMark** community-land context.
- **ACC-5.** A price challenge gets a **World Bank** commodity-price fact (with period).
- **ACC-6.** A region with no gazetteer entry falls back to country-level facts, labeled `geographic_scope: "country"`.
- **ACC-7.** A dataset whose credentials are absent yields a flagged `is_stand_in` fact, and the agent says so.
- **ACC-8.** The tool returns only facts matching the requested themes + horizon for that region; an unmatched theme returns an empty list, not an error.

---

## 13. Decisions and open items

**Decided (2026-11-04):**
- **OPEN-8 → CHIRPS first.** Ingest CHIRPS (country-level rainfall) before anything else; add the other open datasets only if there is time.
- **OPEN-7 → country level.** The gazetteer maps country → boundary; no sub-region geometry for the demo. `geographic_scope` is always `country`.
- **OPEN-9 → no account access.** Aqueduct and ERA5/Copernicus are deferred (no credentials). All demo data comes from open sources; the stand-in path (§6 ING-5) now covers fetch failures, not missing credentials.

- **OPEN-10 → Snapshot + baseline ((a)+(b)).** Every stored fact is a `current` snapshot plus its delta against a long-term reference (e.g. *"820 mm — 22% below the 1981–2010 average"*). The baseline fields live on the fact row, not as a separate horizon (§6 ING-3, §7 CACHE-1). Multi-year `trend` and future `2030`/`2050` projections remain reserved schema dimensions that yield no rows in the demo — addable later with no schema change.
- **OPEN-11 (implementation) → Rainfall source is Open-Meteo ERA5, not the CHIRPS raster.** The CHIRPS raster portal (`data.chc.ucsb.edu`) is a JavaScript app with no stable scriptable GeoTIFF URLs, and the World Bank CCKP sits behind a Cloudflare challenge — both confirmed non-scriptable. Per the agreed fallback (OPEN-8's "add if there is time" / option 2), the demo's rainfall dataset is **Open-Meteo's open archive API (ERA5 reanalysis)**, aggregated at each country's centroid. It still honours OPEN-9 (no account): Open-Meteo's archive API is open, distinct from account-gated Copernicus access. Attribution is honest — `dataset: open_meteo`, method *"ERA5 reanalysis via Open-Meteo archive API; point estimate at country centroid."* The ingest's fetch/aggregate interface is source-agnostic, so a CHIRPS raster drops in later by swapping only the `_fetch` step.
- **OPEN-12 (implementation) → "current" = year-to-date, compared to the same window.** The current rainfall figure is **2026 YTD** (Jan 1 through the last safely-available day, using a 7-day buffer past the ~5-day ERA5 delay). The baseline is *not* the full-year 1981–2010 mean — it is the **same calendar window** (Jan 1 → the same day) averaged over 1981–2010, so the comparison is fair: a partial year would otherwise always look artificially dry against a full-year total. The indicator is `ytd_rainfall_mm` (the earlier `annual_rainfall_mm` was cleared on re-ingest), unit is `mm`, and the period is labeled e.g. *"2026 YTD (01-01 to 10-28)."*

**Still open:** none.

---

## 14. Deployment (integrated with the product stack)

Component 5 ships inside the existing `FtusaExchange-<env>` CloudFormation stack (CDK, `infra/lib/exchange-stack.ts`) — no separate deploy. Four integration points, all in this branch:

- **Packaging (step 1).** The agent zip (`scripts/build_agent.sh`) now copies `external_data/` into the package (`cp -R ../external_data build/pkg/`), so `get_environmental_context` and its gazetteer (including `data/countries.geojson`) are in the deployed AgentCore runtime. `shapely` is added to `agent/pyproject.toml` because the gazetteer imports it at module load. shapely 2.2.0 hard-depends on numpy, and both ship aarch64 wheels only for `manylinux_2_24`/`manylinux_2_28` (glibc 2.24+/2.28+), so the build target is `aarch64-manylinux_2_28` (was `manylinux2014`) — that matches the AgentCore Amazon Linux 2023 runtime (glibc 2.34) and stays compatible with the original pure-Python deps. Prebuilt wheels are used, so no source build or C compiler is needed.
- **Table (step 3).** The stack creates the facts table as `ftusa-environmental-facts-<env>` (PK `region_key`, SK `fact_key`, on-demand, KMS-encrypted, PITR off, removal policy matching the other tables) and exposes its name as the `EnvironmentalFactsTable` stack output.
- **IAM (step 2).** The AgentCore `RuntimeRole` is granted read-only DynamoDB access to that table (`grantReadData`), so the tool's partition query is authorized. The API Lambda and the runtime never get write access — the table is read-only at runtime by design.
- **Manual ingest (step 4).** The table name is read from `ENVIRONMENTAL_FACTS_TABLE` (default `environmental_facts` for local dev; the stack sets it to the CDK table name on the runtime). Nothing in the deploy runs the ingest — it is an **offline, manual** step an operator runs to populate the table:

  ```bash
  # from the repo root, with credentials that can write to the CDK table in us-west-2
  ENVIRONMENTAL_FACTS_TABLE=ftusa-environmental-facts-sandbox \
    AWS_PROFILE=<profile> <python> -m external_data.ingest.open_meteo
  ```

  It's idempotent (re-running overwrites the same region/dataset/indicator/horizon keys). Until it's run against a freshly deployed environment, the table is empty and the tool returns an empty list (the agent says "no external data," not a wrong figure).
