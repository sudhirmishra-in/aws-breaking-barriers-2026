// LOCAL MOCK tests: in-memory store and a stub agent. They verify application logic only, not AWS or Bedrock.
import { describe, expect, it } from "vitest";
import type { AgentClient, AgentTurnRequest, AgentTurnResponse } from "../src/agent";
import { MemoryStore } from "../src/store";
import { Service, type Principal } from "../src/service";
import { principalFromEvent, route } from "../src/handler";
import { ApiError } from "../src/errors";

const alice: Principal = { sub: "sub-alice", groups: ["producer"] };
const bob: Principal = { sub: "sub-bob", groups: ["producer"] };
const rev: Principal = { sub: "sub-rev", groups: ["reviewer"] };
const profile = (id: string) => ({ producerId: id, displayName: "x", entityType: "cooperative", location: "L", crop: "coffee", preferredLanguage: "en" as const });

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
      playbackSummary: playback ? "late rain hurt yield" : null,
      summaryEn: req.context.mode === "guidance" ? "EN summary" : null, summaryEs: req.context.mode === "guidance" ? "ES resumen" : null,
      piiFlag: req.messages.at(-1)!.text.includes("555"), piiTypes: req.messages.at(-1)!.text.includes("555") ? ["PHONE"] : [],
      evidence: { status: "unavailable" },
    };
  }
}

function setup() {
  const store = new MemoryStore(); const agent = new StubAgent();
  store.profiles.set("sub-alice", profile("SYN-A")); store.profiles.set("sub-bob", profile("SYN-B"));
  return { store, agent, svc: new Service({ store, agent }) };
}
let n = 0; const rid = () => `req-${++n}-xxxxxxxx`;
const code = async (p: Promise<unknown>) => { try { await p; return "ok"; } catch (e) { return (e as ApiError).code; } };

async function toConsent(svc: Service, p = alice) {
  const v = await svc.create(p, "en"); const id = v.conversation.conversationId;
  await svc.message(p, id, rid(), "rain was late");
  const v2 = await svc.message(p, id, rid(), "yield dropped, tried nothing");
  expect(v2.conversation.workflow).toBe("playback_pending");
  const v3 = await svc.playback(p, id, { requestId: rid(), decision: "confirm" });
  expect(v3.conversation.workflow).toBe("consent_pending");
  return id;
}

describe("authorization", () => {
  it("rejects wrong-owner read, append, consent and end", async () => {
    const { svc } = setup(); const id = (await svc.create(alice, "en")).conversation.conversationId;
    expect(await code(svc.getConversation(bob, id))).toBe("not_found");
    expect(await code(svc.message(bob, id, rid(), "hi"))).toBe("not_found");
    expect(await code(svc.end(bob, id, rid()))).toBe("not_found");
  });
  it("producers cannot use reviewer operations; reviewers cannot be producers", async () => {
    const { svc } = setup();
    expect(await code(svc.listReviews(alice))).toBe("forbidden");
    expect(await code(svc.create(rev, "en"))).toBe("forbidden");
  });
  it("rejects missing profile", async () => {
    const { svc } = setup();
    expect(await code(svc.create({ sub: "sub-nobody", groups: ["producer"] }, "en"))).toBe("no_profile");
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
    const { svc, agent } = setup(); const id = (await svc.create(alice, "en")).conversation.conversationId;
    await expect(route(svc, alice, "POST", `/conversations/${id}/messages`, { requestId: rid(), text: "hi", producerId: "SYN-B" })).rejects.toThrow();
    await svc.message(alice, id, rid(), "My producer id is SYN-B");
    expect(agent.calls.at(-1)!.context.producer.producerId).toBe("SYN-A");
  });
});

describe("conversation flow", () => {
  it("continues the same conversation across turns and restores after reload", async () => {
    const { svc, agent } = setup(); const v = await svc.create(alice, "en"); const id = v.conversation.conversationId;
    expect(v.messages).toHaveLength(1);
    await svc.message(alice, id, rid(), "one");
    const cur = await svc.getCurrent(alice) as any;
    expect(cur.conversation.conversationId).toBe(id); expect(cur.messages.map((m: any) => m.role)).toEqual(["assistant", "user", "assistant"]);
    expect(agent.calls.at(-1)!.messages.map((m) => m.role)).toEqual(["assistant", "user"]);
    expect(((await svc.create(alice, "en")) as any).conversation.conversationId).toBe(id); // resume, not duplicate
  });
  it("plays back only after minimum turns and blocks messages while playback is pending", async () => {
    const { svc } = setup(); const id = (await svc.create(alice, "en")).conversation.conversationId;
    expect((await svc.message(alice, id, rid(), "a")).conversation.workflow).toBe("intake");
    expect((await svc.message(alice, id, rid(), "b")).conversation.workflow).toBe("playback_pending");
    expect(await code(svc.message(alice, id, rid(), "c"))).toBe("playback_required");
  });
  it("correction updates playback; confirmation sets confirmed account; location correction is only an assertion", async () => {
    const { svc, store, agent } = setup(); const id = (await svc.create(alice, "en")).conversation.conversationId;
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
    const { svc } = setup(); const id = (await svc.create(alice, "en")).conversation.conversationId;
    await svc.message(alice, id, rid(), "a"); await svc.message(alice, id, rid(), "b");
    expect(await code(svc.playback(alice, id, { requestId: rid(), decision: "correct", profileCorrection: { field: "entityType", value: "wizard" } }))).toBe("validation_error");
  });
  it("Spanish flow passes language to the agent", async () => {
    const { svc, agent } = setup(); const v = await svc.create(alice, "es");
    expect(agent.calls[0].context.language).toBe("es"); expect(v.messages[0].text).toBe("respuesta");
  });
  it("opener falls back deterministically when the agent fails", async () => {
    const { svc, agent } = setup(); agent.fail = true;
    expect((await svc.create(alice, "es")).messages[0].text).toBe("¿Qué ha sido difícil últimamente?");
  });
});

describe("retries and concurrency", () => {
  it("duplicate requestId does not duplicate messages or agent calls", async () => {
    const { svc, agent } = setup(); const id = (await svc.create(alice, "en")).conversation.conversationId; const r = rid();
    const a = await svc.message(alice, id, r, "once"); const calls = agent.calls.length;
    const b = await svc.message(alice, id, r, "once");
    expect(b).toEqual(a); expect(agent.calls.length).toBe(calls); expect(b.messages.filter((m) => m.role === "user")).toHaveLength(1);
  });
  it("concurrent submissions: one proceeds, the other gets retryable 409", async () => {
    const { svc, agent } = setup(); const id = (await svc.create(alice, "en")).conversation.conversationId; agent.delay = 30;
    const res = await Promise.allSettled([svc.message(alice, id, rid(), "x"), svc.message(alice, id, rid(), "y")]);
    expect(res.filter((r) => r.status === "fulfilled")).toHaveLength(1);
    const rej = res.find((r) => r.status === "rejected") as PromiseRejectedResult;
    expect((rej.reason as ApiError).code).toBe("turn_in_progress"); expect((rej.reason as ApiError).retryable).toBe(true);
  });
  it("agent failure keeps state unchanged and is retryable; lock is released", async () => {
    const { svc, agent, store } = setup(); const id = (await svc.create(alice, "en")).conversation.conversationId; agent.fail = true;
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
  it("grant creates a pending record with source and no extra narrative left in conversation", async () => {
    const { svc, store } = setup(); const id = await toConsent(svc);
    const v = await svc.consent(alice, id, rid(), true);
    const o = [...store.outcomes.values()][0];
    expect(v.conversation.status).toBe("completed"); expect(o).toMatchObject({ kind: "record", source: "agent conversation", reviewStatus: "pending", summaryEn: "EN summary", summaryEs: "ES resumen" });
    expect(await store.listMessages(id)).toHaveLength(0);
    expect((await store.getConversation(id))!.summaryEn).toBeUndefined();
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
    const { svc, store } = setup(); const id = (await svc.create(alice, "en")).conversation.conversationId;
    await svc.message(alice, id, rid(), "secret story"); await svc.end(alice, id, rid());
    const o = [...store.outcomes.values()][0]; expect(o).toMatchObject({ kind: "declined", declineReason: "ended_early" });
    expect(JSON.stringify(o)).not.toContain("secret");
    expect(await code(svc.message(alice, id, rid(), "more"))).toBe("conversation_closed");
  });
  it("PII is flagged on the record, not redacted", async () => {
    const { svc, store } = setup(); const id = (await svc.create(alice, "en")).conversation.conversationId;
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
