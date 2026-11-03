# CI/CD (GitHub Actions)

Pattern reused from Stack of Dreams after inspecting it: SHA-pinned actions, `permissions: contents: read`, no secrets in PR checks, `npm ci` / `uv sync --locked`, `.nvmrc`, a `hygiene` secret scan, named required checks. Stack of Dreams had no automated AWS deploy (its backend is deployed manually, its frontend by Amplify); the deployment half here is new and uses GitHub OIDC, which its docs listed as the intended next step.

```
PR --> CI (no AWS, no secrets) --merge--> main --CI green--> Deploy sandbox: approval (environment) -> cdk deploy -> smoke tests
```

## Workflows
| File | Trigger | Needs |
|---|---|---|
| `.github/workflows/ci.yml` | `pull_request` to main, `push` to main | nothing (no secrets, no AWS, never `pull_request_target`) |
| `.github/workflows/deploy.yml` | `workflow_run` of CI succeeded on a push to main, or manual from main | environment `sandbox`, repo variables below |

### Required status checks (branch protection on `main`)
`Web (lint, typecheck, test, build)`, `Backend (typecheck, test, build)`, `Authorization, consent and idempotency tests`, `Agent (pytest)`, `Infrastructure (typecheck, tests, cdk synth)`, `Repository hygiene (no secrets)`.
Component jobs are skipped (reported as passing) when a pull request does not touch that component; `Detect changed components` decides. Any `.github/`, `scripts/`, lockfile or `.nvmrc` change runs everything. A failing command fails its job: no `continue-on-error`, no `|| true`. The security-behaviour job also asserts a minimum number of passing tests per group (`scripts/assert-tests.mjs`) so the groups cannot be emptied or renamed silently.

## AWS access (OIDC, no long-lived keys)
`FtusaCiRoles-sandbox` (CDK, `infra/lib/ci-roles-stack.ts`) is deployed **once by an administrator** and creates the GitHub OIDC provider and two roles. It is separate on purpose: the pipeline cannot grant itself access.
| Role | Trusted `sub` | Can do |
|---|---|---|
| `ftusa-gha-deploy-sandbox` | `<sub prefix>:environment:sandbox` | assume the CDK bootstrap roles, read the stack and bootstrap version |
| `ftusa-gha-smoke-sandbox` | `<sub prefix>:ref:refs/heads/main` | read stack outputs, manage disposable Cognito users, put/delete items in the two tables, invoke the runtime |
Pull-request jobs have **no** AWS role. Trust uses exact `StringEquals` on `aud` and `sub`.

## One-time prerequisites (manual)
1. `npx cdk bootstrap` for the account/region (done in sandbox). The deploy job fails with a clear message if missing.
2. `npx cdk deploy FtusaCiRoles-sandbox -c githubSubjectPrefix="$(gh api repos/OWNER/REPO/actions/oidc/customization/sub --jq .sub_claim_prefix)"` as an administrator. New GitHub repositories put immutable owner/repo ids in the OIDC `sub` claim (`repo:owner@id/repo@id`), so the plain `repo:owner/repo` form is rejected by AWS (this caused the first deploy failure).
3. GitHub -> Settings -> Environments -> create `sandbox`: **required reviewers**, deployment branches limited to `main`.
4. GitHub -> Settings -> Secrets and variables -> Actions -> **Variables** (repository level; none are secrets): `AWS_REGION` (`us-west-2`), `AWS_DEPLOY_ROLE_ARN`, `AWS_SMOKE_ROLE_ARN` (the stack outputs).
5. Branch protection on `main`: require a pull request, require the six checks above, block force pushes.

## What a deploy does
Builds the agent package (arm64) and the web bundle, runs `cdk deploy FtusaExchange-sandbox` with `-c gitSha=<commit>`. Everything is in one stack, so CloudFormation orders it: Cognito, tables, guardrail, runtime, API, then the web bucket with `config.json` generated from the live outputs (API URL, client id, Cognito domain, redirect URL). Callback/logout URLs and CORS come from the CloudFront URL in the same stack. The commit is written to the runtime environment, a stack tag and a stack output; the summary lists the commit, URLs and region (no secrets).

## Smoke tests (`scripts/smoke_sandbox.py`, real services, no mocks)
Frontend loads and its config matches the deployment outputs; unauthenticated and malformed-token calls get 401; the AgentCore runtime reports the commit being deployed (direct ping through IAM); a disposable producer reads its profile, creates a conversation, sends a message that reaches AgentCore and Bedrock (no fallback on that path), a retry with the same `requestId` is not duplicated, the conversation is restored, `/ask` answers with evidence reported unavailable; a second producer gets 404 on read/append/end; a producer gets 403 on every reviewer operation; a body-supplied `producerId` is rejected. Everything it creates is deleted in `finally`. Passwords and tokens are masked and never printed.

**Authentication trade-off:** the browser client stays PKCE-only with no password flows. For CI, the *sandbox only* (`-c enableCiClient=true`) adds a second app client that supports only `ADMIN_USER_PASSWORD_AUTH`; tokens can be minted only through the IAM-signed admin API, so there is no public or browser bypass. The API accepts that client id as an additional audience. Not enabled unless the context flag is set.

## Rollback
Re-run the deploy workflow on a previous commit's workflow (or revert and merge); CloudFormation rolls back failed updates automatically.
