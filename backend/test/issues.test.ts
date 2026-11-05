// LOCAL tests: issue history rules and derived memory sync (in-memory store, fake memory). No AWS.
import { describe, expect, it } from "vitest";
import type { AgentClient, AgentTurnRequest, AgentTurnResponse } from "../src/agent";
import type { IssueEvent, IssueRecord, Organization, ProducerProfile } from "../src/contracts";
import { route } from "../src/handler";
import { deriveStatus, matchIssue, withEvent } from "../src/issues";
import { FakeMemory } from "../src/memory";
import type { Principal } from "../src/service";
import { MemoryStore } from "../src/store";
import { ServiceV2 } from "../src/serviceV2";
import type { ApiError } from "../src/errors";

const ev = (eventId: string, type: IssueEvent["type"], at: string, extra: Partial<IssueEvent> = {}): IssueEvent => ({ eventId, type, at, source: "producer_entry", ...extra });
const base = (events: IssueEvent[] = []): IssueRecord => ({ issueId: "issue-1", organizationId: "ORG-A", reportingProducerIds: ["P1"], description: "dry spell", tags: ["climate_weather"], crop: "coffee", geography: "Huila",
  firstReportedAt: "2026-09-01T00:00:00Z", lastReportedAt: "2026-09-01T00:00:00Z", status: "open", linkedConversations: [], events, evidenceRefs: [], visibility: "organization", reviewStatus: "pending", version: 1 });

describe("issue status rules", () => {
  it("advice or a finished conversation never resolves an issue; only a confirmed, dated resolution does", () => {
    expect(deriveStatus([ev("1", "reported", "2026-09-01")])).toBe("open");
    expect(deriveStatus([ev("1", "reported", "2026-09-01"), ev("2", "guidance", "2026-09-01")])).toBe("open");
    expect(deriveStatus([ev("1", "reported", "2026-09-01"), ev("2", "action_planned", "2026-09-02")])).toBe("action_planned");
    expect(deriveStatus([ev("1", "reported", "2026-09-01"), ev("2", "action", "2026-09-03", { text: "tanks" })])).toBe("action_in_progress"); // action without outcome
    expect(deriveStatus([ev("1", "reported", "2026-09-01"), ev("2", "action", "2026-09-03"), ev("3", "outcome", "2026-10-01")])).toBe("unknown"); // outcome is not a verified resolution
    expect(deriveStatus([ev("1", "reported", "2026-09-01"), ev("2", "action", "2026-09-03"), ev("3", "outcome", "2026-10-01"), ev("4", "resolution_confirmed", "2026-10-02")])).toBe("resolved");
    expect(deriveStatus([ev("4", "resolution_confirmed", "2026-10-02"), ev("5", "recurrence", "2026-11-01")])).toBe("recurring");
  });
  it("a correction supersedes a fact without erasing it", () => {
    const events = [ev("1", "reported", "2026-09-01"), ev("2", "resolution_confirmed", "2026-10-02"), ev("3", "correction" as never, "2026-10-03", { supersedes: "2" })];
    expect(deriveStatus(events)).toBe("open"); expect(events).toHaveLength(3);
  });
  it("adding events is idempotent, ordered by date, and bumps the version once", () => {
    const i = base(); const e = ev("e1", "action", "2026-09-05", { producerId: "P2" });
    const a = withEvent(i, e), b = withEvent(a, e);
    expect(b).toBe(a); expect(a.version).toBe(2); expect(a.reportingProducerIds).toEqual(["P1", "P2"]);
  });
});

describe("matching a new report to history", () => {
  const now = Date.parse("2026-11-04T00:00:00Z");
  it("a matching tag alone is a question, not a link; same producer + same crop + shared tag + recent + unresolved links", () => {
    const old = { ...base(), lastReportedAt: "2026-06-01T00:00:00Z" };
    const r1 = matchIssue([old], { producerId: "P1", tags: ["climate_weather"], crop: "coffee", nowMs: now });
    expect(r1.link).toBeUndefined(); expect(r1.candidates).toHaveLength(1);
    const recent = { ...base(), lastReportedAt: "2026-10-20T00:00:00Z" };
    expect(matchIssue([recent], { producerId: "P1", tags: ["climate_weather"], crop: "coffee", nowMs: now }).link?.issueId).toBe("issue-1");
    expect(matchIssue([recent], { producerId: "P2", tags: ["climate_weather"], crop: "coffee", nowMs: now }).link).toBeUndefined(); // someone else: ask
    expect(matchIssue([{ ...recent, status: "resolved" }], { producerId: "P1", tags: ["climate_weather"], crop: "coffee", nowMs: now }).link).toBeUndefined(); // resolved: ask about recurrence
    expect(matchIssue([recent], { producerId: "P1", tags: ["water"], crop: "coffee", nowMs: now }).candidates).toHaveLength(0);
    expect(matchIssue([recent], { producerId: "P1", tags: ["climate_weather"], crop: "cocoa", nowMs: now }).candidates).toHaveLength(0);
  });
});

class Stub implements AgentClient {
  async turn(req: AgentTurnRequest): Promise<AgentTurnResponse> {
    const playback = req.context.mode === "intake" && req.context.allowPlayback;
    return { reply: "r", language: req.context.language, phase: req.context.mode === "guidance" ? "guidance" : playback ? "playback" : "intake", playbackSummary: playback ? "late rain" : null, title: playback ? "Late rain" : null,
      summaryEn: req.context.mode === "guidance" ? "EN summary" : null, summaryOriginal: req.context.mode === "guidance" ? "EN summary" : null, challengeTags: req.context.mode === "guidance" ? ["climate_weather"] : [], piiFlag: false, piiTypes: [], evidence: { status: "unavailable" } };
  }
}
const org = (id: string): Organization => ({ organizationId: id, name: id, info: { accountSk: "A", accountCategoryName: "Cooperative", productCategoryName: ["Coffee"], accountTypeName: null, certificationScopeName: null, certificationStatusName: null, countryName: "Colombia", rawSupplyChainRoleTxt: [], structureTxt: null } });
const prof = (id: string, o: string): ProducerProfile => ({ producerId: id, displayName: id, entityType: "cooperative", location: "Huila", crop: "coffee", preferredLanguage: "en", organizationId: o });
const P = (s: string): Principal => ({ sub: s, groups: ["producer"] }); const ana = P("s-ana"), mateo = P("s-mateo"), lucia = P("s-lucia"); const rev: Principal = { sub: "r", groups: ["reviewer"], name: "R" };
let n = 0; const rid = () => `req-${++n}-xxxxxxxx`;
const code = async (p: Promise<unknown>) => { try { await p; return "ok"; } catch (e) { return (e as ApiError).code ?? (e as Error).name; } };
function setup(clock = { t: Date.parse("2026-11-04T12:00:00Z") }) {
  const store = new MemoryStore(); const memory = new FakeMemory(); const metrics: string[] = [];
  store.orgs.set("ORG-A", org("ORG-A")); store.orgs.set("ORG-H", org("ORG-H"));
  store.profiles.set("s-ana", prof("PRD-ANA", "ORG-A")); store.profiles.set("s-mateo", prof("PRD-MATEO", "ORG-A")); store.profiles.set("s-lucia", prof("PRD-LUCIA", "ORG-H"));
  return { store, memory, metrics, clock, svc: new ServiceV2({ store, agent: new Stub(), memory, now: () => clock.t, metric: (m, _v, _u, d) => metrics.push(`${m}:${d?.Result ?? ""}`) }) };
}
async function finalized(svc: ServiceV2, p: Principal, sharing: "share_summary" | "ftusa_only" = "ftusa_only") {
  const id = (await svc.create(p, undefined, rid())).conversation.conversationId;
  await svc.message(p, id, rid(), "a"); await svc.message(p, id, rid(), "b");
  const h = (await svc.playback(p, id, { requestId: rid(), decision: "confirm" })).confirmation!.summaryHash;
  await svc.finalize(p, id, { requestId: rid(), summaryHash: h, sharing, identityPermitted: false });
  return id;
}

describe("issue history in the service", () => {
  it("a first report opens an issue for the organization and syncs personal and organization memory (never transcripts)", async () => {
    const { svc, store, memory } = setup(); const id = await finalized(svc, ana);
    const ctx = await svc.issueContext(ana, id);
    expect(ctx.issue).toMatchObject({ status: "open", reporterCount: 1, tags: ["climate_weather"] }); expect(ctx.decision).toBe("none"); expect(ctx.memoryStatus).toBe("synced");
    expect(memory.events.map((e) => e.scope).sort()).toEqual(["organization", "personal"]);
    expect(memory.events.find((e) => e.scope === "organization")!.actorId).toBe("ORG-A"); expect(memory.events.find((e) => e.scope === "personal")!.actorId).toBe("PRD-ANA");
    expect(JSON.stringify(memory.events)).not.toContain("a\"");
    expect((await svc.listIssues(mateo)).items).toHaveLength(1); expect((await svc.listIssues(lucia)).items).toHaveLength(0); // other organizations see nothing
    expect(JSON.stringify(await svc.listIssues(mateo))).not.toContain("PRD-ANA");
    expect(store.issues.size).toBe(1);
  });
  it("a similar report by a colleague asks 'same problem?'; yes links and records, no opens a separate issue; asking again changes nothing", async () => {
    const { svc, store } = setup(); await finalized(svc, ana);
    const id2 = await finalized(svc, mateo);
    const q = await svc.issueContext(mateo, id2);
    expect(q.decision).toBe("pending"); expect(q.candidates).toHaveLength(1); expect(q.issue).toBeNull(); expect(store.issues.size).toBe(1); // nothing assumed
    expect(await code(svc.linkIssue(mateo, id2, { issueId: "issue-forged", same: true }))).toBe("validation_error");
    const linked = await svc.linkIssue(mateo, id2, { issueId: q.candidates[0].issueId, same: true });
    expect(linked.issue).toMatchObject({ reporterCount: 2 }); expect(linked.decision).toBe("linked");
    expect((await svc.linkIssue(mateo, id2, { issueId: q.candidates[0].issueId, same: true })).issue!.events.filter((e) => e.type === "reported")).toHaveLength(2);
    const id3 = await finalized(svc, mateo); expect((await svc.issueContext(mateo, id3)).decision).toBe("linked"); // same producer, recent: auto-linked
    const idSep = await finalized(svc, ana); void idSep;
    const a = P("s-x"); void a;
  });
  it("'separate problem' opens a new issue", async () => {
    const { svc, store } = setup(); await finalized(svc, ana); const id2 = await finalized(svc, mateo);
    const r = await svc.linkIssue(mateo, id2, { same: false });
    expect(r.decision).toBe("separate"); expect(store.issues.size).toBe(2);
  });
  it("producer-entered action and outcome are dated facts; status follows the rules; a confirmed resolution and a later recurrence are explicit; retries do not duplicate", async () => {
    const clock = { t: Date.parse("2026-11-04T12:00:00Z") }; const { svc, memory } = setup(clock); const id = await finalized(svc, ana);
    const issueId = (await svc.issueContext(ana, id)).issue!.issueId;
    const r1 = rid();
    expect((await svc.addIssueEvent(ana, issueId, { requestId: r1, type: "action", text: "Built two tanks" })).status).toBe("action_in_progress");
    expect((await svc.addIssueEvent(ana, issueId, { requestId: r1, type: "action", text: "Built two tanks" })).events.filter((e) => e.type === "action")).toHaveLength(1);
    clock.t += 30 * 86400000;
    expect((await svc.addIssueEvent(mateo, issueId, { requestId: rid(), type: "outcome", text: "Fewer dry days" })).status).toBe("unknown"); // colleague can add; not resolved
    clock.t += 86400000;
    expect((await svc.addIssueEvent(ana, issueId, { requestId: rid(), type: "resolution_confirmed" })).status).toBe("resolved");
    clock.t += 90 * 86400000;
    expect((await svc.addIssueEvent(ana, issueId, { requestId: rid(), type: "recurrence", text: "Dry again" })).status).toBe("recurring");
    expect(memory.events.filter((e) => e.token.startsWith("ie-")).length).toBeGreaterThanOrEqual(4);
    expect(await code(svc.addIssueEvent(P("s-lucia"), issueId, { requestId: rid(), type: "action", text: "x" }))).toBe("not_found"); // other organization
    await expect(route(svc, ana, "POST", `/issues/${issueId}/events`, { requestId: rid(), type: "action" })).rejects.toThrow(); // text required
    await expect(route(svc, ana, "POST", `/issues/${issueId}/events`, { requestId: rid(), type: "reported", text: "x" })).rejects.toThrow(); // only the allowed types
  });
  it("the follow-up recall names dates and statuses from memory and never claims a resolution", async () => {
    const { svc } = setup(); const id = await finalized(svc, ana); const issueId = (await svc.issueContext(ana, id)).issue!.issueId;
    await svc.addIssueEvent(ana, issueId, { requestId: rid(), type: "action_planned", text: "Water storage was discussed" });
    const id2 = await finalized(svc, mateo); const q = await svc.issueContext(mateo, id2);
    expect(q.recall.length).toBeGreaterThan(0); expect(q.recall.join(" ")).toMatch(/On 2026-11-04/); expect(q.recall.join(" ")).not.toMatch(/resolved/i);
  });
});

describe("derived memory is repairable and boundary-respecting", () => {
  it("a failed memory write never breaks the user's action; it is retried idempotently by reconcile", async () => {
    const { svc, memory, store, metrics } = setup(); memory.fail = true;
    const id = await finalized(svc, ana);
    expect(store.outcomes.get(`rec-${id}`)!.memoryStatus).toBe("pending_retry"); expect(metrics).toContain("MemorySync:failed");
    expect(await code(svc.reconcileMemory(ana))).toBe("forbidden");
    memory.fail = false;
    expect(await svc.reconcileMemory(rev)).toMatchObject({ attempted: 1, synced: 1, failed: 0 });
    expect(await svc.reconcileMemory(rev)).toMatchObject({ attempted: 0 }); // nothing left; and repeating the writes would not duplicate (same tokens)
    const n = memory.events.length; await svc.syncMemory(`rec-${id}`); expect(memory.events.length).toBe(n);
  });
  it("published memory carries only the reviewed payload; a withdrawn case is blocked by the authoritative check even though the index still has it", async () => {
    const { svc, memory } = setup(); const id = await finalized(svc, ana, "share_summary");
    await svc.patchRecord(rev, `rec-${id}`, { review_status: "approved", case_card: { action: "Tanks", result: "Fewer dry days" } });
    const pub = memory.events.filter((e) => e.scope === "published"); expect(pub).toHaveLength(1);
    expect(pub[0].text).toContain("challenge: EN summary"); expect(pub[0].text).not.toContain("PRD-ANA");
    expect((await svc.publishedRecall(lucia, "EN summary")).map((c) => c.challenge)).toEqual(["EN summary"]);
    await svc.updateSharing(ana, id, { sharing: "ftusa_only", identityPermitted: false }); // withdraw; the index entry is still there
    expect(memory.events.some((e) => e.scope === "published")).toBe(true);
    expect(await svc.publishedRecall(lucia, "EN summary")).toHaveLength(0);
  });
  it("a failed published-memory write leaves the record failed, not published", async () => {
    const { svc, memory } = setup(); const id = await finalized(svc, ana, "share_summary");
    memory.fail = true;
    const r = await svc.patchRecord(rev, `rec-${id}`, { review_status: "approved" }) as { publicationStatus: string };
    expect(r.publicationStatus).toBe("failed");
  });
  it("without memory configured, everything still works and says so", async () => {
    const store = new MemoryStore(); store.orgs.set("ORG-A", org("ORG-A")); store.profiles.set("s-ana", prof("PRD-ANA", "ORG-A"));
    const svc = new ServiceV2({ store, agent: new Stub() }); const id = await finalized(svc, ana);
    expect((await svc.issueContext(ana, id)).memoryStatus).toBe("disabled");
  });
});
