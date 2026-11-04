# Demo accounts and scenario guide (synthetic; no secrets)

Accounts are created by `scripts/seed_v2.py --apply` (admin-created, `@example.com`, temporary passwords go to the git-ignored `.seed-credentials.local`, never printed or committed). Status: **not yet provisioned** (nothing deployed from this branch).

| Account | Role | Organization | Language | Scenario |
|---|---|---|---|---|
| ana.demo@example.com | producer | Andean Coffee Cooperative (Colombia) | es | Drought; playback correction; guidance without action; recurrence with Mateo |
| mateo.demo@example.com | producer | Andean | es | Water-management experience (named, shared conversation) |
| elena.demo@example.com | producer | Andean | en | Climate search-only question; pending soil case |
| lucia.demo@example.com | producer | Copán Coffee Association (Honduras) | es | Drought; recurrence |
| diego.demo@example.com | producer | Copán | en | Price decline; action without outcome; stopped conversation |
| rosa.demo@example.com | producer | Copán | es | FTUSA-only cases (reviewed, never published) |
| awa.demo@example.com | producer | Nawa Cocoa Cooperative (Côte d'Ivoire) | fr | Labor shortage; out-of-scope request |
| koffi.demo@example.com | producer | Nawa | fr | PII mention; summary revision awaiting re-confirmation |
| mariam.demo@example.com | producer | Nawa | en | Soil / evidence search; withdrawn case |
| reviewer1.demo@example.com, reviewer2.demo@example.com | reviewer | n/a | n/a | Review queue, correction requests |

Commands (sandbox only): `python scripts/validate_v2_dataset.py` (offline), `AWS_PROFILE=breaking-barriers-ny python scripts/seed_v2.py --stack FtusaExchange-sandbox` (dry run), add `--apply` to write (conditional puts only; reruns never overwrite demo activity), `--reset-sandbox --apply` to remove only the seeded items.
Illustrative findings and fictional outcomes are labelled in the data (`illustrative: true`, "(fictional)").
Deterministic dataset facts: 3 organizations, 9 producers, 2 reviewers, 24 conversations, 12 issues, 12 published peer cases, 12 Premium projects, 6 corrections (pending x3, accepted-awaiting-source-update, applied, rejected), 6 evidence rows (including one stale/conflicting pair; external and FTUSA-curated are separate fields).
