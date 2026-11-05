// DynamoDB rejects unused or undefined expression attribute names and values (ValidationException). The in-memory store cannot catch that, so check the real command inputs.
import { describe, expect, it } from "vitest";
import { DynamoDBClient } from "@aws-sdk/client-dynamodb";
import { DdbStore } from "../src/ddbStore";

type Cmd = { input: Record<string, unknown> };
function store() {
  const sent: Cmd[] = [];
  const s = new DdbStore("conv", "out", new DynamoDBClient({ region: "us-west-2", credentials: { accessKeyId: "x", secretAccessKey: "y" } }));
  (s as unknown as { d: { send: (c: Cmd) => Promise<unknown> } }).d.send = async (c: Cmd) => { sent.push(c); return { Attributes: {}, Items: [], Item: undefined }; };
  return { sent, s };
}
function check(input: Record<string, unknown>) {
  const expr = ["UpdateExpression", "ConditionExpression", "KeyConditionExpression", "FilterExpression", "ProjectionExpression"].map((k) => String(input[k] ?? "")).join(" ");
  for (const n of Object.keys((input.ExpressionAttributeNames ?? {}) as object)) expect(expr, `unused name ${n}`).toContain(n);
  for (const v of Object.keys((input.ExpressionAttributeValues ?? {}) as object)) expect(expr, `unused value ${v}`).toContain(v);
  for (const n of expr.match(/#\w+/g) ?? []) expect(Object.keys((input.ExpressionAttributeNames ?? {}) as object), `undefined name ${n}`).toContain(n);
  for (const v of expr.match(/:\w+/g) ?? []) expect(Object.keys((input.ExpressionAttributeValues ?? {}) as object), `undefined value ${v}`).toContain(v);
}
describe("DdbStore expression hygiene", () => {
  it("every update and query uses exactly the names and values it declares", async () => {
    const { s, sent } = store();
    await s.updateOutcome("rec-1", null, { memoryStatus: "synced", memoryAttempts: 1 });
    await s.updateOutcome("rec-1", ["pending_publication", "failed"], { publicationStatus: "published" });
    await s.updateOutcome("rec-1", ["not_shared"], { sharingChoice: "ftusa_only" });
    await s.updateCorrection("corr-1", ["pending"], { status: "accepted_awaiting_source_update", decidedBy: "x" });
    await s.updateIssue({ issueId: "i", version: 2 } as never, 1);
    await s.listCorrections({ organizationId: "O" }); await s.listCorrections({}); await s.listRecordsByOrganization("O"); await s.listPublishedRecords(); await s.listIssuesByOrganization("O");
    await s.reviewOutcome("rec-1", { reviewStatus: "approved" });
    expect(sent.length).toBeGreaterThan(8);
    for (const c of sent) check(c.input);
  });
});
