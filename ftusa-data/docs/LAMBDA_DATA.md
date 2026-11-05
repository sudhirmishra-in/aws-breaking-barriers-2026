# C3 + C4 served by the API Lambda

The API Lambda reads FTUSA producer records (Component 3) and standards clauses (Component 4); the agent never
reads them. Scope (which producer, which standard, which amendment variants) is decided in backend code from the
caller's server-side identity and record, never from the request body or the model. This follows the
application's design rule "access is decided in code, not by the model".

```
ftusa-data/out/  ──  python export_lambda.py  ──▶  backend/src/data/ftusa/*.json  (committed, deterministic)
                                                          │  import (bundled into the Lambda by esbuild)
                                                          ▼
                       backend/src/ftusaRecords.ts (C3)    backend/src/standards.ts (C4)
                                                          │
                       reviewer related data, history     standards evidence for a topic
```

## Bundles (`backend/src/data/ftusa/`)

| File | Dataset (catalog.yaml) | Rows | Size |
|---|---|---|---|
| `ftusa_producers.json` | `producer_accounts` | 146 | 65 KB |
| `ftusa_projects.json` | `premium_projects` | 349 | 325 KB |
| `ftusa_surveys.json` | `survey_summaries` (aggregates only) | 33 | 37 KB |
| `standard_clauses.json` | `standard_clauses` | 675 (APS 322, FPS 353) | 1.9 MB |
| `ftusa_producer_map.json` | app `producerId` → `accountSk` | empty | hand-edited, never overwritten |
| `manifest.json` | counts, `dataVersion`, origin label per bundle | | |

Every bundle carries `dataVersion` (content hash), `source`, `origin` and `curationStatus`. Re-run
`python export_lambda.py` after any pipeline change; `tests/test_export_lambda.py` fails if the committed bundles
are stale.

## Backend modules (new files only; no existing backend file is changed)

**`ftusaRecords.ts` (C3)**: same output shapes as `relatedData.ts`, so either source fits the reviewer screen.
- `ftusaAccountFor(producerId)`: server-side resolution through `ftusa_producer_map.json`, or an FTUSA display
  id (`PRD-…`) used as a producerId. An `accountSk` is never accepted as input and never returned.
- `ftusaRelatedFor(producerId)`: `relatedFor` shape (premium projects, surveys, certification), with citations.
  Returns `undefined` for a producer with no FTUSA account, so callers keep the team dataset.
- `ftusaProducer(producerId)`: `teamProducer` shape.
- `ftusaHistory(producerId)`: dated, cited history lines; "Outcome not reported" is the only outcome stated.

**`standards.ts` (C4)**: a retriever port, scope re-applied after retrieval, content only from the validated
rows, and a limitation instead of an invented clause.
- `standardsFor(scope, topic, language, limit, retriever?)` → `{kind: "standards", topic, standard, status:
  "ok" | "no_match" | "unavailable", items, limitation, dataVersion}`.
  `scope = {entityType, crop}` must come from the caller's record and profile.
- Items use the evidence shape: `evidenceId, kind: "standard_clause", title, finding, intent, textLanguage,
  geography, period, tag, source, origin: "ftusa_authored", curationStatus: "ftusa_curated", illustrative,
  taxonomy, standards: [clauseId], citation{label, clauseId, dataVersion, contentHash}`.
- `LocalStandardsRetriever`: BM25 over EN/ES/FR text with an ES/FR→EN glossary; ranks identically to the Python
  retriever (`ftusa-data/c4`), checked by tests. A managed retriever can replace it behind `StandardsRetriever`;
  it may only nominate clause ids.
- `knownClauseIds(ids)`: validates reviewer-entered `standards` lists so an invented id never reaches a producer.

## Wiring (not done on this branch: it changes shared backend and web files)

```ts
// service.ts, reviewRelated: FTUSA data when the producer is mapped, the team dataset otherwise
return ftusaRelatedFor(producerId) ?? relatedFor(producerId);

// an evidence step (e.g. after finalize): scope from the record and profile, topic from the confirmed summary
const standards = await standardsFor({ entityType: profile.entityType, crop: o.crop ?? profile.crop },
  `${o.summaryEn ?? ""} ${(o.challengeTags ?? []).join(" ")}`, o.language ?? "en");
```

Before the first line goes live, `web/src/views/Review.vue` must accept `null` for `amountUsd` and
`incomeChangePct` (it calls `amountUsd.toLocaleString()` today).

## Data that is missing

| Missing | Effect now | Needed from |
|---|---|---|
| Which app login maps to which FTUSA account (`ftusa_producer_map.json` is empty) | No producer gets FTUSA records yet | Team decision (one mapping for every component's demo accounts) |
| Premium amounts (`amountUsd`) | `null`; reviewer screen must handle it | FTUSA Premium expenditure data |
| Measured project outcomes | Always "Outcome not reported" | FTUSA |
| Income change (`incomeChangePct`) | `null` | A survey question on income |
| Challenge tags on survey answers (`topConcern`, `concerns`) | `null` / empty; `topChoices` holds the raw top answers | A survey codebook mapping answers to tags |
| Survey codebook (question wording, applicability) | Metric labels are provisional | FTUSA |
| Certification version and last audit date | `null` | Certification records |
| Facts to derive amendments other than cocoa / palm (Coffee GCP, US, PMT Adaptation, ...) | Those variants are never shown | Producer certification scope |
| Reviewed challenge tags on clauses | Tags come from keyword rules | A reviewer pass |
| Agreed origin label for the CSV data (`ftusa_team_csv` here; other branches and the architecture page use different labels) | Labels differ across branches | Team decision (one constant in `export_lambda.py`) |
