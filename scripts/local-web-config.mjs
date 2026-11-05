#!/usr/bin/env node
// Writes web/public/config.json for local development against a deployed stack.
// It copies the deployed site's public runtime config (no secrets: API URL, Cognito client ID, issuer, domain)
// and points the sign-in redirects at http://localhost:5173, which the stack allows as an extra callback URL.
// Usage: node scripts/local-web-config.mjs [https://<deployed-site>]   (default: the sandbox site)
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const site = (process.argv[2] ?? process.env.WEB_URL ?? "https://d2lckcajg7v2u5.cloudfront.net").replace(/\/+$/, "");
const local = "http://localhost:5173";
const res = await fetch(`${site}/config.json`, { cache: "no-store" });
if (!res.ok) { console.error(`Could not read ${site}/config.json (HTTP ${res.status}).`); process.exit(1); }
const cfg = await res.json();
for (const k of ["apiBaseUrl", "clientId", "issuer", "authority", "cognitoDomain", "region"]) {
  if (!cfg[k]) { console.error(`${site}/config.json has no ${k}; is this the right site?`); process.exit(1); }
}
const out = { ...cfg, redirectUri: `${local}/auth/callback`, logoutUri: `${local}/` };
const file = fileURLToPath(new URL("../web/public/config.json", import.meta.url));
writeFileSync(file, JSON.stringify(out, null, 2) + "\n");
console.log(`Wrote web/public/config.json from ${site} (sign-in returns to ${local}).`);
