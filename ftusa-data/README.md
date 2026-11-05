# FTUSA Producer Exchange Agent: data pipeline

Turns the FTUSA sample export into the tables the agent tools read.
Offline, pandas + openpyxl only, about 4 s end to end.

```bash
pip install pandas openpyxl pytest
python -m ftusa_data.run --raw /path/to/ftusa_files --out out
FTUSA_RAW=/path/to/ftusa_files pytest -q          # 11 checks
```

Raw files are found by suffix, so the random upload prefixes don't matter:
`*Producer_Accounts.csv`, `*pprojects-full-environmental-with-acct-detail.csv`,
`*Premium_Projects_Environmental.csv`, `*Survey_Response_Header.csv`, `*Household_Survey_Header.csv`,
`*Survey_Response_Questions_Single_Choice.csv`, `*Survey_Response_Questions_Multiple_Choice.csv`,
`*APS_*.xlsm`, `*FPS_*.xlsm`.

## Outputs, and which tool reads them

| Output | Tool | Notes |
|---|---|---|
| `tables/producers` | session context, producer-record | key `account_sk`; entity type from `structure_txt`; region = most frequent project region; fictional org name |
| `tables/premium_projects` | producer-record (own), peer-example (others) | two source files merged 1:1; 11-tag labels with `tag_source` + `tag_reason`; `pii_flag` (text never redacted); `is_peer_eligible` |
| `tables/survey_summary` | producer-record | one row per account × year; % metrics with their n; blank when n < 10 |
| `tables/survey_choice_shares` | producer-record (citable detail) | multi-choice shares (harvest-change reasons, borrow sources, income sources, FT benefits) |
| `tables/certifications` | join demo only | status is out of scope for the agent (Journey 4) |
| `tables/regions` | regional-context | approximate centroids for priority countries (verify) |
| `standards/standard_clauses.jsonl` | standards grounding (`c4`, `get_standards_clause`; see docs/COMPONENT_4_STANDARDS.md) | APS 322 + FPS 353 criteria; module/objective attached; ES/FR text for APS; `_v` amendment variants flagged |
| `review/tag_labeling_sample.csv` | evaluation | fill `human_tags`, then `python -m ftusa_data.run --evaluate-tags review/tag_labeling_sample.csv` |
| `review/scenario_candidates.csv` | demo design | priority producers ranked by data richness |
| `review/scope_test_pairs.csv` | negative scope tests | same crop + region pairs (hardest leakage cases) |
| `report.json`, `DATA_DICTIONARY.md` | handoff | counts, warnings, every column described |

## Optional AWS layers

```bash
python -m ftusa_data.run --raw ... --out out \
  --bedrock-model-id <Claude model ID or inference profile> --aws-region us-east-1 \
  --comprehend
```

* `--bedrock-model-id`: Claude re-tags projects the rules could not tag confidently (`tag_source` none/keyword).
  Add `--llm-all` to re-tag every project. Results are cached in `out/cache/llm_tags.jsonl`.
* `--comprehend`: adds Amazon Comprehend `DetectPiiEntities`. The offline regex finds no PII in this extract,
  but project names such as "SCPP <person name>" contain people's names, and only Comprehend can catch those.

Neither layer has been run here (no AWS credentials in the build environment).

## Decisions to confirm with FTUSA (all in `config.py`)

* Sub-category → tag for Waste, Pest Management, Crop Diversification and HR/admin
  (`tag_pending_confirmation=True`, 90 projects).
* 52 accounts have no `structure_txt` → `entity_type=unknown`.
* FPS here is the Factory Production Standard and grounds `processing_operation` only; farms use APS.
* Survey quality filter: completion ≥ 80 %, active, not deleted. About half the responses have no header row; those are kept.
* Only 22 of the 192 survey accounts appear in Producer_Accounts, so most producers have no survey summary (`has_survey`).

---

# Component 3: data tools (`c3/`)

Implements `docs/COMPONENT_3_DATA.md` v2.0. It runs on the output of the pipeline above.

```bash
python -m ftusa_data.run --raw <ftusa files> --out out    # Stage A
python -m c3.smoke --backend memory                        # call all four tools locally
python -m c3.load --tables out/tables --dry-run            # Stage B without AWS: build + validate payloads
pytest -q                                                  # Python: 59 pass, 13 skip without FTUSA_RAW / boto3
```

| File | Role | Tested here |
|---|---|---|
| `catalog.yaml`, `catalog.py` | data catalog; coverage filled from `catalog_stats.json`; `prompt_summary()` for the system prompt | yes |
| `items.py` | Stage A tables → DynamoDB items + vector records (Pydantic-validated; sparse GSI attributes) | yes |
| `access.py` | **DataAccess**: bounds, scope, public-field whitelists, citations, call log | yes |
| `store_base.py` | backend interface (fetch-only) | yes |
| `store_memory.py` | in-memory backend; local TF-IDF embedder with a small ES/FR→EN term map | yes |
| `store_aws.py` | DynamoDB + S3 Vectors + Titan backend (boto3) | **no** (no boto3/AWS in build env) |
| `tools.py` | agent-facing plain functions `get_my_history(producer)`, `get_peer_examples(producer, topic)` (names match main's agent tools) + internal `impl_*` | yes |
| `load.py` | Stage B: create tables/index, upsert, embed, stale sweep, S3 + Athena; `--dry-run` | dry-run yes, AWS **no** |
| `smoke.py` | one call per tool against `memory` or `aws` | memory yes |

## Serving: the API Lambda reads the data

C3 and C4 are served by the API Lambda, not by agent tools: `python export_lambda.py` writes JSON bundles to
`backend/src/data/ftusa/`, read by `backend/src/ftusaRecords.ts` (producer records) and
`backend/src/standards.ts` (standards clauses). Scope is decided in backend code from the caller's server-side
record. The datasets are described in the repository's `catalog.yaml`. Details, wiring and the list of missing
data: [docs/LAMBDA_DATA.md](docs/LAMBDA_DATA.md).

The Python functions named after the agent's tools (`c3.tools.get_my_history`, `get_peer_examples`,
`c4.tools.get_standards_clause`) stay as the reference implementation and are covered by
`tests/test_agent_contract.py`; they are not the integration path.

## Before the first AWS run

1. `python -m c3.load ... --create`, then `python -m c3.smoke --backend aws`.
2. Check the S3 Vectors call shapes (`create_index`, `put_vectors`, `query_vectors` with a `$ne` filter, `list_vectors`)
   against your boto3 version. Caller exclusion is re-checked in code either way.
3. Confirm Titan Text Embeddings V2 is enabled in the region (1024 dims, normalized).

## Data issues found while building this

* 4 source projects are test/placeholder rows (lorem ipsum, "Test Project 7", dropdown-default countries).
  They are now `is_test_record` and excluded from peers.
* 1 producer had no product category; its crop is taken from `account_category` (Coffee).
* Peer text can still contain **real organization names** (e.g. a packhouse name in a description) next to the
  fictional org name. Comprehend (`--comprehend`) or a reviewer should check peer-eligible text before the demo.
