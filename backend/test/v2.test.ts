// LOCAL MOCK tests (in-memory store, stub agent): V2 application logic. They do not exercise AWS, Bedrock or AgentCore.
import { describe, expect, it } from "vitest";
import type { AgentClient, AgentTurnRequest, AgentTurnResponse } from "../src/agent";
import type { Organization, ProducerProfile } from "../src/contracts";
import { route } from "../src/handler";
import { MemoryStore } from "../src/store";
import type { Principal } from "../src/service";
import { dayGroupOf, summaryHashOf } from "../src/service";
import { ServiceV2 } from "../src/serviceV2";
import type { ApiError } from "../src/errors";

class Stub implements AgentClient {
  async turn(req: AgentTurnRequest): Promise<AgentTurnResponse> {
    const playback = req.context.mode === "intake" && req.context.allowPlayback;
    return { reply: "reply", language: req.context.language, phase: req.context.mode === "guidance" ? "guidance" : playback ? "playback" : "intake",
      playbackSummary: playback ? "late rain hurt yield" : null, title: playback ? "Late rain" : null,
      summaryEn: req.context.mode === "guidance" ? "EN summary" : null, summaryOriginal: req.context.mode === "guidance" ? "ES resumen" : null,
      challengeTags: req.context.mode === "guidance" ? ["water"] : [], piiFlag: false, piiTypes: [], evidence: { status: "unavailable" } };
  }
}
const org = (id: string, name: string): Organization => ({ organizationId: id, name, info: { accountSk: `ACC-${id}-0000000001`, accountCategoryName: "Cooperative", productCategoryName: ["Coffee", "Cocoa"],
  accountTypeName: "Producer", certificationScopeName: "Farm", certificationStatusName: "Certified", countryName: "Colombia", rawSupplyChainRoleTxt: ["Grower", "Exporter"], structureTxt: null } });
const prof = (producerId: string, organizationId: string | undefined, lang: "en" | "es" | "fr" = "en", name = producerId): ProducerProfile => ({ producerId, displayName: name, entityType: "cooperative", location: "L", crop: "coffee", preferredLanguage: lang, organizationId, applicationUserId: `u-${producerId}` });
const P = (sub: string): Principal => ({ sub, groups: ["producer"] });
const ana = P("s-ana"), mateo = P("s-mateo"), lucia = P("s-lucia"), nobody = P("s-none");
const rev: Principal = { sub: "s-rev", groups: ["reviewer"], name: "Rev One" };
let n = 0; const rid = () => `req-${++n}-xxxxxxxx`;
const code = async (p: Promise<unknown>) => { try { await p; return "ok"; } catch (e) { return (e as ApiError).code ?? (e as Error).name; } };

function setup() {
  const store = new MemoryStore(); const logs: unknown[] = [];
  store.orgs.set("ORG-A", org("ORG-A", "Andean")); store.orgs.set("ORG-H", org("ORG-H", "Copan"));
  store.profiles.set("s-ana", prof("PRD-ANA", "ORG-A", "es", "Ana")); store.profiles.set("s-mateo", prof("PRD-MATEO", "ORG-A", "es", "Mateo"));
  store.profiles.set("s-lucia", prof("PRD-LUCIA", "ORG-H", "fr", "Lucia"));
  const failPublish = { on: false };
  const svc = new ServiceV2({ store, agent: new Stub(), log: (e) => logs.push(e), publishSideEffect: async () => { if (failPublish.on) throw new Error("memory_down"); } });
  return { store, svc, logs, failPublish };
}
async function finalized(svc: ServiceV2, p: Principal, sharing: "share_conversation" | "share_summary" | "ftusa_only", identity = false) {
  const id = (await svc.create(p, undefined, rid())).conversation.conversationId;
  await svc.message(p, id, rid(), "rain was late"); await svc.message(p, id, rid(), "yield dropped");
  const v = await svc.playback(p, id, { requestId: rid(), decision: "confirm" });
  await svc.finalize(p, id, { requestId: rid(), summaryHash: v.confirmation!.summaryHash, sharing, identityPermitted: identity });
  return id;
}
async function approve(svc: ServiceV2, id: string, extra: Record<string, unknown> = {}) {
  return svc.patchRecord(rev, `rec-${id}`, { review_status: "approved", ...extra } as never);
}

describe("identity and language", () => {
  it("/me returns distinct identifiers and preferred_language; a missing mapping is a configuration error, not a default producer", async () => {
    const { svc } = setup();
    const me = await svc.me(ana);
    expect(me).toMatchObject({ preferred_language: "es", identity: { producerId: "PRD-ANA", organizationId: "ORG-A", applicationUserId: "u-PRD-ANA" }, configurationError: null });
    expect(await svc.me(nobody)).toMatchObject({ configurationError: "producer_mapping_missing", profile: undefined });
    expect(await code(svc.producerInformation(nobody))).toBe("no_profile");
    expect(await svc.me(rev)).toMatchObject({ configurationError: null });
  });
  it("new conversations start in the preferred language; a temporary language does not change the profile; reopening keeps it", async () => {
    const { svc, store } = setup();
    const a = await svc.create(ana, undefined, rid()); expect(a.conversation.language).toBe("es");
    const b = await svc.create(ana, "en", rid()); expect(b.conversation.language).toBe("en");
    expect((await svc.me(ana)).preferred_language).toBe("es");
    expect((await store.getProfileBySub("s-ana"))!.preferredLanguage).toBe("es");
    expect((await svc.getConversation(ana, b.conversation.conversationId)).conversation.language).toBe("en");
  });
  it("a profile without a language falls back to English", async () => {
    const { svc, store } = setup(); store.profiles.set("s-x", { ...prof("PRD-X", "ORG-A"), preferredLanguage: undefined as never });
    expect((await svc.create(P("s-x"), undefined, rid())).conversation.language).toBe("en");
  });
});

describe("every producer belongs to an organization", () => {
  it("an account without an organization is a configuration error and cannot use producer features; there is no individual-farmer type", async () => {
    const { svc, store } = setup(); store.profiles.set("s-solo", { ...prof("PRD-SOLO", undefined) });
    expect(await svc.me(P("s-solo"))).toMatchObject({ configurationError: "organization_missing" });
    expect(await code(svc.create(P("s-solo"), undefined, rid()))).toBe("no_organization");
    expect(await code(svc.producerInformation(P("s-solo")))).toBe("no_organization");
    const { ENTITY_TYPES } = await import("../src/contracts");
    expect([...ENTITY_TYPES]).not.toContain("smallholder"); expect([...ENTITY_TYPES]).toEqual(["cooperative", "association", "estate", "processing_operation"]);
  });
});

describe("producer information and corrections", () => {
  it("separates individual from organization data, keeps multi-values and source names, reports missing values as null", async () => {
    const { svc } = setup(); const i = await svc.producerInformation(ana);
    expect(i.individual).toEqual({ producerId: "PRD-ANA", displayName: "Ana", preferredLanguage: "es" });
    expect(i.organization!.fields).toMatchObject({ product_category_name: ["Coffee", "Cocoa"], raw_supply_chain_role_txt: ["Grower", "Exporter"], structure_txt: null, country_name: "Colombia" });
    expect(i.summary).toEqual({ products: ["Coffee", "Cocoa"], country: "Colombia" });
    expect(i.correctableFields).not.toContain("account_sk");
  });
  it("a correction request leaves the source record unchanged and shows as pending, unverified, to the organization", async () => {
    const { svc, store } = setup();
    const c = await svc.createCorrection(ana, { requestId: rid(), changes: [{ field: "country_name", proposed: "Peru" }], explanation: "moved" });
    expect(c).toMatchObject({ status: "pending", changes: [{ field: "country_name", original: "Colombia", proposed: "Peru" }], explanation: "moved" });
    expect(store.orgs.get("ORG-A")!.info.countryName).toBe("Colombia");
    const mate = await svc.producerInformation(mateo);
    expect(mate.pendingCorrections).toHaveLength(1); expect(mate.pendingCorrections[0]).toMatchObject({ requestedByYou: false, explanation: null });
    expect(mate.verified).toBe(false);
    expect((await svc.producerInformation(lucia)).pendingCorrections).toHaveLength(0); // other organization sees nothing
  });
  it("is idempotent per requestId, rejects no-op changes, and a foreign request id is a conflict", async () => {
    const { svc, store } = setup(); const r = rid();
    await svc.createCorrection(ana, { requestId: r, changes: [{ field: "country_name", proposed: "Peru" }] });
    await svc.createCorrection(ana, { requestId: r, changes: [{ field: "country_name", proposed: "Peru" }] });
    expect(store.corrections.size).toBe(1);
    expect(await code(svc.createCorrection(ana, { requestId: rid(), changes: [{ field: "country_name", proposed: "Colombia" }] }))).toBe("validation_error");
  });
  it("identifiers, membership and permissions cannot be corrected: schema rejects them", async () => {
    const { svc } = setup();
    for (const field of ["account_sk", "organization_id", "role"])
      await expect(route(svc, ana, "POST", "/corrections", { requestId: rid(), changes: [{ field, proposed: "x" }] })).rejects.toThrow();
    await expect(route(svc, ana, "POST", "/corrections", { requestId: rid(), changes: [{ field: "country_name", proposed: "x" }], organizationId: "ORG-H" })).rejects.toThrow();
  });
  it("reviewer decides once: pending -> accepted_awaiting_source_update -> applied; reject is terminal; reviewer-only; attribution is server-derived", async () => {
    const { svc, store } = setup();
    const c = await svc.createCorrection(ana, { requestId: rid(), changes: [{ field: "country_name", proposed: "Peru" }] });
    expect(await code(svc.decideCorrection(ana, c.correctionId, { decision: "accept" }))).toBe("forbidden");
    expect(await code(svc.decideCorrection(rev, c.correctionId, { decision: "mark_applied" }))).toBe("already_decided"); // not yet accepted
    expect((await svc.decideCorrection(rev, c.correctionId, { decision: "accept" })).status).toBe("accepted_awaiting_source_update");
    expect((await svc.decideCorrection(rev, c.correctionId, { decision: "accept" })).status).toBe("accepted_awaiting_source_update"); // retry
    expect((await svc.producerInformation(ana)).pendingCorrections[0].status).toBe("accepted_awaiting_source_update"); // still not applied
    expect(store.orgs.get("ORG-A")!.info.countryName).toBe("Colombia");
    expect((await svc.decideCorrection(rev, c.correctionId, { decision: "mark_applied" })).status).toBe("applied");
    expect((await svc.producerInformation(ana)).pendingCorrections).toHaveLength(0);
    expect(store.corrections.get(c.correctionId)!.decidedBy).toBe("Rev One");
    const c2 = await svc.createCorrection(ana, { requestId: rid(), changes: [{ field: "structure_txt", proposed: "Federation" }] });
    await svc.decideCorrection(rev, c2.correctionId, { decision: "reject", note: "unclear" });
    expect(await code(svc.decideCorrection(rev, c2.correctionId, { decision: "accept" }))).toBe("already_decided");
  });
});

describe("finalize, sharing and review independence", () => {
  it("rejects a stale confirmation hash and finalizes exactly the confirmed summary", async () => {
    const { svc, store } = setup();
    const id = (await svc.create(ana, undefined, rid())).conversation.conversationId;
    await svc.message(ana, id, rid(), "a"); await svc.message(ana, id, rid(), "b");
    const v = await svc.playback(ana, id, { requestId: rid(), decision: "confirm" });
    expect(await code(svc.finalize(ana, id, { requestId: rid(), summaryHash: "0".repeat(64), sharing: "ftusa_only", identityPermitted: false }))).toBe("stale_confirmation");
    await svc.finalize(ana, id, { requestId: rid(), summaryHash: v.confirmation!.summaryHash, sharing: "share_summary", identityPermitted: false });
    const o = store.outcomes.get(`rec-${id}`)!;
    expect(o).toMatchObject({ reviewStatus: "pending", sharingChoice: "share_summary", publicationStatus: "awaiting_review", confirmedByProducerId: "PRD-ANA", organizationId: "ORG-A", summaryVersion: 1 });
    expect(o.confirmationHash).toBe(summaryHashOf({ summaryOriginal: "ES resumen", summaryEn: "EN summary", challengeTags: ["water"], language: "es" }));
    expect(o.ttl).toBeGreaterThan(0); // records are not retained indefinitely
  });
  it("FTUSA-only records still enter review but are never publishable", async () => {
    const { svc, store } = setup(); const id = await finalized(svc, ana, "ftusa_only");
    expect((await svc.reviewProducerRecords(rev, "PRD-ANA")).items).toHaveLength(1);
    const r = await approve(svc, id) as { publicationStatus: string };
    expect(r.publicationStatus).toBe("not_shared");
    expect(store.outcomes.get(`rec-${id}`)!.reviewStatus).toBe("approved");
    expect((await svc.peerSummaries(lucia, "all")).items).toHaveLength(0); // other organizations never see an FTUSA-only case
    const org = (await svc.peerSummaries(mateo)).items; // ...but the producer's own organization sees the summary
    expect(org).toHaveLength(1); expect(org[0]).toMatchObject({ visibility: "organization_only", sameOrganization: true });
  });
  it("identity can only be shared with the conversation choice", async () => {
    const { svc } = setup();
    await expect(route(svc, ana, "POST", "/conversations/x/finalize", { requestId: rid(), summaryHash: "a".repeat(64), sharing: "share_summary", identityPermitted: true })).rejects.toThrow();
  });
  it("retried finalize does not create a second record", async () => {
    const { svc, store } = setup();
    const id = (await svc.create(ana, undefined, rid())).conversation.conversationId;
    await svc.message(ana, id, rid(), "a"); await svc.message(ana, id, rid(), "b");
    const h = (await svc.playback(ana, id, { requestId: rid(), decision: "confirm" })).confirmation!.summaryHash; const r = rid();
    await svc.finalize(ana, id, { requestId: r, summaryHash: h, sharing: "share_summary", identityPermitted: false });
    await svc.finalize(ana, id, { requestId: r, summaryHash: h, sharing: "share_summary", identityPermitted: false });
    expect([...store.outcomes.keys()].filter((k) => k.startsWith("rec-"))).toHaveLength(1);
  });
});

describe("peer summaries", () => {
  it("organization peers see colleagues' confirmed summaries whatever the sharing choice; other organizations only see reviewed, published, shared cases", async () => {
    const { svc } = setup();
    const pending = await finalized(svc, ana, "share_summary");
    const ftusa = await finalized(svc, ana, "ftusa_only"); await approve(svc, ftusa);
    expect((await svc.peerSummaries(mateo)).items).toHaveLength(2); // pending + ftusa-only are visible inside the organization
    expect((await svc.peerSummaries(lucia, "all")).items).toHaveLength(0); // and nowhere else
    await approve(svc, pending, { case_card: { action: "Built tanks", result: null, standards: ["APS 2.1"] } });
    const items = (await svc.peerSummaries(mateo)).items.filter((i) => i.visibility === "published");
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ sameOrganization: true, origin: "your_organization", producer: null, anonymousLabel: "A producer in your organization",
      challenge: "EN summary", action: "Built tanks", result: "Outcome not yet reported", resultReported: false, standards: ["APS 2.1"] });
    expect((await svc.peerSummaries(ana)).items).toHaveLength(0); // never your own
    expect(JSON.stringify((await svc.peerSummaries(mateo)).items)).not.toContain("PRD-ANA"); expect(JSON.stringify(items)).not.toContain("rain was late"); // no ids, no transcript
  });
  it("names appear only with explicit identity permission", async () => {
    const { svc } = setup();
    const named = await finalized(svc, ana, "share_conversation", true); await approve(svc, named);
    expect((await svc.peerSummaries(mateo)).items[0].producer).toEqual({ name: "Ana" });
    await svc.updateSharing(ana, named, { sharing: "share_conversation", identityPermitted: false }); // revoke identity only
    expect((await svc.peerSummaries(mateo)).items[0].producer).toBeNull();
  });
  it("other organizations are labelled, and an unlabelled org-only wrapper does not exist: scope=organization hides them", async () => {
    const { svc } = setup(); const id = await finalized(svc, lucia, "share_summary"); await approve(svc, id);
    expect((await svc.peerSummaries(mateo, "organization")).items).toHaveLength(0);
    const all = (await svc.peerSummaries(mateo, "all")).items;
    expect(all).toHaveLength(1); expect(all[0]).toMatchObject({ sameOrganization: false, origin: "other_organization", anonymousLabel: "A producer in another organization" });
  });
  it("withdrawing sharing blocks retrieval immediately; stale versions and withdrawn cases are rejected", async () => {
    const { svc } = setup(); const id = await finalized(svc, ana, "share_summary"); await approve(svc, id);
    const c = (await svc.peerSummaries(lucia, "all")).items[0]; // another organization: strict rules
    expect((await svc.peerCase(lucia, c.caseId)).challenge).toBe("EN summary");
    expect(await code(svc.peerCase(lucia, c.caseId.replace(/@\d+$/, "@9")))).toBe("case_unavailable"); // stale / wrong version
    await svc.updateSharing(ana, id, { sharing: "ftusa_only", identityPermitted: false });
    expect(await code(svc.peerCase(lucia, c.caseId))).toBe("case_unavailable");
    expect((await svc.peerSummaries(lucia, "all")).items).toHaveLength(0);
    expect(await code(svc.create(lucia, undefined, rid(), c.caseId))).toBe("case_unavailable");
    expect((await svc.peerSummaries(mateo)).items).toHaveLength(1); // the organization still sees the summary
  });
  it("'Ask about this' validates the case server-side and stores the reference on the viewer's own conversation", async () => {
    const { svc } = setup(); const id = await finalized(svc, ana, "share_summary"); await approve(svc, id);
    const c = (await svc.peerSummaries(mateo)).items[0];
    const v = await svc.create(mateo, undefined, rid(), c.caseId);
    expect(v.referencedCase).toEqual({ caseId: c.caseId, version: c.version });
    expect(await code(svc.getConversation(ana, v.conversation.conversationId))).toBe("not_found"); // owned by Mateo only
    expect(v.referencedCaseCard).toMatchObject({ caseId: c.caseId, challenge: "EN summary" }); // the chat shows what it is about
    expect(await code(svc.create(mateo, undefined, rid(), "rec-forged-123456@1"))).toBe("case_unavailable");
  });
  it("deletion request withdraws publication at once and is idempotent", async () => {
    const { svc } = setup(); const id = await finalized(svc, ana, "share_summary"); await approve(svc, id);
    const r = await svc.requestDeletion(ana, id);
    expect(r).toMatchObject({ deletionRequested: true, publicationStatus: "withdrawn", sharingChoice: "ftusa_only" });
    expect((await svc.peerSummaries(mateo, "all")).items).toHaveLength(0);
    expect((await svc.requestDeletion(ana, id)).deletionRequested).toBe(true);
    expect(await code(svc.updateSharing(ana, id, { sharing: "share_summary", identityPermitted: false }))).toBe("deletion_requested");
    expect(await code(svc.requestDeletion(mateo, id))).toBe("not_found"); // not the owner
  });
});

describe("summary versions, re-confirmation and publication", () => {
  it("a material reviewer change is not published until the producer re-confirms; the confirmed version is kept", async () => {
    const { svc, store } = setup(); const id = await finalized(svc, ana, "share_summary");
    const r = await svc.patchRecord(rev, `rec-${id}`, { review_status: "corrected", summary_en: "Edited EN summary" }) as { publicationStatus: string; summaryVersions: { kind: string }[] };
    expect(r.publicationStatus).toBe("awaiting_reconfirmation");
    expect(r.summaryVersions.map((v) => v.kind)).toEqual(["producer_confirmed", "reviewer_revision"]);
    expect((await svc.peerSummaries(lucia, "all")).items).toHaveLength(0);
    expect((await svc.peerSummaries(mateo)).items[0].challenge).toBe("EN summary"); // colleagues see the producer-confirmed text, not the unconfirmed edit
    const st = (await svc.getConversation(ana, id)).record!;
    expect(st.reconfirmation).toMatchObject({ summaryEn: "Edited EN summary" });
    expect(await code(svc.reconfirm(ana, id, { summaryHash: "f".repeat(64), accept: true }))).toBe("stale_confirmation");
    const out = await svc.reconfirm(ana, id, { summaryHash: st.reconfirmation!.summaryHash, accept: true });
    expect(out.publicationStatus).toBe("published");
    expect((await svc.peerSummaries(lucia, "all")).items[0].challenge).toBe("Edited EN summary");
    expect(store.outcomes.get(`rec-${id}`)!.versions!.map((v) => v.kind)).toEqual(["producer_confirmed", "reviewer_revision", "producer_confirmed"]);
  });
  it("declining the revision publishes the original confirmed content", async () => {
    const { svc } = setup(); const id = await finalized(svc, ana, "share_summary");
    await svc.patchRecord(rev, `rec-${id}`, { review_status: "corrected", summary_en: "Edited EN summary" });
    const h = (await svc.getConversation(ana, id)).record!.reconfirmation!.summaryHash;
    expect((await svc.reconfirm(ana, id, { summaryHash: h, accept: false })).publicationStatus).toBe("published");
    expect((await svc.peerSummaries(mateo)).items[0].challenge).toBe("EN summary");
  });
  it("tag-only corrections need no re-confirmation", async () => {
    const { svc } = setup(); const id = await finalized(svc, ana, "share_summary");
    const r = await svc.patchRecord(rev, `rec-${id}`, { review_status: "corrected", challenge_tags: ["water", "climate_weather"] }) as { publicationStatus: string };
    expect(r.publicationStatus).toBe("published");
  });
  it("a failed publication is visible as failed (not published), invisible to peers, and a retry publishes exactly once", async () => {
    const { svc, store, failPublish } = setup(); const id = await finalized(svc, ana, "share_summary");
    failPublish.on = true;
    const r = await approve(svc, id) as { publicationStatus: string; publishError: string };
    expect(r).toMatchObject({ publicationStatus: "failed", publishError: "Error" });
    expect((await svc.peerSummaries(lucia, "all")).items).toHaveLength(0);
    failPublish.on = false;
    const ok = await svc.retryPublication(rev, `rec-${id}`) as { publicationStatus: string; publishedVersion: number };
    expect(ok).toMatchObject({ publicationStatus: "published", publishedVersion: 1 });
    expect((await svc.retryPublication(rev, `rec-${id}`) as { publishedVersion: number }).publishedVersion).toBe(1); // idempotent
    expect(store.outcomes.get(`rec-${id}`)!.publication!.version).toBe(1);
  });
  it("approving again with the same reviewer is a safe retry; a different reviewer conflicts", async () => {
    const { svc } = setup(); const id = await finalized(svc, ana, "share_summary"); await approve(svc, id);
    await approve(svc, id);
    expect(await code(svc.patchRecord({ ...rev, sub: "other" }, `rec-${id}`, { review_status: "approved" }))).toBe("already_reviewed");
  });
  it("producers cannot read reviewer views or publish", async () => {
    const { svc } = setup(); const id = await finalized(svc, ana, "share_summary");
    expect(await code(svc.retryPublication(ana, `rec-${id}`))).toBe("forbidden");
    expect(await code(route(svc, ana, "PATCH", `/records/rec-${id}`, { review_status: "approved" }))).toBe("forbidden");
    expect(await code(route(svc, ana, "GET", "/review/corrections", undefined))).toBe("forbidden");
  });
});

describe("related cases", () => {
  it("only comparable cases: same crop and a shared challenge tag; ranked with reasons; unrelated crops never appear", async () => {
    const { svc, store } = setup();
    store.profiles.set("s-cocoa", { ...prof("PRD-COCOA", "ORG-H", "en", "Cocoa"), crop: "cocoa" });
    const mine = await finalized(svc, ana, "share_summary");               // coffee, tag water
    const coffeePeer = await finalized(svc, lucia, "share_summary"); await approve(svc, coffeePeer, { case_card: { result: "Fewer lost days" } });
    const cocoa = await finalized(svc, P("s-cocoa"), "share_summary"); await approve(svc, cocoa);
    const r = await svc.relatedCases(ana, mine);
    expect(r.items.map((i) => i.caseId)).toEqual([`rec-${coffeePeer}@1`]);
    expect(r.items[0].relevance).toEqual(expect.arrayContaining(["Same crop: coffee", "Same challenge: water"]));
    const none = await svc.relatedCases(P("s-cocoa"), cocoa); // cocoa grower: coffee cases are not comparable
    expect(none.items).toHaveLength(0); expect(none.limitation).toContain("cocoa");
    expect(await code(svc.relatedCases(mateo, mine))).toBe("not_found"); // not the owner
  });
});

describe("agent matching", () => {
  async function world(matchImpl: (req: import("../src/agent").MatchRequest) => Promise<import("../src/agent").MatchResponse>) {
    const store = new MemoryStore(); const calls: import("../src/agent").MatchRequest[] = [];
    store.orgs.set("ORG-A", org("ORG-A", "Andean")); store.orgs.set("ORG-H", org("ORG-H", "Copan"));
    store.profiles.set("s-ana", prof("PRD-ANA", "ORG-A", "en", "Ana")); store.profiles.set("s-lucia", prof("PRD-LUCIA", "ORG-H", "en", "Lucia"));
    store.profiles.set("s-coco", { ...prof("PRD-COCO", "ORG-H", "en", "Coco"), crop: "cocoa" });
    const stub = new Stub(); (stub as unknown as { match: unknown }).match = async (req: import("../src/agent").MatchRequest) => { calls.push(req); return matchImpl(req); };
    const svc = new ServiceV2({ store, agent: stub });
    const mine = await finalized(svc, ana, "share_summary");
    const a = await finalized(svc, lucia, "share_summary"); await approve(svc, a, { case_card: { action: "Tanks", result: "Fewer dry days" } });
    const b = await finalized(svc, lucia, "share_summary"); await approve(svc, b);
    const c = await finalized(svc, P("s-coco"), "share_summary"); await approve(svc, c);
    return { svc, calls, mine, a, b, c };
  }
  it("sends the agent only authorized, same-crop candidates and returns only what it picked, with its reason and fit", async () => {
    const w = await world(async (req) => ({ matches: [{ caseId: req.candidates[0].caseId, fit: "strong", reason: "Same dry-spell problem" }], considered: req.candidates.length }));
    const r = await w.svc.relatedCases(ana, w.mine);
    expect(w.calls[0].candidates).toHaveLength(2); // two coffee cases; the cocoa case never reaches the model
    expect(JSON.stringify(w.calls[0].candidates)).not.toContain("PRD-"); expect(JSON.stringify(w.calls[0])).not.toContain("rain was late"); // no ids, no transcripts
    expect(r.matchedBy).toBe("agent"); expect(r.items).toHaveLength(1);
    expect(r.items[0]).toMatchObject({ fit: "strong", reason: "Same dry-spell problem" });
  });
  it("drops case ids the model invents or repeats and may return no match at all", async () => {
    const w = await world(async (req) => ({ matches: [{ caseId: "rec-invented-0001@1", fit: "strong", reason: "x" }, { caseId: req.candidates[1].caseId, fit: "partial", reason: "y" }, { caseId: req.candidates[1].caseId, fit: "strong", reason: "dup" }], considered: 2 }));
    expect((await w.svc.relatedCases(ana, w.mine)).items.map((i) => i.reason)).toEqual(["y"]);
    const none = await world(async () => ({ matches: [], considered: 2 }));
    const r = await none.svc.relatedCases(ana, none.mine);
    expect(r.items).toHaveLength(0); expect(r.limitation).toContain("No close match");
  });
  it("falls back to rule-based ranking when the agent fails, and says so", async () => {
    const w = await world(async () => { throw new Error("down"); });
    const r = await w.svc.relatedCases(ana, w.mine);
    expect(r.matchedBy).toBe("rules"); expect(r.items.length).toBeGreaterThan(0); expect(r.items.every((i) => i.reason === null)).toBe(true);
  });
  it("does not call the agent when there is nothing comparable", async () => {
    const w = await world(async () => ({ matches: [], considered: 0 }));
    const lone = await w.svc.relatedCases(P("s-coco"), `${w.c}`); // cocoa grower: no cocoa peers
    expect(lone.items).toHaveLength(0); expect(w.calls.filter((c) => c.producer.crop === "cocoa")).toHaveLength(0);
  });
});

describe("feedback", () => {
  it("owner records helpfulness (replaceable); reviewers see it; others cannot", async () => {
    const { svc } = setup(); const id = await finalized(svc, ana, "ftusa_only");
    await svc.feedback(ana, id, { helpful: "partly", comment: "ok" }); await svc.feedback(ana, id, { helpful: "yes" });
    expect(await svc.getRecord(rev, `rec-${id}`)).toMatchObject({ feedbackHelpful: "yes" });
    expect(await code(svc.feedback(mateo, id, { helpful: "no" }))).toBe("not_found");
  });
});

describe("guidance turn without summary fields", () => {
  it("English conversations fall back to the confirmed account; other languages stay at guidance (retry), never an invented translation", async () => {
    const store = new MemoryStore(); store.profiles.set("s-en", prof("PRD-EN", "ORG-A", "en")); store.profiles.set("s-es", prof("PRD-ES", "ORG-A", "es"));
    const bare = new Stub(); const orig = bare.turn.bind(bare);
    bare.turn = async (req) => { const r = await orig(req); return req.context.mode === "guidance" ? { ...r, summaryEn: null, summaryOriginal: null, reply: "Another question?" } : r; };
    const svc = new ServiceV2({ store, agent: bare });
    for (const [p, expected] of [[P("s-en"), "consent_pending"], [P("s-es"), "guidance_pending"]] as const) {
      const id = (await svc.create(p, undefined, rid())).conversation.conversationId;
      await svc.message(p, id, rid(), "a"); await svc.message(p, id, rid(), "b");
      expect((await svc.playback(p, id, { requestId: rid(), decision: "confirm" })).conversation.workflow).toBe(expected);
    }
  });
});

describe("conversation language", () => {
  it("switching language mid-conversation changes later agent replies for that conversation only, never the profile; closed conversations refuse", async () => {
    const store = new MemoryStore(); store.orgs.set("ORG-A", org("ORG-A", "A")); store.profiles.set("s-ana", prof("PRD-ANA", "ORG-A", "es", "Ana"));
    const langs: string[] = []; const agent = new Stub(); const orig = agent.turn.bind(agent);
    agent.turn = async (req) => { langs.push(req.context.language); return orig(req); };
    const svc = new ServiceV2({ store, agent });
    const id = (await svc.create(ana, undefined, rid())).conversation.conversationId;
    await svc.message(ana, id, rid(), "hola");
    const r = rid(); const v = await svc.setConversationLanguage(ana, id, r, "fr");
    expect(v.conversation.language).toBe("fr"); expect((await svc.setConversationLanguage(ana, id, r, "fr")).conversation.language).toBe("fr"); // retry safe
    await svc.message(ana, id, rid(), "bonjour");
    expect(langs.slice(0, 2)).toEqual(["es", "es"]); expect(langs.at(-1)).toBe("fr");
    expect((await store.getProfileBySub("s-ana"))!.preferredLanguage).toBe("es");
    expect(await code(svc.setConversationLanguage(mateo, id, rid(), "en"))).toBe("not_found");
    await svc.end(ana, id, rid()); expect(await code(svc.setConversationLanguage(ana, id, rid(), "en"))).toBe("conversation_closed");
    await expect(route(svc, ana, "POST", `/conversations/${id}/language`, { requestId: rid(), language: "de" })).rejects.toThrow();
  });
});

describe("playback is forced after enough turns", () => {
  it("the agent is told to play back from the 4th producer message, never earlier", async () => {
    const store = new MemoryStore(); store.orgs.set("ORG-A", org("ORG-A", "A")); store.profiles.set("s-ana", prof("PRD-ANA", "ORG-A", "en", "Ana"));
    const seen: boolean[] = []; const agent = new Stub(); const orig = agent.turn.bind(agent);
    agent.turn = async (req) => { seen.push(!!(req.context as { forcePlayback?: boolean }).forcePlayback); const r = await orig(req); return req.context.allowPlayback ? { ...r, phase: "intake" as const, playbackSummary: null } : r; };
    const svc = new ServiceV2({ store, agent });
    const id = (await svc.create(ana, undefined, rid())).conversation.conversationId;
    for (const t of ["a", "b", "c", "d"]) await svc.message(ana, id, rid(), t);
    expect(seen.slice(1)).toEqual([false, false, false, true]); // messages 1-3 never forced (playback allowed from 2); message 4 must
  });
});

describe("history grouping", () => {
  it("groups by Today / Previous 7 days / Older", () => {
    const now = Date.parse("2026-11-04T15:00:00Z");
    expect(dayGroupOf("2026-11-04T01:00:00Z", now)).toBe("today");
    expect(dayGroupOf("2026-11-01T01:00:00Z", now)).toBe("previous_7_days");
    expect(dayGroupOf("2026-10-01T01:00:00Z", now)).toBe("older");
  });
  it("personal transcripts are not exposed to organization peers", async () => {
    const { svc } = setup(); const id = await finalized(svc, ana, "share_conversation", true); await approve(svc, id);
    expect(await code(svc.getConversation(mateo, id))).toBe("not_found");
    expect((await svc.listConversations(mateo)).items).toHaveLength(0);
  });
});
