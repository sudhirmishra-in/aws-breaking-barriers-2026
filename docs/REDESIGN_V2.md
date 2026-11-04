# Producer Exchange V2 redesign: checklist, contracts, decisions, status

Branch `redesign-v2`. **Status: partially implemented.** This document is the source of truth for what is done, what is not, and what the code
decides. Nothing here is claimed as deployed or CI-verified: see "Verification status".

## 0. Inputs that were not available (blockers, not assumptions)
| Input named in the brief | Found? | Consequence |
|---|---|---|
| `ftusa_prep/schemas.py` and the prepared `out/` tables | **No** (searched the repo, parent folders and `~`) | TypeScript contracts here are *not yet aligned* with it. The producer-information source columns (`account_sk`, `account_category_name`, ...) come from the brief's field list. Need the path or the files. |
| UI Design Spec Version 2 and the original seven acceptance scenarios (documents) | **No** | The existing REV/CHAT/CONV implementation was kept; V2 changes follow the brief only. |
| Supplied APS/FPS clauses | **No** | `standards` is empty everywhere and the dataset says so. No clause text was invented. |
| Stack of Dreams | Yes, `../stack-of-dreams-communitynavigator` (inspected earlier; mapping in `ARCHITECTURE.md` section 1) | Cognito/PKCE, JWT access-token verification, AgentCore invoke permissions reused. |

## 1. Requirement overrides (brief vs earlier requirements)
| Override | Earlier behaviour | V2 behaviour | Where |
|---|---|---|---|
| Stop, withhold sharing, request deletion are three different things | "Don't save" = delete everything | **Stop** (`POST /conversations/:id/end`): transcript kept, status `stopped`, no record. **Withhold**: sharing choice `ftusa_only`. **Delete**: `POST /conversations/:id/deletion-request` (publication withdrawn at once) or the producer's own `DELETE`. | `service.ts` `end`, `serviceV2.ts` |
| Every finalized record is reviewed | Only consented records reached review | `finalize` always creates a `pending` record, FTUSA-only included; it is never publishable | `finalize` |
| No indefinite retention | Saved summaries had no expiry | Conversations 90 days, records 180 days (DynamoDB TTL); see section 6 | `RETENTION` in `service.ts`, stack TTL on outcomes |
| One entry point | Separate Share and Ask | `/chat` for everything; `/ask` redirects to `/chat`; nav is Home, Ask the AI Agent, Review | `router.ts`, `App.vue` |
| Language | UI picked per session | `/me.preferred_language` initializes new conversations; conversation language persisted; profile never modified by a temporary choice; English fallback | `service.ts` `me`, `create` |
| Peers | none | org peers see eligible reviewed summaries only | `peers.ts`, `serviceV2.ts` |
Old `POST /conversations/:id/consent` is kept for backward compatibility only (tests and old clients) and is not used by the new UI.

## 2. Contract decisions
* **Identity**: four distinct identifiers, resolved server-side from the Cognito `sub`: `organization_id`, `producer_id`, `application_user_id`, `sub`. `/me` returns `identity` and `preferred_language`; an unmapped producer gets `configurationError: "producer_mapping_missing"`, `403 no_profile` on producer data, never a default producer. Strict zod schemas reject any identity, organization, location or entity type in request bodies.
* **Producer information** (`GET /producer-info`): individual (`producerId`, name, preferred language) is separate from shared organization attributes (the nine source columns, multi-valued ones as arrays, missing = `null` shown as "Not provided").
* **Corrections** (`POST /corrections`, `GET /corrections`, reviewer `GET /review/corrections`, `POST /review/corrections/:id/decision`): stored as separate items in the outcomes table (`gsiKind=correction`), original values captured server-side, same-value changes rejected, idempotent by `requestId`. Statuses `pending -> accepted_awaiting_source_update -> applied`, or `rejected`. **`applied` is a recorded fact that someone updated the source table; this app never writes source data.** Allowed fields exclude `account_sk`, membership and permissions.
* **Finalize** (`POST /conversations/:id/finalize`): body `{requestId, summaryHash, sharing, identityPermitted}`. The hash covers language, original summary, English summary and sorted tags; a mismatch is `409 stale_confirmation`. Stored separately: `confirmationHash`, `confirmedAt`, `confirmedByProducerId`, `sharingChoice`, `identityPermitted`, `versions[]`.
* **Three independent states** on a record: `reviewStatus` (pending/approved/corrected), `sharingChoice` (share_conversation / share_summary / ftusa_only) + `identityPermitted`, `publicationStatus` (not_shared, awaiting_review, awaiting_reconfirmation, pending_publication, published, failed, withdrawn).
* **Summary versions**: producer-confirmed version 1 is never overwritten. A reviewer change to meaning/translation creates a `reviewer_revision`, sets `awaiting_reconfirmation`, and publishes only after the producer accepts (`POST /conversations/:id/reconfirm`); declining publishes the original confirmed content. Tag-only corrections need no re-confirmation.
* **Publication**: built from reviewer-approved payload (`publication.payload`: challenge from the confirmed English summary, action/result/standards/citations from the reviewer's case card), versioned (`publication.version`), idempotent (`runPublication` is a no-op when published), failure leaves `failed` and is retryable (`POST /records/:id/publish`, reviewer only). The publisher never reads transcripts. `Deps.publishSideEffect` is the hook where the derived-memory update belongs.
* **Peers** (`GET /peers/summaries?scope=organization|other|all`, `GET /peers/summaries/:caseId`): `caseId = <outcomeId>@<publishedVersion>`. Eligible only if: a different producer, reviewed, `published` at exactly the published version, sharing is `share_*`, no deletion request. Withdrawal or narrowing blocks retrieval immediately because eligibility is recomputed from the authoritative record on every call. Projection returns no transcript and no producer ids; a name only if `identityPermitted` and `share_conversation`. No result -> "Outcome not yet reported". "Ask about this" = `POST /conversations` with `referenceCaseId`, validated server-side, stored on the viewer's own conversation.
* **History**: `GET /conversations` returns own conversations with `status` `in_progress|completed`, `stopped`, and a server `group` (`today|previous_7_days|older`).

## 3. Visibility defaults (shown to producers in the sharing step)
| Choice | Org peers | Other organizations | Name | FTUSA |
|---|---|---|---|---|
| Share the conversation + permitted info | after review | after review | only if ticked | full conversation |
| Share the summary only | after review | after review | never | full conversation |
| Do not share | never | never | never | full conversation |
Organization visibility and wider visibility are not separately switchable in this increment (one rule: any `share_*` choice reaches both, after review). A separate org-only level would need a fourth choice; recorded as a decision to confirm.

## 4. Trust boundaries
Authentication on every API call (JWT authorizer + in-handler `token_use`/client/issuer re-check). Ownership: another producer's conversation is `404`. Reviewer-only operations check the role before parsing input. Reviewer attribution (`reviewedBy`, `decidedBy`) is taken from the token. Peer content is projected server-side before it can reach the browser or the model.

## 5. Data model (existing tables, one new index)
Conversations table: `PROFILE#<sub>` (now carries `organizationId`, `applicationUserId`), `ORG#<id>` (organization + nine source fields), `CONV#`, `MSG#`, `ACTIVE#`. Outcomes table: records (`rec-<conversationId>`), declined markers, corrections (`corr-...`); new GSI `org-index` (`organizationId`, `createdAt`) and TTL on `ttl`.

## 6. Sandbox retention policy
Active conversations expire 7 days after last activity. Completed or stopped conversations (transcript, summary) expire 90 days after closing. Finalized FTUSA records and correction requests expire after 180 days. Producers can delete their own history at any time and request deletion of the retained record. FTUSA can retain and review the full conversation (stated at the sharing step). **Unresolved conflict with older consent text**: the previous consent said a declined summary meant everything was deleted. V2 contradicts that by design (stopping is not deleting); the producer-facing copy was updated, but legal/consent wording needs FTUSA sign-off. Withdrawal does not recall answers already delivered.

## 7. Implementation checklist
| # | Item | Status |
|---|---|---|
| 1 | Inspect repo, Stack of Dreams, reconcile requirements | done (blockers in section 0) |
| 2 | Contracts, trust boundaries, lifecycle | done for the items above |
| 3 | Database extension, demo identities | schema + seed code done; **identities not provisioned** (not deployed) |
| 4 | Auth + language initialization | done (backend + web), unit-tested |
| 5 | Home, producer information accordion, corrections | done, unit-tested; not browser-verified against a deployment |
| 6 | Real Chat-to-AgentCore verification | **not done** (needs deploy) |
| 7 | History + org-peer summaries | done (backend, Home, peer cards) |
| 8 | Issue tracking and AgentCore Memory | **not started** (dataset fixtures exist; no issue store, no memory resources, no recall) |
| 9 | Summary confirmation + sharing | done |
| 10 | Post-conversation evidence + peer cards | peer cards done; **evidence retrieval/Athena/Glue not built**; the panel states the limitation |
| 11 | Review, publication, joined data | publication/versions/corrections done in API; **Review.vue not yet extended** (shows no sharing/version/publication/reconfirmation fields), joined data still the old synthetic tables |
| 12 | Seed and validate | dataset + validator + idempotent seeder written; **not applied** |
| 13 | Browser + CI/CD verification | **not done** |
Also not done: asynchronous turn operations (submit -> operation id -> poll; today a turn is synchronous behind the HTTP API's 30 s limit with a 60 s Lambda timeout), per-conversation lock exists, publication worker is inline (`runPublication`) not an event-driven worker, memory rebuild tooling, Guardrails changes, agent changes (agent tools do not yet receive the referenced peer case or issue history), ReportFindings-style reasoning/tool-event views, SQL exposure.

## 8. Verification status
Local only: backend 84+ tests (in-memory store, stub agent), web 21 tests, infra 12 tests. No AWS call, no browser run, no GitHub run for this branch.
