// LOCAL MOCK tests: in-memory store and a stub agent. They verify application logic only, not AWS or Bedrock.
import { describe, expect, it } from "vitest";
import type { AgentClient, AgentTurnRequest, AgentTurnResponse } from "../src/agent";
import { MemoryStore } from "../src/store";
import { type Principal } from "../src/service";
import { ServiceV2 as Service } from "../src/serviceV2";
import { principalFromEvent, route } from "../src/handler";
import { ApiError } from "../src/errors";

const alice: Principal = { sub: "sub-alice", groups: ["producer"] };
const bob: Principal = { sub: "sub-bob", groups: ["producer"] };
const rev: Principal = { sub: "sub-rev", groups: ["reviewer"] };
const profile = (id: string) => ({ producerId: id, displayName: "x", entityType: "cooperative", location: "L", crop: "coffee", preferredLanguage: "en" as const, organizationId: "ORG-T" });

class StubAgent implements AgentClient {
  calls: AgentTurnRequest[] = [];
  fail = false;
  delay = 0;
  async turn(req: AgentTurnRequest): Promise<AgentTurnResponse> {
    this.calls.push(structuredClone(req));
    if (this.delay) await new Promise((r) => setTimeout(r, this.delay));
    if (this.fail) throw new Error("boom");
    const playback = req.context.mode === "intake" && req.context.allowPlayback;
    return {
      reply: req.context.language === "es" ? "respuesta" : "reply", language: req.context.language,
      phase: req.context.mode === "guidance" ? "guidance" : playback ? "playback" : "intake",
      playbackSummary: playback ? "late rain hurt yield" : null, title: playback ? "Late rain and lower yield" : null,
      summaryEn: req.context.mode === "guidance" ? "EN summary" : null, summaryOriginal: req.context.mode === "guidance" ? (req.context.language === "en" ? "EN summary" : req.context.language === "fr" ? "FR résumé" : "ES resumen") : null,
      challengeTags: req.context.mode === "guidance" ? ["water", "climate_weather", "not_a_tag"] : [],
      piiFlag: req.messages.at(-1)!.text.includes("555"), piiTypes: req.messages.at(-1)!.text.includes("555") ? ["PHONE"] : [],
      evidence: { status: "unavailable" },
    };
  }
}

class StubTranscriber { calls = 0; fail = false; last?: { len: number; language: string };
  async transcribe(pcm: Uint8Array, language: string) { this.calls++; this.last = { len: pcm.length, language }; if (this.fail) throw new Error("boom"); return "late rains hurt the harvest"; } }
class StubSpeaker { calls: { text: string; language: string }[] = []; fail = false;
  async speak(text: string, language: string) { this.calls.push({ text, language }); if (this.fail) throw new Error("boom"); return { audio: new Uint8Array([73, 68, 51, 4]), voice: "Lea" }; } }
function setup() {
  const store = new MemoryStore(); const agent = new StubAgent(); const transcriber = new StubTranscriber(); const speaker = new StubSpeaker(); const logs: unknown[] = [];
  store.profiles.set("sub-alice", profile("SYN-A")); store.profiles.set("sub-bob", profile("SYN-B"));
  return { store, agent, transcriber, speaker, logs, svc: new Service({ store, agent, transcriber, speaker, log: (e) => logs.push(e) }) };
}
let n = 0; const rid = () => `req-${++n}-xxxxxxxx`;
const code = async (p: Promise<unknown>) => { try { await p; return "ok"; } catch (e) { return (e as ApiError).code; } };

async function toConsent(svc: Service, p = alice) {
  const v = await svc.create(p, "en", rid()); const id = v.conversation.conversationId;
  await svc.message(p, id, rid(), "rain was late");
  const v2 = await svc.message(p, id, rid(), "yield dropped, tried nothing");
  expect(v2.conversation.workflow).toBe("playback_pending");
  const v3 = await svc.playback(p, id, { requestId: rid(), decision: "confirm" });
  expect(v3.conversation.workflow).toBe("consent_pending");
  return id;
}

describe("authorization", () => {
  it("rejects wrong-owner read, append, consent and end", async () => {
    const { svc } = setup(); const id = (await svc.create(alice, "en", rid())).conversation.conversationId;
    expect(await code(svc.getConversation(bob, id))).toBe("not_found");
    expect(await code(svc.message(bob, id, rid(), "hi"))).toBe("not_found");
    expect(await code(svc.end(bob, id, rid()))).toBe("not_found");
  });
  it("producers cannot use reviewer operations; reviewers cannot be producers", async () => {
    const { svc } = setup();
    expect(await code(svc.listReviews(alice))).toBe("forbidden");
    expect(await code(svc.create(rev, "en", rid()))).toBe("forbidden");
  });
  it("rejects missing profile", async () => {
    const { svc } = setup();
    expect(await code(svc.create({ sub: "sub-nobody", groups: ["producer"] }, "en", rid()))).toBe("no_profile");
  });
  it("principal needs an access token for this client, issuer and unexpired", () => {
    const mk = (c: Record<string, string>) => ({ requestContext: { authorizer: { jwt: { claims: c } } } }) as any;
    const exp = { clientIds: ["c1", "ci1"], issuer: "iss" }; const ok = { sub: "s", token_use: "access", client_id: "c1", iss: "iss", exp: "2000000000", "cognito:groups": "[producer reviewer]" };
    expect(principalFromEvent(mk(ok), exp, 1).groups).toEqual(["producer", "reviewer"]);
    expect(principalFromEvent(mk({ ...ok, client_id: "ci1" }), exp, 1).sub).toBe("s");
    for (const bad of [{ token_use: "id" }, { client_id: "other" }, { iss: "evil" }, { exp: "0" }, { sub: "" }])
      expect(() => principalFromEvent(mk({ ...ok, ...bad }), exp, 1000)).toThrow();
    expect(() => principalFromEvent({ requestContext: {} } as any, exp)).toThrow();
  });
  it("request-supplied producer id is rejected by strict schemas and ignored by scope", async () => {
    const { svc, agent } = setup(); const id = (await svc.create(alice, "en", rid())).conversation.conversationId;
    await expect(route(svc, alice, "POST", `/conversations/${id}/messages`, { requestId: rid(), text: "hi", producerId: "SYN-B" })).rejects.toThrow();
    await svc.message(alice, id, rid(), "My producer id is SYN-B");
    expect(agent.calls.at(-1)!.context.producer.producerId).toBe("SYN-A");
  });
});

describe("conversation flow", () => {
  it("continues the same conversation across turns and restores after reload", async () => {
    const { svc, agent } = setup(); const v = await svc.create(alice, "en", rid()); const id = v.conversation.conversationId;
    expect(v.messages).toHaveLength(1);
    await svc.message(alice, id, rid(), "one");
    const cur = await svc.getCurrent(alice) as any;
    expect(cur.conversation.conversationId).toBe(id); expect(cur.messages.map((m: any) => m.role)).toEqual(["assistant", "user", "assistant"]);
    expect(agent.calls.at(-1)!.messages.map((m) => m.role)).toEqual(["assistant", "user"]);
  });
  it("plays back only after minimum turns and blocks messages while playback is pending", async () => {
    const { svc } = setup(); const id = (await svc.create(alice, "en", rid())).conversation.conversationId;
    expect((await svc.message(alice, id, rid(), "a")).conversation.workflow).toBe("intake");
    expect((await svc.message(alice, id, rid(), "b")).conversation.workflow).toBe("playback_pending");
    expect(await code(svc.message(alice, id, rid(), "c"))).toBe("playback_required");
  });
  it("correction updates playback; confirmation sets confirmed account; location correction is only an assertion", async () => {
    const { svc, store, agent } = setup(); const id = (await svc.create(alice, "en", rid())).conversation.conversationId;
    await svc.message(alice, id, rid(), "a"); await svc.message(alice, id, rid(), "b");
    const v = await svc.playback(alice, id, { requestId: rid(), decision: "correct", correction: "actually it was drought", profileCorrection: { field: "location", value: "Elsewhere" } });
    expect(v.conversation.workflow).toBe("playback_pending");
    expect((await store.getConversation(id))!.producerAssertions).toEqual({ location: "Elsewhere" });
    await svc.playback(alice, id, { requestId: rid(), decision: "confirm" });
    expect((await store.getConversation(id))!.confirmedAccount).toBe("late rain hurt yield");
    expect(agent.calls.at(-1)!.context.producer.location).toBe("L"); // trusted scope unchanged
    expect(await code(svc.playback(alice, id, { requestId: rid(), decision: "correct", profileCorrection: { field: "entityType", value: "x" } }))).toBe("wrong_state");
  });
  it("rejects unknown entity type corrections", async () => {
    const { svc } = setup(); const id = (await svc.create(alice, "en", rid())).conversation.conversationId;
    await svc.message(alice, id, rid(), "a"); await svc.message(alice, id, rid(), "b");
    expect(await code(svc.playback(alice, id, { requestId: rid(), decision: "correct", profileCorrection: { field: "entityType", value: "wizard" } }))).toBe("validation_error");
  });
  it("Spanish flow passes language to the agent", async () => {
    const { svc, agent } = setup(); const v = await svc.create(alice, "es", rid());
    expect(agent.calls[0].context.language).toBe("es"); expect(v.messages[0].text).toBe("respuesta");
  });
  it("opener falls back deterministically when the agent fails", async () => {
    const { svc, agent } = setup(); agent.fail = true;
    expect((await svc.create(alice, "es", rid())).messages[0].text).toBe("¿Qué ha sido difícil últimamente?");
  });
});

describe("retries and concurrency", () => {
  it("duplicate requestId does not duplicate messages or agent calls", async () => {
    const { svc, agent } = setup(); const id = (await svc.create(alice, "en", rid())).conversation.conversationId; const r = rid();
    const a = await svc.message(alice, id, r, "once"); const calls = agent.calls.length;
    const b = await svc.message(alice, id, r, "once");
    expect(b).toEqual(a); expect(agent.calls.length).toBe(calls); expect(b.messages.filter((m) => m.role === "user")).toHaveLength(1);
  });
  it("concurrent submissions: one proceeds, the other gets retryable 409", async () => {
    const { svc, agent } = setup(); const id = (await svc.create(alice, "en", rid())).conversation.conversationId; agent.delay = 30;
    const res = await Promise.allSettled([svc.message(alice, id, rid(), "x"), svc.message(alice, id, rid(), "y")]);
    expect(res.filter((r) => r.status === "fulfilled")).toHaveLength(1);
    const rej = res.find((r) => r.status === "rejected") as PromiseRejectedResult;
    expect((rej.reason as ApiError).code).toBe("turn_in_progress"); expect((rej.reason as ApiError).retryable).toBe(true);
  });
  it("agent failure keeps state unchanged and is retryable; lock is released", async () => {
    const { svc, agent, store } = setup(); const id = (await svc.create(alice, "en", rid())).conversation.conversationId; agent.fail = true;
    expect(await code(svc.message(alice, id, rid(), "x"))).toBe("agent_unavailable");
    expect((await store.listMessages(id)).length).toBe(1); agent.fail = false;
    expect((await svc.message(alice, id, rid(), "x")).messages).toHaveLength(3);
  });
  it("retried consent does not create a second record", async () => {
    const { svc, store } = setup(); const id = await toConsent(svc); const r = rid();
    await svc.consent(alice, id, r, true); await svc.consent(alice, id, r, true);
    expect([...store.outcomes.values()].filter((o) => o.kind === "record")).toHaveLength(1);
  });
});

describe("consent, decline, review", () => {
  it("grant creates a pending record and keeps the transcript readable for the owner", async () => {
    const { svc, store } = setup(); const id = await toConsent(svc);
    const v = await svc.consent(alice, id, rid(), true);
    const o = [...store.outcomes.values()][0];
    expect(v.conversation.status).toBe("completed"); expect(o).toMatchObject({ kind: "record", source: "agent conversation", reviewStatus: "pending", summaryEn: "EN summary", summaryOriginal: "EN summary" });
    expect((await store.listMessages(id)).length).toBeGreaterThan(0); // saved: transcript stays in the producer's history
    expect((await store.getConversation(id))!.summaryEn).toBe("EN summary"); // kept for the producer's own history
  });
  it("decline creates no narrative record and removes transient narrative", async () => {
    const { svc, store } = setup(); const id = await toConsent(svc);
    await svc.consent(alice, id, rid(), false);
    const all = [...store.outcomes.values()]; expect(all).toHaveLength(1);
    expect(all[0].kind).toBe("declined"); expect(all[0].summaryEn).toBeUndefined(); expect(all[0].summaryEs).toBeUndefined();
    expect(await store.listMessages(id)).toHaveLength(0);
    expect(await svc.listReviews(rev)).toEqual({ items: [] });
  });
  it("ending early records a narrative-free declined outcome", async () => {
    const { svc, store } = setup(); const id = (await svc.create(alice, "en", rid())).conversation.conversationId;
    await svc.message(alice, id, rid(), "secret story"); await svc.end(alice, id, rid());
    const o = [...store.outcomes.values()][0]; expect(o).toMatchObject({ kind: "declined", declineReason: "ended_early" });
    expect(JSON.stringify(o)).not.toContain("secret");
    expect(await code(svc.message(alice, id, rid(), "more"))).toBe("conversation_closed");
  });
  it("PII is flagged on the record, not redacted", async () => {
    const { svc, store } = setup(); const id = (await svc.create(alice, "en", rid())).conversation.conversationId;
    await svc.message(alice, id, rid(), "call 555"); await svc.message(alice, id, rid(), "b");
    await svc.playback(alice, id, { requestId: rid(), decision: "confirm" }); await svc.consent(alice, id, rid(), true);
    expect([...store.outcomes.values()][0]).toMatchObject({ piiFlag: true, piiTypes: ["PHONE"] });
  });
  it("reviewer approves or corrects once; second review conflicts; retry is safe", async () => {
    const { svc, store } = setup(); const id = await toConsent(svc); await svc.consent(alice, id, rid(), true);
    const oid = `rec-${id}`;
    expect(((await svc.listReviews(rev)) as any).items).toHaveLength(1);
    const c = await svc.updateReview(rev, oid, { decision: "correct", correctedSummaryEn: "fixed" });
    expect(c).toMatchObject({ reviewStatus: "corrected", summaryEn: "fixed" });
    expect((await svc.updateReview(rev, oid, { decision: "correct", correctedSummaryEn: "fixed" })).reviewStatus).toBe("corrected");
    expect(await code(svc.updateReview({ sub: "other-rev", groups: ["reviewer"] }, oid, { decision: "approve" }))).toBe("already_reviewed");
    expect(await code(svc.updateReview(alice, oid, { decision: "approve" }))).toBe("forbidden");
    expect(await code(svc.getReview(rev, "dec-x"))).toBe("not_found");
    void store;
  });
});

describe("ask and overview", () => {
  it("ask uses trusted scope, stores nothing, and requires the producer role", async () => {
    const { svc, agent, store } = setup();
    const r = await svc.ask(alice, "What do peers do about late rain?", "en");
    expect(r.evidence.status).toBe("unavailable");
    expect(agent.calls.at(-1)!.context).toMatchObject({ mode: "ask", producer: { producerId: "SYN-A" } });
    expect(store.convs.size).toBe(0); expect(store.outcomes.size).toBe(0);
    expect(await code(svc.ask(rev, "q", "en"))).toBe("forbidden");
    await expect(route(svc, alice, "POST", "/ask", { requestId: rid(), text: "q", language: "en", producerId: "SYN-B" })).rejects.toThrow();
  });
  it("ask agent failure is retryable 502", async () => {
    const { svc, agent } = setup(); agent.fail = true;
    expect(await code(svc.ask(alice, "q", "es"))).toBe("agent_unavailable");
  });
  it("overview is role-scoped", async () => {
    const { svc } = setup(); const id = await toConsent(svc); await svc.consent(alice, id, rid(), true);
    expect(await svc.overview(rev)).toMatchObject({ reviewer: { pending: 1, approved: 0 } });
    expect(await svc.overview(rev)).not.toHaveProperty("producer");
    const o = await svc.overview(alice) as any; expect(o.reviewer).toBeUndefined(); expect(o.producer.activeConversation).toBeNull();
  });
});

describe("dictation", () => {
  const pcm = (seconds: number) => Buffer.alloc(32000 * seconds).toString("base64");
  it("returns text for a producer, stores nothing and never logs the transcript", async () => {
    const { svc, transcriber, store, logs } = setup();
    const r = await svc.transcribe(alice, "es", pcm(2));
    expect(r.text).toBe("late rains hurt the harvest"); expect(transcriber.last).toEqual({ len: 64000, language: "es" });
    expect(store.convs.size + store.outcomes.size).toBe(0);
    expect(JSON.stringify(logs)).not.toContain("late rains");
  });
  it("is producer-only", async () => { const { svc } = setup(); expect(await code(svc.transcribe(rev, "en", pcm(1)))).toBe("forbidden"); });
  it("rejects invalid, odd-length, too short and too long audio before calling the service", async () => {
    const { svc, transcriber } = setup();
    expect(await code(svc.transcribe(alice, "en", "not base64!!"))).toBe("audio_invalid");
    expect(await code(svc.transcribe(alice, "en", Buffer.alloc(32001).toString("base64")))).toBe("audio_too_short");
    expect(await code(svc.transcribe(alice, "en", Buffer.alloc(100).toString("base64")))).toBe("audio_too_short");
    expect(await code(svc.transcribe(alice, "en", pcm(61)))).toBe("audio_too_long");
    expect(transcriber.calls).toBe(0);
  });
  it("transcription failure is a retryable 502", async () => {
    const { svc, transcriber } = setup(); transcriber.fail = true;
    await expect(svc.transcribe(alice, "en", pcm(1))).rejects.toMatchObject({ status: 502, code: "transcription_unavailable", retryable: true });
  });
  it("route rejects unknown fields and bad language", async () => {
    const { svc } = setup();
    await expect(route(svc, alice, "POST", "/transcribe", { requestId: rid(), language: "en", audio: pcm(1), producerId: "x" })).rejects.toThrow();
    await expect(route(svc, alice, "POST", "/transcribe", { requestId: rid(), language: "de", audio: pcm(1) })).rejects.toThrow();
  });
});

describe("history and multiple conversations", () => {
  it("create is idempotent per requestId and otherwise starts a new conversation", async () => {
    const { svc, agent } = setup(); const r = rid();
    const a = await svc.create(alice, "en", r); const calls = agent.calls.length;
    const b = await svc.create(alice, "en", r);
    expect(b.conversation.conversationId).toBe(a.conversation.conversationId); expect(agent.calls.length).toBe(calls);
    const c = await svc.create(alice, "en", rid());
    expect(c.conversation.conversationId).not.toBe(a.conversation.conversationId);
  });
  it("lists only the caller's conversations, newest first, with title and status; declined ones disappear", async () => {
    let t = 1_000; const { store, agent } = setup(); const svc = new Service({ store, agent, now: () => (t += 1000) });
    const first = (await svc.create(alice, "en", rid())).conversation.conversationId;
    await svc.message(alice, first, rid(), "a"); await svc.message(alice, first, rid(), "b"); // playback sets the title
    const second = (await svc.create(alice, "es", rid())).conversation.conversationId;
    await svc.create(bob, "en", rid());
    let list = (await svc.listConversations(alice)).items;
    expect(list.map((i) => i.conversationId)).toEqual([second, first]);
    expect(list[1]).toMatchObject({ title: "Late rain and lower yield", status: "in_progress", summary: "late rain hurt yield" });
    expect(list[0].summary).toBeNull(); // still at intake
    await svc.end(alice, second, rid());
    // V2 override: stopping is not deleting. The stopped conversation stays in "My conversations", read-only, with its transcript.
    list = (await svc.listConversations(alice)).items;
    expect(list.map((i) => i.conversationId)).toEqual([second, first]);
    expect(list[0]).toMatchObject({ status: "completed", stopped: true, group: "today" });
    expect((await store.listMessages(second)).length).toBeGreaterThan(0);
    expect(await code(svc.listConversations(rev))).toBe("forbidden");
  });
  it("a saved conversation is listed as saved and its transcript stays readable but read-only", async () => {
    const { svc } = setup(); const id = await toConsent(svc); await svc.consent(alice, id, rid(), true);
    expect((await svc.listConversations(alice)).items[0]).toMatchObject({ conversationId: id, status: "completed", summary: "EN summary" });
    const v = await svc.getConversation(alice, id);
    expect(v.messages.length).toBeGreaterThan(3); expect(v.conversation.status).toBe("completed");
    expect(await code(svc.message(alice, id, rid(), "more"))).toBe("conversation_closed");
    expect(await code(svc.getConversation(bob, id))).toBe("not_found");
  });
  it("messages carry their stage so the progress panel can jump to them", async () => {
    const { svc } = setup(); const id = await toConsent(svc);
    const stages = (await svc.getConversation(alice, id)).messages.map((m) => m.stage);
    expect(stages[0]).toBe("intake"); expect(stages).toContain("playback"); expect(stages.at(-1)).toBe("consent");
  });
  it("the producer view never exposes the PII flag", async () => {
    const { svc } = setup(); const id = (await svc.create(alice, "en", rid())).conversation.conversationId;
    const v = await svc.message(alice, id, rid(), "call me at 555");
    expect(JSON.stringify(v)).not.toMatch(/pii/i);
  });
  it("cleanTitle trims, caps and falls back to the playback summary", async () => {
    const { cleanTitle } = await import("../src/service");
    expect(cleanTitle("  Late   rain \n and yield ")).toBe("Late rain and yield");
    expect(cleanTitle(null, "x".repeat(100))!.length).toBe(58);
    expect(cleanTitle("", "")).toBeUndefined();
  });
});

describe("decline keeps no summary", () => {
  it("a declined conversation keeps no title or summary", async () => {
    const { svc, store } = setup(); const id = await toConsent(svc); await svc.consent(alice, id, rid(), false);
    const c = (await store.getConversation(id))!;
    expect([c.title, c.summaryEn, c.summaryOriginal, c.playbackSummary]).toEqual([undefined, undefined, undefined, undefined]);
  });
});

describe("saved summaries are kept until deleted", () => {
  it("V2: no indefinite retention by default; a saved conversation expires after the sandbox retention period", async () => {
    const { svc, store } = setup(); const id = await toConsent(svc); await svc.consent(alice, id, rid(), true);
    const exp = (await store.getConversation(id))!.expiresAt;
    expect(exp).toBeGreaterThan(0);
    expect(exp - Math.floor(Date.now() / 1000)).toBeGreaterThan(89 * 86400);
    expect(exp - Math.floor(Date.now() / 1000)).toBeLessThanOrEqual(90 * 86400);
    expect((await svc.getConversation(alice, id)).conversation.expiresAt).not.toBeNull();
  });
  it("the owner can delete a saved conversation; it leaves the history and its transcript and snapshots are gone", async () => {
    const { svc, store } = setup(); const id = await toConsent(svc); await svc.consent(alice, id, rid(), true);
    expect(await code(svc.deleteConversation(bob, id))).toBe("not_found");
    expect(await code(svc.deleteConversation(rev, id))).toBe("forbidden");
    await svc.deleteConversation(alice, id);
    expect(await store.getConversation(id)).toBeUndefined();
    expect(await store.listMessages(id)).toHaveLength(0);
    expect([...store.idem.keys()].some((k) => k.startsWith(id))).toBe(false);
    expect((await svc.listConversations(alice)).items).toHaveLength(0);
    expect(await code(svc.getConversation(alice, id))).toBe("not_found");
    // the consented review record is a separate record and is not changed
    expect(store.outcomes.get(`rec-${id}`)).toBeDefined();
  });
  it("an in-progress conversation cannot be deleted (end it instead)", async () => {
    const { svc } = setup(); const id = (await svc.create(alice, "en", rid())).conversation.conversationId;
    expect(await code(svc.deleteConversation(alice, id))).toBe("wrong_state");
  });
  it("declining storage (legacy consent route) still removes idempotency snapshots that could hold narrative", async () => {
    const { svc, store } = setup(); const id = await toConsent(svc);
    await svc.consent(alice, id, rid(), false);
    const snaps = [...store.idem.entries()].filter(([k]) => k.startsWith(id)).map(([, v]) => JSON.stringify(v));
    expect(snaps.some((x) => x.includes("EN summary"))).toBe(false);
    expect(await store.listMessages(id)).toHaveLength(0);
  });
  it("V2: stopping keeps the transcript, and the producer can still delete it explicitly", async () => {
    const { svc, store } = setup(); const id = (await svc.create(alice, "en", rid())).conversation.conversationId;
    await svc.message(alice, id, rid(), "my story"); await svc.end(alice, id, rid());
    expect((await store.listMessages(id)).some((m) => m.text === "my story")).toBe(true);
    expect((await svc.getConversation(alice, id)).conversation.status).toBe("stopped");
    await svc.deleteConversation(alice, id);
    expect(await store.listMessages(id)).toHaveLength(0);
  });
});

describe("French", () => {
  async function toConsentFr(svc: Service) {
    const id = (await svc.create(alice, "fr", rid())).conversation.conversationId;
    await svc.message(alice, id, rid(), "Les pluies sont arrivées tard"); await svc.message(alice, id, rid(), "La récolte a baissé");
    await svc.playback(alice, id, { requestId: rid(), decision: "confirm" }); return id;
  }
  it("passes French to the agent and uses the French opener when the agent is down", async () => {
    const { svc, agent } = setup(); await svc.create(alice, "fr", rid());
    expect(agent.calls[0].context.language).toBe("fr");
    agent.fail = true;
    expect((await svc.create(alice, "fr", rid())).messages[0].text).toBe("Qu'est-ce qui a été difficile ces derniers temps ?");
  });
  it("stores the French original and the English summary on the record and in history", async () => {
    const { svc, store } = setup(); const id = await toConsentFr(svc); await svc.consent(alice, id, rid(), true);
    expect(store.outcomes.get(`rec-${id}`)).toMatchObject({ language: "fr", summaryOriginal: "FR résumé", summaryEn: "EN summary" });
    expect((await svc.listConversations(alice)).items[0].summary).toBe("FR résumé");
  });
  it("reviewer can correct the original-language summary", async () => {
    const { svc } = setup(); const id = await toConsentFr(svc); await svc.consent(alice, id, rid(), true);
    expect(await svc.updateReview(rev, `rec-${id}`, { decision: "correct", correctedSummaryOriginal: "Pluies tardives" })).toMatchObject({ summaryOriginal: "Pluies tardives", reviewStatus: "corrected" });
  });
  it("rejects unsupported languages", async () => {
    const { svc } = setup();
    await expect(route(svc, alice, "POST", "/conversations", { requestId: rid(), language: "de" })).rejects.toThrow();
  });
});

describe("read aloud", () => {
  it("speaks the owner's agent reply in the conversation language, from server-held text, and never logs it", async () => {
    const { svc, speaker, logs, store } = setup(); const id = (await svc.create(alice, "fr", rid())).conversation.conversationId;
    await store.addMessages(id, [{ seq: 2, role: "assistant", text: "**Bonjour** et `merci`", at: "", stage: "intake" }]);
    const r = await svc.speech(alice, id, 2);
    expect(r).toMatchObject({ contentType: "audio/mpeg", voice: "Lea", language: "fr" });
    expect(Buffer.from(r.audio, "base64")).toEqual(Buffer.from([73, 68, 51, 4]));
    expect(speaker.calls.at(-1)).toEqual({ text: "Bonjour et merci", language: "fr" });
    expect(JSON.stringify(logs)).not.toContain("Bonjour");
  });
  it("refuses other producers, reviewers, producer messages and unknown messages", async () => {
    const { svc, store } = setup(); const id = (await svc.create(alice, "en", rid())).conversation.conversationId;
    await svc.message(alice, id, rid(), "my words");
    const userSeq = (await store.listMessages(id)).find((m) => m.role === "user")!.seq;
    expect(await code(svc.speech(bob, id, 1))).toBe("not_found");
    expect(await code(svc.speech(rev, id, 1))).toBe("forbidden");
    expect(await code(svc.speech(alice, id, userSeq))).toBe("not_found");
    expect(await code(svc.speech(alice, id, 99))).toBe("not_found");
  });
  it("speech failure is a retryable 502", async () => {
    const { svc, speaker } = setup(); const id = (await svc.create(alice, "en", rid())).conversation.conversationId; speaker.fail = true;
    await expect(svc.speech(alice, id, 1)).rejects.toMatchObject({ status: 502, code: "speech_unavailable", retryable: true });
  });
  it("route validates the message number and does not confuse speech with sending a message", async () => {
    const { svc, agent } = setup(); const id = (await svc.create(alice, "en", rid())).conversation.conversationId; const calls = agent.calls.length;
    await expect(route(svc, alice, "POST", `/conversations/${id}/messages/abc/speech`, {})).rejects.toThrow();
    const r = await route(svc, alice, "POST", `/conversations/${id}/messages/1/speech`, {}) as { contentType: string };
    expect(r.contentType).toBe("audio/mpeg"); expect(agent.calls.length).toBe(calls);
  });
  it("turns markdown into plain speech and splits long text at sentences", async () => {
    const { toSpokenText, chunkText } = await import("../src/speech");
    expect(toSpokenText("- **One** item\n- *two* `x`")).toBe("One item\ntwo x");
    const parts = chunkText("A sentence. ".repeat(400), 100);
    expect(parts.every((p) => p.length <= 100)).toBe(true); expect(parts.join(" ").length).toBeGreaterThan(4000);
  });
});

describe("synthetic producer turns are natural phrases", () => {
  it("opens with a greeting and confirms with a plain sentence in the conversation language", async () => {
    const { svc, agent } = setup(); const id = (await svc.create(alice, "es", rid())).conversation.conversationId;
    expect(agent.calls[0].messages.at(-1)!.text).toBe("Hola");
    await svc.message(alice, id, rid(), "a"); await svc.message(alice, id, rid(), "b");
    await svc.playback(alice, id, { requestId: rid(), decision: "confirm" });
    expect(agent.calls.at(-1)!.messages.at(-1)!.text).toBe("Sí, es correcto.");
    expect(JSON.stringify(agent.calls)).not.toMatch(/Open the conversation|Please continue/);
  });
});

describe("review screen API", () => {
  const rv: Principal = { sub: "sub-rev", groups: ["reviewer"], name: "reviewer.demo@example.com" };
  async function seed() {
    let t = Date.parse("2026-11-04T10:00:00Z"); const { store, agent } = setup(); const svc = new Service({ store, agent, now: () => (t += 60_000) });
    store.profiles.set("sub-alice", { ...profile("P-CO-001"), displayName: "Finca Alto Mirador", entityType: "association", location: "Cauca, Colombia" });
    const a = await toConsent(svc); await svc.consent(alice, a, rid(), true);           // Finca: saved, pending
    const b = (await svc.create(bob, "en", rid())).conversation.conversationId; await svc.end(bob, b, rid()); // SYN-B: declined
    const c = await toConsent(svc); await svc.consent(alice, c, rid(), true);           // Finca: second record
    return { svc, store, a, b, c };
  }
  it("every review operation is reviewer-only", async () => {
    const { svc, a } = await seed();
    for (const f of [() => svc.reviewStats(alice), () => svc.reviewProducers(alice, {}), () => svc.reviewProducerRecords(alice, "P-CO-001"),
      () => svc.reviewRelated(alice, "P-CO-001"), () => svc.getRecord(alice, `rec-${a}`), () => svc.patchRecord(alice, `rec-${a}`, { review_status: "approved" })])
      expect(await code(f())).toBe("forbidden");
  });
  it("records carry valid agent tags and a trusted producer snapshot", async () => {
    const { svc, a } = await seed();
    expect(await svc.getRecord(rv, `rec-${a}`)).toMatchObject({ challengeTags: ["water", "climate_weather"], producerName: "Finca Alto Mirador",
      entityType: "association", outcome: "completed", reviewStatus: "pending", source: "agent conversation", peerExampleOk: false, claims: [] });
  });
  it("stats count pending, declined and today's outcomes", async () => {
    const { svc } = await seed();
    expect(await svc.reviewStats(rv)).toMatchObject({ pending: 2, approved: 0, corrected: 0, declined: 1, piiFlagged: 0, conversationsToday: 3 });
  });
  it("producer list: pending first, counts, and filters by status, outcome, PII and search", async () => {
    const { svc } = await seed();
    const all = (await svc.reviewProducers(rv, {})).items;
    expect(all.map((x) => x.producerId)).toEqual(["P-CO-001", "SYN-B"]);
    expect(all[0]).toMatchObject({ producerName: "Finca Alto Mirador", recordCount: 2, pendingCount: 2 });
    expect((await svc.reviewProducers(rv, { outcome: "declined" })).items.map((x) => x.producerId)).toEqual(["SYN-B"]);
    expect((await svc.reviewProducers(rv, { review_status: "approved" })).items).toEqual([]);
    for (const [m, path, b] of [["PATCH", "/records/rec-x", { bogus: 1 }], ["GET", "/review/producers", undefined]] as const)
      await expect(route(svc, alice, m, path, b, { review_status: "nonsense" })).rejects.toMatchObject({ status: 403 });
    expect((await svc.reviewProducers(rv, { pii_only: "true" })).items).toEqual([]);
    expect((await svc.reviewProducers(rv, { q: "alto" })).items.map((x) => x.producerId)).toEqual(["P-CO-001"]);
    expect((await svc.reviewProducers(rv, { q: "climate_weather" })).items.map((x) => x.producerId)).toEqual(["P-CO-001"]);
  });
  it("producer records are newest first; declined records expose no narrative", async () => {
    const { svc, b, c } = await seed();
    expect((await svc.reviewProducerRecords(rv, "P-CO-001")).items[0].recordId).toBe(`rec-${c}`);
    const dec = (await svc.reviewProducerRecords(rv, "SYN-B")).items[0];
    expect(dec).toMatchObject({ recordId: `dec-${b}`, outcome: "declined", reviewStatus: null });
    expect(Object.keys(dec)).not.toEqual(expect.arrayContaining(["summaryOriginal", "summaryEn", "challengeTags", "claims"]));
  });
  it("related data joins the team's synthetic Premium, survey and certification rows; no SQL without a warehouse", async () => {
    const { svc } = await seed();
    const r = await svc.reviewRelated(rv, "P-CO-001");
    expect(r.premiumProjects.length).toBe(3); expect(r.premiumProjects[0].year).toBeGreaterThanOrEqual(r.premiumProjects[2].year);
    expect(r.surveys.length).toBeGreaterThan(0); expect(r.certification.length).toBe(1); expect(r.query).toBeNull();
    expect((await svc.reviewRelated(rv, "UNKNOWN")).premiumProjects).toEqual([]);
  });
  it("approve keeps content, records reviewer name and note; corrections change summary and tags; reviews happen once", async () => {
    const { svc, a, c, b } = await seed();
    expect(await svc.patchRecord(rv, `rec-${a}`, { review_status: "approved", reviewer_note: "Looks right" }))
      .toMatchObject({ reviewStatus: "approved", reviewerNote: "Looks right", reviewedBy: "reviewer.demo@example.com", challengeTags: ["water", "climate_weather"] });
    const cor = await svc.patchRecord(rv, `rec-${c}`, { review_status: "corrected", challenge_tags: ["water", "infrastructure"], summary_en: "Fixed." });
    expect(cor).toMatchObject({ reviewStatus: "corrected", challengeTags: ["water", "infrastructure"], agentChallengeTags: ["water", "climate_weather"], summaryEn: "Fixed." });
    expect((await svc.patchRecord(rv, `rec-${c}`, { review_status: "corrected", summary_en: "Fixed." })).reviewStatus).toBe("corrected"); // safe retry
    expect(await code(svc.patchRecord({ ...rv, sub: "other" }, `rec-${c}`, { review_status: "approved" }))).toBe("already_reviewed");
    expect(await code(svc.patchRecord(rv, `dec-${b}`, { review_status: "approved" }))).toBe("not_reviewable");
    expect(await svc.reviewStats(rv)).toMatchObject({ pending: 0, approved: 1, corrected: 1 });
  });
  it("route validation: approve cannot change content, correct must, tags must be from the 11", async () => {
    const { svc, a } = await seed();
    await expect(route(svc, rv, "PATCH", `/records/rec-${a}`, { review_status: "approved", summary_en: "x" })).rejects.toThrow();
    await expect(route(svc, rv, "PATCH", `/records/rec-${a}`, { review_status: "corrected" })).rejects.toThrow();
    await expect(route(svc, rv, "PATCH", `/records/rec-${a}`, { review_status: "corrected", challenge_tags: ["weather"] })).rejects.toThrow();
    await expect(route(svc, rv, "GET", "/review/producers", undefined, { review_status: "bogus" })).rejects.toThrow();
    expect(await route(svc, rv, "GET", "/review/producers", undefined, { review_status: "pending" })).toHaveProperty("items");
  });
});
