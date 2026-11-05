# Component 3 — Data Tools for Structured Data

**Status:** v2.0. Component-level requirements. The system overview and cross-component decisions live in `../REQUIREMENTS.md`; this document is authoritative for Component 3 only.

**Changes from v1.0**

| # | Change | Why |
|---|---|---|
| 1 | Tools take **no producer ID argument**. The caller's `account_sk` comes from session context. | Vision: "scope is enforced in the tool, not the prompt"; 0 cross-producer leaks is a success metric. A tool parameter is filled by the model. |
| 2 | New **prepare stage** (offline, tested) before the load stage. | Source data needs merging, normalization, tagging, PII flagging and survey aggregation before it can be loaded. |
| 3 | Projects come from **both** project files, merged 1:1. | Only `pprojects-full…csv` has the English text, `reason` and `primary_goal`. Only `Premium_Projects_Environmental.csv` has dates and status. |
| 4 | `project_id` = deterministic hash **plus a disambiguator**. | 36 project names repeat, some within the same account. |
| 5 | Projects carry the **11 challenge tags**. GSIs are keyed on `primary_tag`, not `category`. | `category` is always "Environmental". Vision matches peers "on challenge tag, crop, and entity type". |
| 6 | The vector embeds **name + description + reason**. Metadata adds crop, entity type and tag. | `reason` states the need, which is what a producer describes. |
| 7 | Survey is aggregated **per year**, with **small-n suppression**, and includes **multi-choice** shares. Raw rows are **not** in DynamoDB. | Several producers have several years. Harvest-change reasons are the most useful survey signal. The agent never needs row-level answers. |
| 8 | Added **S3 + Athena** copy of all tables. | Journey 3 join demo; the Technical doc names Athena/Glue as the Redshift stand-in. |
| 9 | PII **flagging** at prepare time. Flagged projects are excluded from peer results until reviewed. | Some project names contain people's names (e.g. "SCPP <person name>"). Peer results show other organizations' text. |
| 10 | Coverage numbers corrected. | 22 of 146 producers have single-choice survey data, not 14. |

---

## Architecture (at a glance)

```
 COMPONENT 3 — DATA TOOLS
══════════════════════════════════════════════════════════════════════════════

 FTUSA export (CSV / xlsm)
        │
        ▼
 ┌────────────────────────────────────────────────────────────────────┐
 │ STAGE A — PREPARE  (ftusa_data, offline, deterministic, tested)    │
 │ merge projects · synthesize IDs · normalize · 11-tag labels         │
 │ · PII flags · survey aggregation · data dictionary → catalog.yaml   │
 └──────────────────────────────┬─────────────────────────────────────┘
                                │ out/tables/*  (validated, Pydantic)
                                ▼
 ┌────────────────────────────────────────────────────────────────────┐
 │ STAGE B — LOAD  (idempotent upsert + stale sweep)                  │
 └───────┬──────────────────────────┬──────────────────────────┬──────┘
         ▼                          ▼                          ▼
 ┌────────────────┐      ┌──────────────────────┐     ┌───────────────────┐
 │ DynamoDB       │      │ S3 Vectors           │     │ S3 + Glue/Athena  │
 │ producers      │      │ peer-projects        │     │ all prepared      │
 │ projects       │      │ (Titan v2, metadata  │     │ tables + raw      │
 │ survey_summ.   │      │  filters)            │     │ survey (join demo,│
 │ PK account_sk  │      │                      │     │  analytics only)  │
 └───────▲────────┘      └──────────▲───────────┘     └───────────────────┘
         │      hot path            │
 ┌───────┴──────────────────────────┴────────┐
 │ DATA-ACCESS LAYER (only code touching     │
 │ the stores; bounded; shapes + citations)  │
 └───────────────────▲───────────────────────┘
                     │
 ┌───────────────────┴───────────────────────┐    ┌────────────────────────┐
 │ TOOLS  get_producer_record ·              │◄───│ SESSION CONTEXT        │
 │ find_similar_projects · query ·           │    │ account_sk (from C1 /  │
 │ describe_dataset                          │    │ Lambda, never model)   │
 └───────────────────▲───────────────────────┘    └────────────────────────┘
                     │ tool calls
 ┌───────────────────┴───────────────────────┐    ┌────────────────────────┐
 │ STRANDS AGENT (Bedrock Claude)            │◄───│ DATA CATALOG           │
 └───────────────────────────────────────────┘    │ condensed → prompt;    │
                                                  │ full → describe_dataset│
                                                  └────────────────────────┘
```

Three decouplings make this scale:

- **Catalog ⟂ data.** The agent learns what exists from the manifest. Adding a dataset needs no agent code change.
- **Access layer ⟂ backend.** Tools see one interface. Demo and production use the same tables and indexes; only the volume differs.
- **Prepare ⟂ load.** Data cleaning is offline and testable. The loader only writes.

---

## 1. Purpose

Give the agent grounded, attributable, **scope-safe** access to the structured datasets through four Strands tools:

- producer accounts
- Premium-funded projects
- household-survey aggregates

A data catalog tells the agent what each dataset can and cannot answer. Sample and production data share one model. Scaling is a data-load change, not a redesign.

## 2. Scope

**In scope:**
- prepare stage
- data catalog
- data-access layer
- DynamoDB model (3 tables)
- S3 Vectors `peer-projects` index
- S3/Athena copy
- the four tools
- the load script
- scope negative tests

**Out of scope:**
- agent orchestration (C2)
- standards RAG (C4; shares the S3 Vectors bucket)
- climate/CHIRPS (C5)
- conversation save, PII flagging of *producer input*, KB promotion (C6)
- UI (C1)

---

## 3. Source data (sample export)

| File | Grain | Rows | Used for |
|---|---|---|---|
| `Producer_Accounts.csv` | producer | 146 | producers |
| `pprojects-full-environmental-with-acct-detail.csv` | project | 349 | project text (EN), reason, goal, region, sub-category |
| `Premium_Projects_Environmental.csv` | project | 349 | original-language description, start/end date, status |
| `Survey_Response_Questions_Single_Choice.csv` | response | 33,153 | survey aggregates |
| `Survey_Response_Questions_Multiple_Choice.csv` | response × choice | 55,427 | survey aggregates (choice shares) |
| `Survey_Response_Header.csv` | response | 16,857 | quality filter (completion, active, deleted) |
| `Household_Survey_Header.csv` | survey | 83 | survey name → crop, type (HL/SPO), year |

Facts about this sample that shape the design:

- **Projects**
  - All 349 projects have `category = Environmental`.
  - 117 projects have sub-category "Sustainability efforts" and 60 have none.
- **Survey coverage**
  - 192 accounts have survey responses.
  - Only 22 of those accounts are in `Producer_Accounts`.
- **Entity type**
  - 52 producers have no `structure`.
- **Countries**
  - Country names need normalizing (e.g. "Côte d’Ivoire" / "Cote d'Ivoire").
  - Some project countries look like dropdown defaults (Åland Islands, Afghanistan, Andorra).

---

## 4. Stage A — Prepare (`ftusa_data`)

A deterministic, offline Python pipeline. Already implemented; see `ftusa_data/` and `DATA_DICTIONARY.md`.

- **PREP-1 (Producers).**
  - Normalize country.
  - Map `structure` to `entity_type`: 1st/2nd Grade → `cooperative` (with `org_level`); Estate / Multi-Estate → `estate`; Independent Smallholder → `smallholder`; Factory → `processing_operation`; missing → `unknown`. Never guess the missing ones.
  - Split `product_category` into `crops` and set `primary_crop`.
  - Set `region` to the most frequent region in the producer's projects.
  - Set `primary_language` from the country.
  - Generate `org_name_fictional`, marked "(fictional)".
  - Set `applicable_standard`: APS for farms, FPS for `processing_operation`.
- **PREP-2 (Project merge).**
  - Match the two project files on (`account_sk`, name, region, sub-category).
  - Where a key repeats, pair identical descriptions first, then pair the rest in file order and set `merge_ambiguous`.
  - Fail the run unless the result is exactly 1:1.
- **PREP-3 (Project ID).** `project_id = "PRJ-" + sha1(account_sk | name | region | n-th occurrence)[:10]`. The ID is stable across reloads of the same source.
- **PREP-4 (Challenge tags).**
  - Assign 1–3 of the 11 tags, primary first, in three layers:
    1. sub-category rule;
    2. keyword rules on name + description + reason + goal;
    3. optionally, Claude on Bedrock for rows the rules could not tag confidently.
  - Every row records `tag_source` and `tag_reason`.
  - Mappings awaiting FTUSA confirmation are flagged `tag_pending_confirmation`.
- **PREP-5 (PII flags).** Run regex plus Amazon Comprehend `DetectPiiEntities` over project text. Set `pii_flag` and `pii_types`. **Never redact.**
- **PREP-6 (Peer eligibility).** `is_peer_eligible` requires all of:
  - status is completed or in_progress;
  - description ≥ 40 chars;
  - at least one tag;
  - not `pii_flag`.
- **PREP-7 (Survey aggregation).**
  - **Quality filter:** drop responses whose header shows completion < 80 %, inactive or deleted.
  - **Grain:** aggregate per (`account_sk`, `survey_year`).
  - **Metrics:**
    - Yes/No and categorical metrics are reported as `pct` plus `n`.
    - Multi-choice questions get choice shares: harvest-change reasons, borrow sources, income sources, FT benefits.
  - **Suppression:** any `pct` or share with `n < 10` is blank.
  - **Citation ID:** each summary gets a `summary_id`.
- **PREP-8 (Outputs).**
  - Validated tables in `out/tables/`.
  - `DATA_DICTIONARY.md`.
  - `report.json` with counts and warnings.
  - Review files: tag-labeling sample, scenario candidates, scope test pairs.

---

## 5. Data catalog

- **CAT-1 (Manifest).** `catalog.yaml` describes every dataset. Fields come from `DATA_DICTIONARY.md`; `answers` and `cannot_answer` are written by hand. See Appendix A.
- **CAT-2 (Prompt summary).** A condensed summary goes into the system prompt (C2): name, grain, answers, cannot_answer, coverage.
- **CAT-3 (On-demand schema).** `describe_dataset(name)` returns the full entry.
- **CAT-4 (Stable contract).** A new dataset = a catalog entry + an access-layer adapter. No agent code changes.
- **CAT-5 (Describes, doesn't contain).** The catalog holds no data rows.
- **CAT-6 (Coverage and limits are explicit).** Each entry states:
  - coverage (e.g. "survey: 22 of 146 producers");
  - what it **cannot** answer (e.g. "no market, labor or education projects: Premium data is Environmental only").

  This keeps the agent from inventing data it doesn't have.

---

## 6. Scope enforcement

- **SCOPE-1 (Session context).** C1/Lambda resolves the session's `account_sk` and passes it in the AgentCore invocation payload. The agent entrypoint puts it into Strands invocation state (`ToolContext`). As a fallback, it binds tools per session with a closure.
- **SCOPE-2 (No ID parameters).** No tool accepts `account_sk`, producer ID, location or region as a model-supplied argument. Own-record tools read only the session `account_sk`.
- **SCOPE-3 (Cross-producer = public project fields only).** `find_similar_projects` and `query` return only org-level project fields:
  - fictional org name, country, region, crop, entity type;
  - project name, description, reason, tags, status, year.

  They never return another producer's survey summary, certification status or `account_sk`. Peers are referenced by `project_id` and display name.
- **SCOPE-4 (Caller exclusion).** Cross-producer tools exclude the caller's projects in the store query **and** re-check in code before returning.
- **SCOPE-5 (Negative tests).** For every pair in `review/scope_test_pairs.csv` (same crop and region), with session = A:
  - no tool output contains B's own-record data;
  - no peer result has `account_sk` = A;
  - injecting B's ID into tool arguments or the prompt changes nothing.

---

## 7. Data-access layer

- **DA-1 (Single choke point).** The `DataAccess` interface is the only code that touches the stores. There are two implementations behind it:
  - `DynamoS3Backend` (demo and production);
  - `InMemoryBackend`, which reads `out/tables/`, for unit tests and local agent runs without AWS.
- **DA-2 (Bounded).** Every method requires a `limit` / `top_k`, capped server-side (`MAX_LIMIT = 20`). There are no scans.
- **DA-3 (Shaped + cited).** Methods return shaped dicts. Each fact carries a citation `{source_type, source_id, label}`, where `source_type` is one of `producer_record | peer_project | survey_summary`.
- **DA-4 (Observability).** Every call is logged with its arguments (minus nothing — there are no secrets), result size, latency and returned citation IDs.

---

## 8. Data model

### 8.1 DynamoDB — `producers`

- **Key:** PK `account_sk`.
- **Attributes:** `display_id`, `org_name_fictional`, `entity_type`, `org_level`, `crops`, `primary_crop`, `country`, `country_iso3`, `region`, `region_id`, `primary_language`, `certification_status`, `certification_scope`, `applicable_standard`, `supply_chain_roles`, `project_count`, `has_survey`, `survey_years`.
- **Precomputed:** `survey_latest`, a copy of the most recent `survey_summaries` item (§8.3). Absent when `has_survey = false`.
- **GSI `by_country_crop`:** PK `country`, SK `primary_crop#account_sk`. Used by `query(dataset="producers")`.

### 8.2 DynamoDB — `projects`

- **Key:** PK `account_sk`, SK `project_id`.
- **Attributes:** `name`, `description`, `reason`, `primary_goal`, `description_original`, `subcategory`, `challenge_tags` (list), `primary_tag`, `status`, `start_date`, `end_date`, `start_year`, `country`, `region`, `region_id`, `tag_source`, `tag_reason`, `pii_flag`, `is_peer_eligible`.
- **Denormalized for peers:** `crop`, `entity_type` and `org_name_fictional` of the owner.
- **GSI `peers_by_country_tag`** (sparse; only items with `is_peer_eligible = true` carry `gsi_country`):
  - PK `gsi_country`
  - SK `primary_tag#start_year#project_id`
  - Serves "water projects in Peru".
- **GSI `peers_by_tag`** (sparse; same rule):
  - PK `gsi_primary_tag`
  - SK `crop#country#project_id`
  - Serves "water projects for coffee anywhere".

### 8.3 DynamoDB — `survey_summaries`

- **Key:** PK `account_sk`, SK `survey_year`.
- **Attributes:** `summary_id`, `n_responses`, `survey_types`, `survey_crops`, and every `pct_*` / `n_*` metric and `top_*` choice share from PREP-7.
- **Behavior:** Read only for the session producer, never cross-producer. The latest year is also copied onto the producer item, so the hot path stays at 2 calls.

### 8.4 S3 Vectors — `peer-projects` index

- **Vectors:**
  - One vector per **peer-eligible** project; key = `project_id`.
  - Model: Titan Text Embeddings V2, 1024 dims, cosine. The model is multilingual, so Spanish queries match English text.
  - Embedded text: `name + description + reason`.
- **Filterable metadata:** `account_sk`, `country`, `crop`, `entity_type`, `primary_tag`, `status`, `start_year`.
- **Non-filterable metadata:** `name`, `org_name_fictional`, `region`.
- **Query:**
  1. Embed the query.
  2. Filter `account_sk $ne caller`, plus optional `crop` / `entity_type` / `primary_tag`.
  3. Request `top_k × 3`.
  4. Re-check caller exclusion in code.
  5. Hydrate from DynamoDB `projects` via `BatchGetItem` and truncate to `top_k`.
- **Bucket:** the same S3 Vectors bucket holds the C4 `standards` index and the C6 `generic_kb` index.

### 8.5 S3 + Glue/Athena (not on the hot path)

- **What is stored:** all prepared tables, plus the raw single- and multi-choice survey files, as Parquet (CSV fallback) under `s3://<bucket>/c3/tables/<table>/`, with Glue tables over them.
- **Uses:**
  - the Journey 3 join demo (C6 write-back records ⋈ projects ⋈ survey ⋈ certifications);
  - recomputing aggregates;
  - analytics.
- **SQL:** Redshift-compatible.
- **Not exposed to the agent.**

---

## 9. Tools

These are plain Python functions with Strands `@tool`. All of them go through the data-access layer. The session `account_sk` is read from tool context (SCOPE-1).

### 9.1 `get_producer_record()`

- **Purpose:** the session producer's own profile, projects and latest survey summary.
- **Input:** none (SCOPE-2). Optional `include_all_survey_years: bool = False`.
- **Implementation:** `GetItem(producers)` + `Query(projects, PK = session account_sk, Limit 50)`. Add `Query(survey_summaries)` only if all years were requested.
- **Output:**
  ```json
  {
    "profile": {"display_id", "org_name_fictional", "entity_type", "primary_crop", "crops",
                "country", "region", "primary_language", "applicable_standard",
                "citation": {"source_type": "producer_record", "source_id": "<account_sk>", "label": "..."}},
    "projects": [{"project_id", "name", "description", "reason", "challenge_tags", "status",
                  "start_date", "end_date", "citation": {...}}],
    "survey": null | {"survey_year", "n_responses", "metrics": {...}, "top_choices": {...},
                      "citation": {"source_type": "survey_summary", "source_id": "<summary_id>", ...}},
    "coverage_notes": ["no survey data for this producer"]
  }
  ```
- **Edge cases:**
  - 124 of 146 producers have no survey. The tool still returns a complete answer with `survey: null` and a coverage note.
  - An unknown or absent session ID returns a typed `{"error": "no_session_producer"}`.

### 9.2 `find_similar_projects(challenge, tags=None, same_crop=True, same_entity_type=False, top_k=5)`

- **Purpose:** peer examples, i.e. what comparable producers did about a similar challenge.
- **Input:**
  - `challenge`: natural-language text, in any language.
  - `tags`: optional subset of the 11 tags.
  - Crop and entity type come from the session producer's record, not from the model.
  - `top_k` ≤ 10.
- **Implementation:** S3 Vectors query (§8.4). If fewer than 2 results survive with `same_crop`, retry once without it and mark `relaxed: ["crop"]`.
- **Output:**
  ```json
  {"results": [{"project_id", "org_name_fictional", "country", "region", "crop", "entity_type",
                "name", "description", "reason", "challenge_tags", "status", "start_year",
                "similarity", "citation": {"source_type": "peer_project", "source_id": "<project_id>", ...}}],
   "relaxed": [], "coverage_notes": ["Premium project data covers Environmental projects only"]}
  ```
- **Constraints:**
  - Never returns caller projects (SCOPE-4).
  - Never returns PII-flagged or ineligible projects. They are not in the index.

### 9.3 `query(dataset, filters, limit)`

- **Purpose:** bounded cross-producer lookups, e.g. "water projects in Peru" or "coffee cooperatives in Colombia".
- **Input:**
  - `dataset` ∈ {`projects`, `producers`}.
  - `filters` from a whitelist:
    - projects: `country`, `primary_tag`, `crop`, `status`, `start_year_from`;
    - producers: `country`, `primary_crop`, `entity_type`.
  - `limit` is required, 1–20.
- **Implementation:**
  - projects → `peers_by_country_tag` when `country` is given, else `peers_by_tag`;
  - producers → `by_country_crop`;
  - any remaining filters are applied as a `FilterExpression`.
  - A call with no indexed filter (no `country` or `primary_tag`) is rejected.
- **Output:**
  - Rows with public fields only (SCOPE-3), each with a citation.
  - Producer rows return `display_id`, `org_name_fictional`, `country`, `region`, `primary_crop`, `entity_type` and `project_count`, and nothing else.
- **Rejections:** a missing `limit`, `limit > 20`, an unknown filter key or an unknown tag returns a typed error listing the allowed values.

### 9.4 `describe_dataset(name)`

Returns the catalog entry: grain, description, answers, cannot_answer, coverage, fields. No store call. An unknown name returns a typed error with the available names.

---

## 10. Stage B — Load script

- **LOAD-1 (Input).** Read Stage A outputs (`out/tables/*`), never raw files.
- **LOAD-2 (Validate).** Pydantic per row. Rejects go to `load_manifest.json`, which records rows in / loaded / rejected per table.
- **LOAD-3 (DynamoDB).** `BatchWriteItem` upserts into `producers`, `projects` and `survey_summaries`. Copy `survey_latest` and the denormalized peer fields at write time. Set the sparse GSI attributes only for peer-eligible projects.
- **LOAD-4 (Vectors).** Embed the peer-eligible projects with Titan V2 (batched). `PutVectors` into `peer-projects`, key = `project_id`. Skip re-embedding when the text hash is unchanged (`text_sha1` stored in metadata).
- **LOAD-5 (S3/Athena).** Upload the tables as Parquet and (re)create the Glue tables.
- **LOAD-6 (Idempotent).**
  - IDs are deterministic and writes are upserts.
  - Each run stamps `load_id`. Items and vectors from a previous `load_id` that are absent from the new source are deleted (stale sweep).
  - Running twice yields identical stores.
- **LOAD-7 (Same code at scale).** A larger export changes only the input. Writes are batched and resumable by table.

---

## 11. Constraints & assumptions

- **CON-1 (Anonymized, not risk-free).** `account_sk` is already re-keyed, but free text can still contain names, so PII flagging stays (PREP-5). Scope enforcement is required regardless of anonymization (§6).
- **CON-2 (Survey coverage).** 22 of 146 producers have survey data. Survey is enrichment, never a dependency.
- **CON-3 (Join key).** `account_sk` everywhere.
- **CON-4 (Content limits).**
  - Projects are Environmental only.
  - Coffee-dominant: 180 of 349 projects.
  - Priority coverage, measured in producers: Colombia coffee 27, Peru coffee 18, Honduras coffee 12, Mexico coffee 4, Côte d'Ivoire cocoa 3, Colombia banana 2.
- **CON-5 (Fictional names).** Source accounts have no names. Peers are shown by `org_name_fictional`, which is allowed because peer projects are org-level and largely public.
- **CON-6 (Bedrock only).** Titan embeddings, optional LLM tagging and any model use go through Bedrock.
- **CON-7 (Sample = stand-in).** The same pipeline runs on the full export.

## 12. Non-functional requirements

- **NFR-1 (Scale).** Bounded queries, sparse GSIs, a vector index and no scans. More rows change no code.
- **NFR-2 (Hot-path latency).** `get_producer_record` = 1 GetItem + 1 Query. `find_similar_projects` = 1 embedding + 1 vector query + 1 BatchGetItem.
- **NFR-3 (Cost).** DynamoDB on-demand, S3 Vectors, Athena per query. No always-on compute.
- **NFR-4 (Observability).** DA-4. C2 surfaces the citation IDs.
- **NFR-5 (Local mode).** The `InMemoryBackend` runs every tool test without AWS.

## 13. Acceptance criteria

- **ACC-1.** `get_producer_record` returns a complete cited answer:
  - for a producer with survey data;
  - for one without (`survey: null` plus a coverage note, no error).
- **ACC-2.** `find_similar_projects("bombeo solar de agua")`, run in a Colombian coffee session, returns ≤ `top_k` real projects. None belongs to the caller, none is PII-flagged, and each has a citation.
- **ACC-3.** `query("projects", {country: "Peru", primary_tag: "water"}, limit=5)` returns ≤ 5 matching rows. These calls are rejected with typed errors:
  - no `limit`;
  - `limit=100`;
  - filter `category`.
- **ACC-4.** `describe_dataset("projects")` returns fields with meanings, plus coverage and `cannot_answer`.
- **ACC-5 (Scope).** Every pair in `scope_test_pairs.csv` passes SCOPE-5. There are 0 leaks.
- **ACC-6 (Load).** The load writes 3 tables, the vector index and the Athena tables. A second run is identical. Removing a project from the source removes it from every store.
- **ACC-7 (Join demo).** One Athena query joins a C6 conversation record to the producer's projects, survey summary and certification on `account_sk`.
- **ACC-8 (Scale).** Loading a larger export changes no tool, catalog or access-layer code.

## 14. Open items

- **OPEN-1.** Confirm the tag mappings for Waste, Pest Management, Crop Diversification and HR/admin (90 projects pending).
- **OPEN-2.** 52 producers have `entity_type = unknown`. Can FTUSA supply the structure?
- **OPEN-3.** 170 survey accounts are not in `Producer_Accounts`. Load their summaries (for future producers) or drop them?
- **OPEN-4.** Should peers show `entity_type` and `region` for other producers, or country only?
- **OPEN-5.** Run the Bedrock LLM tagging layer on the 43 untagged projects, then human-label the 40-project sample (target ≥ 80 % primary-tag agreement).

*(v1.0 OPEN-3, OPEN-5 and OPEN-6 are resolved by SCOPE-1, PREP-7/§8.3 and PREP-3 respectively.)*

---

## Appendix A — `catalog.yaml` (draft)

```yaml
datasets:
  - name: producers
    grain: one item per producer (account_sk)
    description: Fair Trade certified organizations - profile only.
    answers: what the session producer grows, where, what entity type, which standard applies
    cannot_answer: names of people; certification audit details (out of scope for the agent)
    coverage: 146 producers; entity_type unknown for 52
    fields:
      display_id: short alias for display
      org_name_fictional: generated name (source has no names)
      entity_type: cooperative | smallholder | estate | processing_operation | unknown
      primary_crop / crops: coffee, cocoa, banana, tea, ...
      country / region: region = most frequent region of the producer's projects
      applicable_standard: APS (farms) or FPS (factories)
      has_survey: whether survey_summaries exist for this producer

  - name: projects
    grain: one item per Premium-funded project
    description: Environmental projects funded by the Fair Trade Premium, with the need they responded to.
    answers: what the session producer has already done; what comparable producers did (peer examples)
    cannot_answer: market, labor, education or health projects (Environmental only); budgets; beneficiaries
    coverage: 349 projects, 146 producers; coffee 180; Colombia 106, Peru 37, Mexico 37, Honduras 19, Côte d'Ivoire 8
    fields:
      project_id: citation ID
      name / description: what was done (English translation)
      reason: the need or challenge the project responds to
      challenge_tags / primary_tag: 1-3 of the 11 challenge tags
      status: completed | in_progress | in_planning
      start_date / end_date: dates (blank if unknown)
      country / region: location

  - name: survey_summaries
    grain: one item per producer per survey year (aggregated, never row-level)
    description: Household survey aggregates - practices, water access, harvest change and its reasons.
    answers: share of members reporting harvest decrease and why; conservation practices; water access; borrowing
    cannot_answer: any individual household's answers; anything for producers without survey data
    coverage: 22 of 146 producers; years 2020-2026; any pct with n < 10 is blank
    fields:
      summary_id: citation ID
      n_responses: responses after quality filter
      pct_* / n_*: percentage and the number of valid answers behind it
      top_harvest_change_reasons: e.g. "Climate change (14%)|..."
      top_borrow_sources / top_income_sources / top_ft_benefits: choice shares
```
