# Run the web UI locally

This guide is written so a developer, or their Claude Code, can follow it step by step. It covers the **web UI only** (Vue 3 + Vite). The API, agent and database stay in the deployed AWS sandbox; you don't need to run them.

There are two ways to run it:

| Mode | Needs AWS or a login? | Use it for |
|---|---|---|
| **A. Mock mode** | No | UI work: layout, styles, translations. The data is fake and built into the dev server. |
| **B. Sandbox mode** | A sandbox user account (no AWS credentials) | Checking real behaviour: sign-in, the real agent, real records. |

Start with mock mode. It works offline in about two minutes.

## Prerequisites

- **Node.js 24 or newer** (`.nvmrc` pins 24; CI uses 24). Check with `node -v`. With nvm, run `nvm install && nvm use` from the repo root.
- **git** and access to `https://github.com/sudhirmishra-in/aws-breaking-barriers-2026`.
- You don't need Python, AWS credentials, the AWS CLI or CDK to run the UI.

## 1. Clone and install

```bash
git clone https://github.com/sudhirmishra-in/aws-breaking-barriers-2026.git
```

```bash
cd aws-breaking-barriers-2026 && npm ci
```

`npm ci` installs all workspaces (`web`, `backend`, `infra`) from the lock file. Run it from the **repo root**, not from `web/`.

## 2A. Mock mode (no AWS, no login)

```bash
npm run dev:web
```

Then open one of these:

- Producer screens: http://localhost:5173/?mock=producer
- Reviewer screen: http://localhost:5173/review?mock=reviewer

How it works: in `vite dev` only, `?mock=producer|reviewer` loads `web/src/devMock.ts`, which signs you in as a fake user and answers API calls with canned data. It is never part of the production build. Each page load needs the `?mock=...` parameter, so add it again after a hard refresh if the app sends you to `/login`.

Limits of mock mode:
- Only the routes listed in `devMock.ts` exist. Anything else shows "Mock has no such route." To add data, add an entry to the `routes` map there.
- The agent's replies are fixed, and Listen plays a short tone instead of a voice.
- The microphone returns a fixed sentence.

## 2B. Sandbox mode (real sign-in, real data)

1. Create the local runtime config. It contains no secrets: only the public API URL, Cognito client ID, issuer and domain, copied from the deployed site.

   ```bash
   npm run config:local
   ```

   This writes `web/public/config.json`, which git ignores, so don't commit it. To use a different deployment, pass its URL: `node scripts/local-web-config.mjs https://<site>`.

2. Start the dev server:

   ```bash
   npm run dev:web
   ```

3. Open http://localhost:5173. Choose a role on the login screen and sign in on the Cognito page. You'll come back to `http://localhost:5173/auth/callback`; the stack allows that address as an extra callback URL.

**Accounts.** Sign-up is closed, so ask the project owner for an account. The sandbox has these synthetic users (passwords are shared privately, never in the repo or chat):

| User | Role | Producer |
|---|---|---|
| `producer.demo1@example.com` | producer | Unión Sierra Madre (P-MX-004), English |
| `productor.demo2@example.com` | producer | Finca Alto Mirador (P-CO-001), Spanish |
| `producteur.demo3@example.com` | producer | Coopérative Espoir de Soubré (P-CI-005), French |
| `reviewer.demo@example.com` | reviewer | — |

On first sign-in, Cognito asks you to set a new password.

Everything you do in sandbox mode is real: messages go to the deployed agent (Amazon Bedrock), and saved summaries appear on the reviewer screen. Use only synthetic content, never real personal details.

## 3. Checks before you push

These run the same checks as CI for the web app, with no AWS:

```bash
npm run lint && npm run typecheck -w web && npm test -w web && npm run build -w web
```

To run every workspace: `npm run typecheck && npm test`. Open a pull request against `main`; `main` is protected, and CI must pass before merging. Deploys to the sandbox happen from `main` with an approval (see `docs/CI_CD.md`).

## Where things are

| Path | What |
|---|---|
| `web/src/views/` | Pages: `Login`, `Home`, `Chat` (producer conversation), `Ask`, `Review` (reviewer screen) |
| `web/src/components/` | Shared pieces (history dropdown, progress panel, microphone, and so on) |
| `web/src/lib/i18n.ts` | All text in English, Spanish and French. Add every new string in all three. |
| `web/src/lib/api.ts` | API client; `web/src/types.ts` holds the response types |
| `web/src/style.css` | Colors and theme. Navy and lime brand; dark mode is the `html.dark` block at the end. |
| `web/src/devMock.ts` | Mock-mode data |
| `docs/ARCHITECTURE.md` | API routes, data model and design decisions |

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Clicking Sign in shows "We could not load your account. Please try again." | Usually `web/public/config.json` is missing or out of date. Run `npm run config:local` and restart the dev server, or use mock mode. |
| Redirected to `/login` in mock mode | The `?mock=...` parameter was lost. Open http://localhost:5173/?mock=producer again. |
| Cognito says `redirect_mismatch` | The app isn't on port 5173. Stop whatever else uses 5173 and restart; the `dev` script pins `--port 5173`. |
| Calls fail with a CORS error | Same cause: only `http://localhost:5173` is allowed. Don't use `127.0.0.1`. |
| "Your session has expired" | Tokens are kept in memory only, so a full page reload signs you out. Sign in again. |
| `npm ci` fails on engine or version errors | Use Node 24 (`nvm use`). |

## Notes for Claude Code

- Run every command from the repo root.
- Start the dev server with `npm run dev:web` as a long-running process (the preview tool or a background terminal), not a blocking shell command.
- Never print, commit or ask for passwords. The user types their password on the Cognito page themself.
- Don't commit `web/public/config.json`, `.seed-credentials.local` or `cdk-outputs.json`; all three are git-ignored.
- To check UI changes without signing in, use mock mode and add any data you need in `web/src/devMock.ts`.
