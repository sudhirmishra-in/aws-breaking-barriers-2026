# Component 4 — Standards RAG

Grounds answers in Fair Trade USA APS / FPS criteria. Implements main's agent tool
`get_standards_clause(topic: str) -> dict` (`agent/app/exchange/tools.py`), which today always returns
"unavailable".

## Interface (unchanged from main)

| | main today | C4 |
|---|---|---|
| Tool name | `get_standards_clause` | same |
| Model-supplied args | `topic: str` | same (no producer, standard or location argument) |
| Producer scope | closure over trusted `ProducerRef` in `build_tools(producer)` | same: `make_standards_tool(sa, producer, language)` |
| Result keys | `kind, topic, status, note` | same, plus `standard`, and `clauses` when `status == "ok"` |
| `status` | `"unavailable"` | `"ok"` / `"no_match"` / `"unavailable"` (empty topic or backend error) |

Each clause: `clause_id, standard, module, objective, requirement, intent` (≤600 chars),
`text_language, timeline, priority, challenge_tags, score, citation{source_type="standard_clause", source_id, label}`.

## Scope rules (from trusted context only)

- **Standard:** `entityType == "processing_operation"` → FPS, otherwise APS; each clause's `applies_to` must
  include the producer's entity type.
- **Amendment variants:** a `_v…` variant is returned only when one of its `show_for_amendments` applies, and a
  base clause is hidden when an active amendment is in its `hide_for_amendments`. Only
  "Cocoa or Palm producer" is derived (crop cocoa / cacao / palm). Coffee GCP, US, PMT Adaptation, etc. need
  facts we do not hold; pass them as `extra_amendments` once a source exists.
- **Language:** APS has ES/FR text and is returned in the conversation language when given; FPS is English only.
- Clause text describes requirements, never this producer's compliance (certification status stays out of scope).

## Backends

- **Offline (default):** BM25 over EN + ES/FR text with a small ES/FR → EN glossary. No AWS.
- **AWS:** Titan Text Embeddings v2 (1024-d, multilingual) + S3 Vectors index `standards` in the C3 bucket,
  metadata filter `standard`. Similarity floor 0.25. Applicability is re-checked against the local corpus.

```bash
python -m c4.load --clauses out/standards/standard_clauses.jsonl --dry-run --dump out/load_dryrun
python -m c4.load --clauses out/standards/standard_clauses.jsonl --region us-east-1 \
  --vector-bucket ftusa-c3-vectors --create          # NOT RUN in the build environment
```

## Wiring into main (not done on this branch)

```python
# agent/app/exchange/tools.py
from c4.tools import make_standards_tool, standards_access_from_env
_STANDARDS = standards_access_from_env()   # STANDARDS_CLAUSES, optional STANDARDS_VECTOR_BUCKET / _INDEX
...
get_standards_clause = make_standards_tool(_STANDARDS, producer)   # replaces the placeholder
```

The build script must also ship `ftusa-data/c4`, `ftusa-data/ftusa_data/config.py` and
`standard_clauses.jsonl`; the prompt line saying evidence tools always return unavailable must change.

## Tests

`pytest tests/test_c4.py` — main-shape and signature contract, APS/FPS split, applicability and amendment
invariants, citations resolve, ES topic → ES text, glossary reaches FPS, no_match / empty / backend-failure,
bounds, call log, loader dry run.

## Not covered

- Memory-agent interface (`retrieve_standards(reasoning, tags)` → `StandardsSource.search(tags)`): clauses
  carry `challenge_tags`, so an adapter is small, but tag strings there differ (`climate and weather`).
- Clause tags come from keyword rules, unreviewed.
