# Public nonprofit data: ingestion, validation, serving

Source: six CSV files supplied by the user, stated to be public and usable for the demo (not in this repository; 50 MB). Attribution is kept on every record:
`origin = public_source_data`, `curationStatus = not_curated`. **Public does not mean consented for conversation sharing and does not mean FTUSA-curated.**
No account-name or person column exists; no real names are invented; synthetic members are not survey respondents.

## Pipeline (`scripts/nonprofit_ingest.py`, deterministic, stdlib + optional pyarrow)
```
uv run --with pyarrow python scripts/nonprofit_ingest.py --src "<dir with the six CSVs>"
```
Writes `data/nonprofit-public/` (committed, 0.7 MB: manifest, exception report, accounts, projects, survey definitions, demo-account summaries), `backend/src/data/public_projects.json`
(API serving subset, no account keys) and `build/nonprofit/` (git-ignored: Parquet tables, project cards, **quarantine**). Raw files are never modified. The manifest holds each file's SHA-256, size,
rows, columns, `schemaVersion`, `pipelineVersion` and `ingestionVersion` (hash of pipeline + file hashes). Reruns on the same inputs produce identical outputs (tested).

## Verified counts (recomputed here; they match the profiling snapshot exactly)
| Check | Result |
|---|---|
| Rows (excl. header): accounts / projects / survey defs / response headers / single / multi | 146 / 349 / 83 / 16,857 / 33,153 / 55,427 |
| Keys unique (accounts, response headers); projects linked to an account | yes; 349 of 349 |
| Single-choice rows: consistent + account supplied | **3,297** (served) |
| Single-choice rows: account conflict with header / no header / consistent but account not supplied | **1,440** / 16,536 / 11,880 |
| Multi-choice option rows: consistent + account supplied | **20,074** (served) |
| Multi-choice option rows: account conflict / no header / consistent, account not supplied | **6,999** / 4,305 / 24,049 |
| Projects: country alias (reviewed, text differs only) / country conflict / epoch start date / geography needs review | 9 / 6 / 1 (row 176, 1970-01-01) / 3 (Andorra, Åland Islands, Afghanistan) |
| Project cards generated (usable rows) | 342 of 349 |
Conflicting rows are **never** attached to either account. Every excluded row is kept in `build/nonprofit/quarantine/*.csv.gz` with its reason; quarantine means "not served for account-scoped answers", not "invalid" (the exports may have different scopes).
Header coverage: 51 distinct accounts in response headers, of which 14 are in Producer Accounts.

## Rules implemented (and tested in `agent/tests/test_nonprofit_ingest.py`)
* Join answers to headers by `survey_response_sk` and require `account_sk`, `survey_sk` and `response_id` to agree. Neither table is preferred on disagreement.
* Multiple-choice rows collapse to distinct (response, question) selections before any count. Denominator = distinct responses with at least one selection for that question (a skipped and a not-asked response are indistinguishable in the source; stated in the output). An option count can never exceed its denominator.
* Country aliases use a reviewed map; raw values are kept (`Cote d'Ivoire`, `Côte d’Ivoire` -> `Côte d'Ivoire`). A real difference is `conflict`; unmapped is `unreviewed`. Suspicious dates are flagged, never rewritten (1970-01-01 is neither a real year nor silently null).
* Values stay distinct: `missing`, `zero_raw` (could be real, default or not-applicable), `refused`, `dont_know`, `not_applicable_label`, `value`. Coded structures (`1st Grade`, ...) are not translated into organization types.
* Survey summaries use **provisional** labels derived from column names (no codebook was supplied) with explicit denominators and survey years.
* **Project ids**: `PRJ-` + first 12 hex of SHA-256(account_sk | name | start | end). Description edits keep the id and change `contentHash`; a change to name, dates or account issues a new id (the old one disappears from the next manifest). Identical rows get `-2`, `-3` by source order. Row numbers (`Premium Projects Environmental.csv, row N`) are kept for traceability.
* Outcomes: the source has no measured-outcome field, so every project shows **"Outcome not reported"**; a `Completed` status is displayed as the recorded status only. No APS/FPS clause is produced anywhere.

## Demo mapping decision
The original fictional organizations stay as they are. The public records serve as **attributed external evidence** (not relabelled as those organizations): the API retrieves up to 3 project records for the caller's own country and crop (derived server-side from the caller's organization and record) and shows them as "EXTERNAL" public project records, never FTUSA-curated. Source-backed accounts selected after validation (0 conflicting rows each): `691F055F…` coffee Huila CO (5 projects, 574 responses; years 2021-2023), `A7F700B0…` coffee Cajamarca PE (3, 683; 2021, 2023, 2026), `FA9ADCCE…` cocoa Bas-Sassandra CI (2, 86; 2024), `CED2DEE8…` coffee La Paz HN (1, 314; 2023). Their survey summaries are in `data/nonprofit-public/demo_accounts.json`. **Not yet done:** explicit demonstration aliases (a fictional org linked to one of these source accounts with fictional members) and the "your organization's records contain earlier project or survey evidence" recall in the agent; both need a decision on which login maps to which source account.

## Serving paths
| Need | Path | Status |
|---|---|---|
| Narrative project retrieval | `projectEvidence.ts`: `ProjectRetriever` port. Local concept retriever (EN/ES/FR dictionary, hard country/crop filters) is live; a managed Bedrock Knowledge Base adapter (`KnowledgeBaseRetriever`) nominates ids only and the API returns content from the validated rows | local: implemented, tested. **KB: infrastructure code written and synth-tested; not deployed, not ingested, not verified** |
| Structured analytics | Parquet tables in `build/nonprofit/parquet` (projects, survey definitions, response headers, consistent single-choice, consistent multiple-choice selections) | written locally; **not uploaded to S3, no Glue/Athena tables yet** |
| Scoped profile/history, reviewer related data | accounts and demo summaries as JSON | **not loaded into the application store; reviewer related-data screen unchanged** |
| Raw household answers | never indexed in the KB or exposed to peers; only reviewed, scoped aggregates | enforced by design (not in cards) |

## Knowledge Base (not ready until ingested and smoke-tested)
Design: managed Bedrock KB, S3 Vectors store, Titan Text Embeddings v2 (multilingual, 1024 dims, available in us-west-2), one Markdown card per project (+ `.metadata.json` with country ISO, products, status, taxonomy, provenance; the internal account reference is metadata only), chunking `NONE` so a citation is exactly one project.
Enable: `cdk deploy -c enableKnowledgeBase=true`, then `python scripts/kb_sync.py --stack FtusaExchange-sandbox` (reports indexed/failed counts) and `python scripts/kb_smoke.py --stack FtusaExchange-sandbox` (EN/ES/FR relevance, scope filter, provenance metadata, ids resolving to bundled rows). Nothing may be described as "ready" before both succeed.

## Remaining source dependencies
APS/FPS clause text and versions; a survey codebook (question wording, applicability); external climate/market time series; Premium expenditure amounts; audit history; a decision on demonstration aliases for the source accounts.
