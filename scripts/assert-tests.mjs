// Usage: node scripts/assert-tests.mjs <vitest-json-report> <min-passed>
// Fails unless at least <min-passed> tests ran and passed with none failed, so a renamed or deleted group cannot pass silently.
import { readFileSync } from "node:fs";
const [file, min] = process.argv.slice(2);
const r = JSON.parse(readFileSync(file, "utf8"));
if (r.numFailedTests > 0 || r.numPassedTests < Number(min)) {
  console.error(`expected >= ${min} passing tests and 0 failures; got passed=${r.numPassedTests} failed=${r.numFailedTests}`);
  process.exit(1);
}
console.log(`ok: ${r.numPassedTests} passed (minimum ${min})`);
