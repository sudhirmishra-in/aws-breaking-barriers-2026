# aws-breaking-barriers-2026

## FTUSA Producer Exchange Agent - first working increment

Authenticated vertical slice: Cognito sign-in (Vue 3) -> HTTP API with JWT authorizer -> TypeScript Lambda -> Strands agent on Amazon Bedrock AgentCore Runtime -> Bedrock model with Guardrails. DynamoDB holds conversations and consented outcomes. **All producer data is synthetic.**

Status: deployed 2026-11-03 to the breaking-barriers-ny account, us-west-2, stack `FtusaExchange-sandbox`. Verified live: unauthenticated and bad-token API calls return 401; the AgentCore runtime answers (Spanish opener, PII flagged not blocked, out-of-scope declined, evidence reported unavailable). NOT yet verified: browser sign-in and the authenticated API path end to end. See `docs/ARCHITECTURE.md`.

> **V2 redesign in progress (branch `redesign-v2`)**: see [docs/REDESIGN_V2.md](docs/REDESIGN_V2.md) for what is implemented, the requirement overrides, retention policy and the remaining work. [docs/DEMO_ACCOUNTS_AND_SCENARIOS.md](docs/DEMO_ACCOUNTS_AND_SCENARIOS.md) lists the synthetic accounts.

## Layout
| Path | What |
|---|---|
| `infra/` | CDK (TypeScript): one stack `FtusaExchange-<env>` |
| `backend/` | API Lambda (TypeScript): contracts (zod), service logic, DynamoDB store, AgentCore client |
| `agent/` | Python Strands agent and AgentCore entry point (`app/main.py`) |
| `web/` | Vue 3 + TypeScript producer chat and reviewer UI |
| `scripts/` | `build_agent.sh` (arm64 zip), `seed_users.py` (synthetic users/profiles) |

## Local checks
```bash
npm install
npm run typecheck && npm test            # backend, infra, web (all use LOCAL MOCKS, no AWS)
(cd agent && uv sync && uv run pytest)   # agent contract tests (stubbed model)
./scripts/build_agent.sh                 # agent/dist/agent.zip
npm run build:web && npm run synth       # needs agent zip + web/dist
```

## Deployment (requires approval; not yet done)
Prerequisites: AWS profile `breaking-barriers-ny` (region us-west-2 verified reachable; account not CDK-bootstrapped), Bedrock model access for the chosen model/inference profile (default `us.anthropic.claude-haiku-4-5-20251001-v1:0`, availability NOT verified for invocation), Docker not required.
```bash
export AWS_PROFILE=breaking-barriers-ny
cd infra && npx cdk bootstrap            # one-time, creates CDKToolkit stack
npx cdk diff && npx cdk deploy           # after ./scripts/build_agent.sh and npm run build:web
python ../scripts/seed_users.py --stack FtusaExchange-sandbox
```
Local web dev: see [docs/LOCAL_DEV.md](docs/LOCAL_DEV.md) (mock mode with no AWS, or `npm run config:local && npm run dev:web` against the sandbox; port 5173 is an allowed callback). Region, env name, model, callback URLs are CDK context (`.env.example`).

## CI/CD
See `docs/CI_CD.md` (workflows, required checks, OIDC roles, prerequisites).

## Seed users
Synthetic producers and a reviewer come from `agent/app/exchange/data/producers.json` (example.com addresses). `seed_users.py` admin-creates them (no open sign-up), adds groups, and writes the sub -> producer profile mapping. Temporary passwords go to `.seed-credentials.local` (git-ignored). Users must set a new password at first sign-in.
