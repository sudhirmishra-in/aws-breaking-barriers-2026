# CI/CD (GitHub Actions)

Pattern reused from Stack of Dreams after inspecting it: SHA-pinned actions, `permissions: contents: read`, no secrets in PR checks, `npm ci` / `uv sync --locked`, `.nvmrc`, a `hygiene` secret scan, named required checks. Stack of Dreams had no automated AWS deploy (its backend is deployed manually, its frontend by Amplify); the deployment half here is new and uses GitHub OIDC, which its docs listed as the intended next step.

```
PR --> CI (no AWS, no secrets) --merge--> main --CI green--> Deploy sandbox: approval (environment) -> cdk deploy -> smoke tests -> Ingest environmental facts (also runs daily on a schedule)
```

## Workflows
| File | Trigger | Needs |
|---|---|---|
| `.github/workflows/ci.yml` | `pull_request` to main, `push` to main | nothing (no secrets, no AWS, never `pull_request_target`) |
| `.github/workflows/deploy.yml` | `workflow_run` of CI succeeded on a push to main, or manual from main | environment `sandbox`, repo variables below |
| `.github/workflows/ingest.yml` | `schedule` (daily), `workflow_run` of a successful `Deploy sandbox`, or manual from main | the main-branch smoke role (no environment gate), repo variables below |

### Required status checks (branch protection on `main`)
`Web (lint, typecheck, test, build)`, `Backend (typecheck, test, build)`, `Authorization, consent and idempotency tests`, `Agent (pytest)`, `Infrastructure (typecheck, tests, cdk synth)`, `Repository hygiene (no secrets)`.
Component jobs are skipped (reported as passing) when a pull request does not touch that component; `Detect changed components` decides. Any `.github/`, `scripts/`, lockfile or `.nvmrc` change runs everything. A failing command fails its job: no `continue-on-error`, no `|| true`. The security-behaviour job also asserts a minimum number of passing tests per group (`scripts/assert-tests.mjs`) so the groups cannot be emptied or renamed silently.

## AWS access (OIDC, no long-lived keys)
`FtusaCiRoles-sandbox` (CDK, `infra/lib/ci-roles-stack.ts`) is deployed **once by an administrator** and creates the GitHub OIDC provider and two roles. It is separate on purpose: the pipeline cannot grant itself access.
| Role | Trusted `sub` | Can do |
|---|---|---|
| `ftusa-gha-deploy-sandbox` | `<sub prefix>:environment:sandbox` | assume the CDK bootstrap roles, read the stack and bootstrap version |
| `ftusa-gha-smoke-sandbox` | `<sub prefix>:ref:refs/heads/main` | read stack outputs, manage disposable Cognito users, put/delete/query the three tables (conversations, outcomes, environmental-facts), invoke the runtime |
Pull-request jobs have **no** AWS role. Trust uses exact `StringEquals` on `aud` and `sub`.

## One-time prerequisites (manual)

One-time per new account/region. An administrator runs these — or a Claude Code agent acting on the admin's behalf can, since every step below is either a concrete command or a named console action with a stated verification. **Part A** makes the pipeline able to deploy; **Part B** makes the deployed stack actually answer questions. The CDK deploy creates the tables and runtime *empty*, so a green deploy alone is not enough — Part B is what a first deploy in a fresh env still owes.

### Part A — make the pipeline able to deploy
1. `npx cdk bootstrap` for the account/region (done in sandbox). The deploy job fails with a clear message if missing.
2. `npx cdk deploy FtusaCiRoles-sandbox -c githubSubjectPrefix="$(gh api repos/OWNER/REPO/actions/oidc/customization/sub --jq .sub_claim_prefix)"` as an administrator. New GitHub repositories put immutable owner/repo ids in the OIDC `sub` claim (`repo:owner@id/repo@id`), so the plain `repo:owner/repo` form is rejected by AWS (this caused the first deploy failure). **Redeploy this stack whenever the role definitions in `infra/lib/ci-roles-stack.ts` change** — it is deployed separately from the pipeline, so a code change to a role does not take effect until you redeploy. Example: the smoke role was extended to write the `environmental-facts` table (for the `Ingest environmental facts` workflow); until you redeploy, that job's `PutItem` is AccessDenied.
3. GitHub -> Settings -> Environments -> create `sandbox`: **required reviewers**, deployment branches limited to `main`.
4. GitHub -> Settings -> Secrets and variables -> Actions -> **Variables** (repository level; none are secrets): `AWS_REGION` (`us-west-2`), `AWS_DEPLOY_ROLE_ARN`, `AWS_SMOKE_ROLE_ARN` (the stack outputs).
5. Branch protection on `main`: require a pull request, require the six checks above, block force pushes.

### Part B — make the deployed stack answer questions (after the first deploy lands)
6. **Enable the Bedrock model (AWS Marketplace subscription).** The runtime's default model is the cross-region inference profile `us.anthropic.claude-haiku-4-5-20251001-v1:0` (override with `-c modelId=`). In a fresh account the model is not subscribed, so every call is a `ConverseStream` -> `AccessDeniedException` -> **502**, and the smoke test's "message reaches Bedrock, no fallback" assertion fails. Subscribe once (AWS Marketplace -> the Claude model -> subscribe, or enable it in the Bedrock console); it takes effect after a short propagation window (~5 min). Verify by invoking the model with the runtime role until the reply is not an `AccessDeniedException`.
7. **Populate `ENVIRONMENTAL_FACTS_TABLE` — automatic via the `Ingest environmental facts` workflow.** The CDK creates the DynamoDB table (stack output `EnvironmentalFactsTable`, e.g. `ftusa-environmental-facts-sandbox`) **empty**; until facts exist the agent's `get_environmental_context` tool returns `[]` and answers "no external data". It is populated **automatically** by `.github/workflows/ingest.yml`, which runs the Open-Meteo (ERA5) ingest on a daily `schedule`, **after every successful `Deploy sandbox` run** (`workflow_run`, so a first deploy self-populates instead of waiting for the next cron), and on `workflow_dispatch`. The job assumes the main-branch smoke role (extended to write the facts table), reads the table name from the live stack outputs, and writes one row per gazetteer country. The pilot set is five countries, so expect exactly **5 rows**:

   | region_key | fact_key | dataset | indicator | horizon |
   |---|---|---|---|---|
   | colombia#COUNTRY | open_meteo#ytd_rainfall_mm#current | open_meteo | ytd_rainfall_mm | current |
   | honduras#COUNTRY | open_meteo#ytd_rainfall_mm#current | open_meteo | ytd_rainfall_mm | current |
   | mexico#COUNTRY | open_meteo#ytd_rainfall_mm#current | open_meteo | ytd_rainfall_mm | current |
   | peru#COUNTRY | open_meteo#ytd_rainfall_mm#current | open_meteo | ytd_rainfall_mm | current |
   | vietnam#COUNTRY | open_meteo#ytd_rainfall_mm#current | open_meteo | ytd_rainfall_mm | current |

   Each row carries `value` (current-year YTD total, mm), `baseline_value` (same-window 1991-2020 total, mm), `baseline_delta_pct`, `baseline_period` = "1991-2020 (same window)", `theme` = climate, `is_projection` = false, and `is_stand_in` = false. A failed fetch writes a flagged stand-in (`value` = null, `is_stand_in` = true) instead of crashing, so the agent says "no reliable data" for that country rather than a number. **Manual fallback** (only if the workflow is unavailable): `ENVIRONMENTAL_FACTS_TABLE=<table> python -m external_data.ingest.open_meteo`, run from the repo root with credentials that can write the table. Verify with `aws dynamodb scan --table <table>` (5 items, one per country) or by asking the agent a Colombia rainfall question and seeing a real figure with its baseline.
8. **Mint Cognito users.** The pool has `selfSignUpEnabled: false`, so no one can self-register. The smoke test mints and deletes its own disposable producer, but any **standing** account must be created by an admin: `admin_create_user`, then `admin_set_user_password(Permanent=True)` (auto-confirms), then add to the `producer` or `reviewer` group.
9. **(Demo) Write producer profiles.** The app builds each session's trusted context (country / entity type / crop) from a profile item in the conversations table (`pk = PROFILE#{sub}`, `sk = META`, `profile = {producerId, displayName, entityType, location, crop, preferredLanguage}`). Write one per demo producer, using a gazetteer country for `location` so the C5 tool has data to return.

## What a deploy does
Builds the agent package (arm64) and the web bundle, runs `cdk deploy FtusaExchange-sandbox` with `-c gitSha=<commit>`. Everything is in one stack, so CloudFormation orders it: Cognito, tables, guardrail, runtime, API, then the web bucket with `config.json` generated from the live outputs (API URL, client id, Cognito domain, redirect URL). Callback/logout URLs and CORS come from the CloudFront URL in the same stack. The commit is written to the runtime environment, a stack tag and a stack output; the summary lists the commit, URLs and region (no secrets).

## Smoke tests (`scripts/smoke_sandbox.py`, real services, no mocks)
Frontend loads and its config matches the deployment outputs; unauthenticated and malformed-token calls get 401; the AgentCore runtime reports the commit being deployed (direct ping through IAM); a disposable producer reads its profile, creates a conversation, sends a message that reaches AgentCore and Bedrock (no fallback on that path), a retry with the same `requestId` is not duplicated, the conversation is restored, `/ask` answers with evidence reported unavailable; a second producer gets 404 on read/append/end; a producer gets 403 on every reviewer operation; a body-supplied `producerId` is rejected. Everything it creates is deleted in `finally`. Passwords and tokens are masked and never printed.

**Authentication trade-off:** the browser client stays PKCE-only with no password flows. For CI, the *sandbox only* (`-c enableCiClient=true`) adds a second app client that supports only `ADMIN_USER_PASSWORD_AUTH`; tokens can be minted only through the IAM-signed admin API, so there is no public or browser bypass. The API accepts that client id as an additional audience. Not enabled unless the context flag is set.

## Rollback
Re-run the deploy workflow on a previous commit's workflow (or revert and merge); CloudFormation rolls back failed updates automatically.
