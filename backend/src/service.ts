import { randomUUID } from "node:crypto";
import type { AgentClient, AgentTurnResponse } from "./agent";
import { runtimeSessionIdFor } from "./agent";
import type { Conversation, Language, Message, Outcome, ProducerProfile } from "./contracts";
import { SYNTHETIC_LABEL } from "./contracts";
import { ApiError, conflict, forbidden, notFound } from "./errors";
import type { Store } from "./store";

export interface Principal { sub: string; groups: string[] }
export interface Deps {
  store: Store;
  agent: AgentClient;
  now?: () => number;
  log?: (event: Record<string, unknown>) => void;
}

export const MIN_USER_TURNS_BEFORE_PLAYBACK = 2;
export const ENTITY_TYPES = ["smallholder", "cooperative", "processor", "exporter", "other"];
const LOCK_MS = 120_000;
const ACTIVE_TTL_S = 7 * 86400; // sandbox retention: active conversations expire 7 days after last activity
const CLOSED_META_TTL_S = 30 * 86400; // closed: narrative-free metadata kept 30 days
const IDEM_TTL_S = 86400;

const OPENER: Record<Language, string> = {
  en: "What has been difficult recently?",
  es: "¿Qué ha sido difícil últimamente?",
};

export const requireProducer = (p: Principal) => { if (!p.groups.includes("producer")) throw forbidden("Producer access required."); };
export const requireReviewer = (p: Principal) => { if (!p.groups.includes("reviewer")) throw forbidden("Reviewer access required."); };

export class Service {
  private now: () => number;
  constructor(private d: Deps) { this.now = d.now ?? Date.now; }
  private iso = () => new Date(this.now()).toISOString();
  private log = (e: Record<string, unknown>) => this.d.log?.(e);

  // ---- identity -------------------------------------------------------
  async me(p: Principal) {
    const profile = p.groups.includes("producer") ? await this.d.store.getProfileBySub(p.sub) : undefined;
    return {
      roles: p.groups.filter((g) => g === "producer" || g === "reviewer"),
      profile: profile && { displayName: profile.displayName, entityType: profile.entityType, location: profile.location, crop: profile.crop, preferredLanguage: profile.preferredLanguage },
      syntheticDemo: true,
      syntheticLabel: SYNTHETIC_LABEL,
    };
  }

  private async profileFor(p: Principal): Promise<ProducerProfile> {
    const profile = await this.d.store.getProfileBySub(p.sub);
    if (!profile) throw new ApiError(403, "no_profile", "No producer profile is linked to this account.");
    return profile;
  }

  // ---- views ----------------------------------------------------------
  private async view(c: Conversation) {
    const messages = c.status === "active" ? await this.d.store.listMessages(c.conversationId) : [];
    return {
      conversation: {
        conversationId: c.conversationId, language: c.language, workflow: c.workflow, confirmation: c.confirmation,
        consent: c.consent, status: c.status, playbackSummary: c.playbackSummary, piiFlag: c.piiFlag,
        summaryEn: c.workflow === "consent_pending" ? c.summaryEn : undefined,
        summaryEs: c.workflow === "consent_pending" ? c.summaryEs : undefined,
        createdAt: c.createdAt, updatedAt: c.updatedAt, expiresAt: new Date(c.expiresAt * 1000).toISOString(),
      },
      messages: messages.map((m) => ({ seq: m.seq, role: m.role, text: m.text, at: m.at })),
      retention: {
        activeDays: 7,
        text: "Your messages are kept temporarily so you can continue, for up to 7 days. They are deleted when you finish. A summary is stored for review only if you say yes.",
      },
      syntheticDemo: true,
    };
  }

  private async owned(p: Principal, id: string): Promise<Conversation> {
    requireProducer(p);
    const c = await this.d.store.getConversation(id);
    if (!c || c.ownerSub !== p.sub) throw notFound(); // same response for missing and foreign
    return c;
  }

  async getConversation(p: Principal, id: string) { return this.view(await this.owned(p, id)); }

  async getCurrent(p: Principal) {
    requireProducer(p);
    const c = await this.d.store.findActiveByOwner(p.sub);
    return c ? this.view(c) : { conversation: null };
  }

  // ---- turn execution wrapper (ownership, idempotency, lock) -----------
  private async guarded<T>(p: Principal, id: string, requestId: string, fn: (c: Conversation) => Promise<T>): Promise<T> {
    await this.owned(p, id);
    const hit = await this.d.store.getIdem(id, requestId);
    if (hit !== undefined) return hit as T;
    const token = randomUUID();
    if (!(await this.d.store.acquireLock(id, token, this.now(), LOCK_MS)))
      throw conflict("turn_in_progress", "Another message is still being processed. Please wait a moment.", true);
    try {
      const again = await this.d.store.getIdem(id, requestId);
      if (again !== undefined) return again as T;
      const fresh = await this.owned(p, id);
      const result = await fn(fresh);
      await this.d.store.putIdem(id, requestId, result, Math.floor(this.now() / 1000) + IDEM_TTL_S);
      return result;
    } finally {
      await this.d.store.releaseLock(id, token);
    }
  }

  private async runAgent(c: Conversation, profile: ProducerProfile, mode: "intake" | "guidance", history: Message[], newUser: string, allowPlayback: boolean, p: Principal): Promise<AgentTurnResponse> {
    try {
      return await this.d.agent.turn({
        context: {
          conversationId: c.conversationId, language: c.language, mode, allowPlayback,
          // Trusted: built from the server-side profile, never from the request.
          producer: { producerId: profile.producerId, entityType: profile.entityType, location: profile.location, crop: profile.crop },
          confirmedAccount: c.confirmedAccount ?? null,
        },
        messages: [...history.map((m) => ({ role: m.role, text: m.text })), { role: "user" as const, text: newUser }],
      }, runtimeSessionIdFor(c.conversationId), p.sub);
    } catch (e) {
      this.log({ event: "agent_failure", conversationId: c.conversationId, mode, errorName: (e as Error).name });
      throw new ApiError(502, "agent_unavailable", "The assistant could not answer just now. Your message was not lost; please try again.", true);
    }
  }

  private async save(c: Conversation, patch: Partial<Conversation>): Promise<Conversation> {
    const n = await this.d.store.updateConversation(c.conversationId, c.version, {
      ...patch, updatedAt: this.iso(),
      expiresAt: patch.status && patch.status !== "active" ? Math.floor(this.now() / 1000) + CLOSED_META_TTL_S : Math.floor(this.now() / 1000) + ACTIVE_TTL_S,
    });
    if (!n) throw conflict("stale_state", "The conversation changed. Please reload and try again.", true);
    return n;
  }

  private async append(c: Conversation, entries: { role: "user" | "assistant"; text: string }[]): Promise<number> {
    const msgs: Message[] = entries.map((e, i) => ({ seq: c.messageCount + i + 1, role: e.role, text: e.text, at: this.iso() }));
    await this.d.store.addMessages(c.conversationId, msgs);
    return c.messageCount + msgs.length;
  }

  // ---- operations -------------------------------------------------------
  async create(p: Principal, language: Language) {
    requireProducer(p);
    const profile = await this.profileFor(p);
    const existing = await this.d.store.findActiveByOwner(p.sub);
    if (existing) return this.view(existing);

    const id = randomUUID();
    const nowIso = this.iso();
    const holder = await this.d.store.claimActiveSlot(p.sub, id, this.now());
    if (holder !== id) { const c = await this.d.store.getConversation(holder); if (c) return this.view(c); }
    const conv: Conversation = {
      conversationId: id, ownerSub: p.sub, producerId: profile.producerId, language, workflow: "intake",
      confirmation: "none", consent: "unanswered", status: "active", piiFlag: false, piiTypes: [],
      messageCount: 0, userTurns: 0, version: 1, createdAt: nowIso, updatedAt: nowIso,
      expiresAt: Math.floor(this.now() / 1000) + ACTIVE_TTL_S,
    };
    await this.d.store.putConversation(conv);
    // Real agent opener; deterministic fallback so a model outage cannot block starting.
    let opener = OPENER[language];
    try {
      const r = await this.runAgent(conv, profile, "intake", [], "(The producer has just joined. Open the conversation with one open question.)", false, p);
      opener = r.reply;
    } catch { this.log({ event: "opener_fallback", conversationId: id }); }
    const count = await this.append(conv, [{ role: "assistant", text: opener }]);
    const saved = await this.save(conv, { messageCount: count });
    this.log({ event: "conversation_created", conversationId: id });
    return this.view(saved);
  }

  async message(p: Principal, id: string, requestId: string, text: string) {
    return this.guarded(p, id, requestId, async (c) => {
      this.assertActive(c);
      if (c.workflow === "playback_pending") throw conflict("playback_required", "Please confirm or correct the summary first.");
      if (c.workflow !== "intake") throw conflict("wrong_state", "This step does not accept new messages.");
      const profile = await this.profileFor(p);
      const history = await this.d.store.listMessages(id);
      const allow = c.userTurns + 1 >= MIN_USER_TURNS_BEFORE_PLAYBACK;
      const r = await this.runAgent(c, profile, "intake", history, text, allow, p);
      const toPlayback = allow && r.phase === "playback" && !!r.playbackSummary; // app-side check, independent of the agent
      const count = await this.append(c, [{ role: "user", text }, { role: "assistant", text: r.reply }]);
      const saved = await this.save(c, {
        messageCount: count, userTurns: c.userTurns + 1,
        piiFlag: c.piiFlag || r.piiFlag, piiTypes: [...new Set([...c.piiTypes, ...r.piiTypes])],
        ...(toPlayback ? { workflow: "playback_pending", confirmation: "pending", playbackSummary: r.playbackSummary! } : {}),
      });
      return this.view(saved);
    });
  }

  async playback(p: Principal, id: string, req: { requestId: string; decision: "confirm" | "correct"; correction?: string; profileCorrection?: { field: "location" | "entityType"; value: string } }) {
    return this.guarded(p, id, req.requestId, async (c) => {
      this.assertActive(c);
      const profile = await this.profileFor(p);
      if (req.decision === "confirm") {
        if (c.workflow !== "playback_pending" && c.workflow !== "guidance_pending") throw conflict("wrong_state", "Nothing to confirm right now.");
        let cur = c;
        if (c.workflow === "playback_pending") {
          const count = await this.append(c, [{ role: "user", text: "(confirmed)" }]);
          cur = await this.save(c, { workflow: "guidance_pending", confirmation: "confirmed", confirmedAccount: c.playbackSummary, messageCount: count });
        }
        const history = await this.d.store.listMessages(id);
        const r = await this.runAgent(cur, profile, "guidance", history.slice(0, -1), "The producer confirmed the account. Please continue.", false, p);
        const count2 = await this.append(cur, [{ role: "assistant", text: r.reply }]);
        const saved = await this.save(cur, {
          messageCount: count2, summaryEn: r.summaryEn ?? undefined, summaryEs: r.summaryEs ?? undefined,
          workflow: r.summaryEn && r.summaryEs ? "consent_pending" : "guidance_pending",
          piiFlag: cur.piiFlag || r.piiFlag, piiTypes: [...new Set([...cur.piiTypes, ...r.piiTypes])],
        });
        return this.view(saved);
      }
      if (c.workflow !== "playback_pending") throw conflict("wrong_state", "Nothing to correct right now.");
      // Corrections to location/entity type are validated by the app and kept as producer assertions only.
      const assertions = { ...(c.producerAssertions ?? {}) };
      let text = req.correction ?? "";
      const pc = req.profileCorrection;
      if (pc) {
        if (pc.field === "entityType" && !ENTITY_TYPES.includes(pc.value)) throw new ApiError(400, "validation_error", "Unknown entity type.");
        assertions[pc.field] = pc.value;
        text = text || `Correction: my ${pc.field === "entityType" ? "entity type" : "location"} is ${pc.value}.`;
      }
      const history = await this.d.store.listMessages(id);
      const r = await this.runAgent(c, profile, "intake", history, text, true, p);
      const again = r.phase === "playback" && !!r.playbackSummary;
      const count = await this.append(c, [{ role: "user", text }, { role: "assistant", text: r.reply }]);
      const saved = await this.save(c, {
        messageCount: count, userTurns: c.userTurns + 1, producerAssertions: assertions,
        piiFlag: c.piiFlag || r.piiFlag, piiTypes: [...new Set([...c.piiTypes, ...r.piiTypes])],
        ...(again ? { playbackSummary: r.playbackSummary!, confirmation: "pending" as const } : { workflow: "intake" as const, confirmation: "none" as const }),
      });
      return this.view(saved);
    });
  }

  async consent(p: Principal, id: string, requestId: string, storeSummary: boolean) {
    return this.guarded(p, id, requestId, async (c) => {
      this.assertActive(c);
      if (c.workflow !== "consent_pending") throw conflict("wrong_state", "Storage permission is not requested yet.");
      if (storeSummary && !(c.summaryEn && c.summaryEs)) throw conflict("no_summary", "There is no summary to store.");
      return this.close(c, storeSummary ? "granted" : "declined", "declined_storage");
    });
  }

  async end(p: Principal, id: string, requestId: string) {
    return this.guarded(p, id, requestId, async (c) => {
      if (c.status !== "active") return this.view(c);
      return this.close(c, "declined", c.workflow === "consent_pending" ? "declined_storage" : "ended_early");
    });
  }

  private async close(c: Conversation, consent: "granted" | "declined", reason: "declined_storage" | "ended_early") {
    const base = { outcomeId: "", ownerSub: c.ownerSub, producerId: c.producerId, conversationId: c.conversationId, language: c.language, createdAt: this.iso() };
    if (consent === "granted") {
      const o: Outcome = {
        ...base, outcomeId: `rec-${c.conversationId}`, kind: "record", source: "agent conversation",
        entityType: (await this.d.store.getProfileBySub(c.ownerSub))?.entityType, summaryEn: c.summaryEn, summaryEs: c.summaryEs,
        piiFlag: c.piiFlag, piiTypes: c.piiTypes, evidenceStatus: "unavailable", reviewStatus: "pending",
      };
      await this.d.store.putOutcome(o);
    } else {
      await this.d.store.putOutcome({ ...base, outcomeId: `dec-${c.conversationId}`, kind: "declined", declineReason: reason });
    }
    // Transient narrative is removed in both cases.
    await this.d.store.deleteMessages(c.conversationId);
    const saved = await this.save(c, {
      workflow: "closed", consent, status: consent === "granted" ? "completed" : "declined",
      playbackSummary: undefined, confirmedAccount: undefined, summaryEn: undefined, summaryEs: undefined, producerAssertions: undefined,
    });
    await this.d.store.releaseActiveSlot(c.ownerSub, c.conversationId);
    this.log({ event: "conversation_closed", conversationId: c.conversationId, consent });
    return this.view(saved);
  }

  private assertActive(c: Conversation) { if (c.status !== "active") throw conflict("conversation_closed", "This conversation has ended."); }

  // ---- ask (stateless Q&A: nothing is stored) ------------------------------
  async ask(p: Principal, text: string, language: Language) {
    requireProducer(p);
    const profile = await this.profileFor(p);
    let r: AgentTurnResponse;
    try {
      r = await this.d.agent.turn({
        context: { conversationId: `ask-${randomUUID()}`, language, mode: "ask", allowPlayback: false,
          producer: { producerId: profile.producerId, entityType: profile.entityType, location: profile.location, crop: profile.crop }, confirmedAccount: null },
        messages: [{ role: "user", text }],
      }, `ftusa-ask-${p.sub}`, p.sub);
    } catch (e) {
      this.log({ event: "agent_failure", mode: "ask", errorName: (e as Error).name });
      throw new ApiError(502, "agent_unavailable", "The assistant could not answer just now. Please try again.", true);
    }
    this.log({ event: "ask_answered", piiFlag: r.piiFlag });
    return { answer: r.reply, evidence: { status: "unavailable" as const }, piiFlag: r.piiFlag, language: r.language, syntheticDemo: true };
  }

  // ---- overview (role-aware home) ----------------------------------------
  async overview(p: Principal) {
    const out: Record<string, unknown> = { syntheticDemo: true };
    if (p.groups.includes("producer")) {
      const c = await this.d.store.findActiveByOwner(p.sub);
      out.producer = { activeConversation: c ? { workflow: c.workflow, updatedAt: c.updatedAt } : null };
    }
    if (p.groups.includes("reviewer")) {
      const recs = await this.d.store.listRecords();
      const count = (s: string) => recs.filter((r) => r.reviewStatus === s).length;
      out.reviewer = { pending: count("pending"), approved: count("approved"), corrected: count("corrected"), piiFlagged: recs.filter((r) => r.piiFlag).length,
        recent: recs.slice(0, 5).map((r) => this.reviewView(r)) };
    }
    return out;
  }

  // ---- reviewer ---------------------------------------------------------
  private reviewView(o: Outcome) {
    return { outcomeId: o.outcomeId, source: o.source, producerId: o.producerId, entityType: o.entityType, language: o.language,
      summaryEn: o.summaryEn, summaryEs: o.summaryEs, piiFlag: o.piiFlag, piiTypes: o.piiTypes, evidenceStatus: o.evidenceStatus,
      reviewStatus: o.reviewStatus, reviewedAt: o.reviewedAt, createdAt: o.createdAt, syntheticDemo: true };
  }
  async listReviews(p: Principal) {
    requireReviewer(p);
    return { items: (await this.d.store.listRecords()).map((o) => this.reviewView(o)) };
  }
  async getReview(p: Principal, id: string) {
    requireReviewer(p);
    const o = await this.d.store.getOutcome(id);
    if (!o || o.kind !== "record") throw notFound(); // declined outcomes have no reviewable narrative
    return this.reviewView(o);
  }
  async updateReview(p: Principal, id: string, req: { decision: "approve" | "correct"; correctedSummaryEn?: string; correctedSummaryEs?: string; piiHandled?: boolean }) {
    requireReviewer(p);
    const o = await this.d.store.getOutcome(id);
    if (!o || o.kind !== "record") throw notFound();
    const status = req.decision === "approve" ? "approved" : "corrected";
    if (o.reviewStatus !== "pending") {
      if (o.reviewStatus === status && o.reviewedBy === p.sub) return this.reviewView(o); // retry of a completed review
      throw conflict("already_reviewed", "This record has already been reviewed.");
    }
    const patch: Partial<Outcome> = { reviewStatus: status, reviewedBy: p.sub, reviewedAt: this.iso() };
    if (req.decision === "correct") {
      if (req.correctedSummaryEn) patch.summaryEn = req.correctedSummaryEn;
      if (req.correctedSummaryEs) patch.summaryEs = req.correctedSummaryEs;
    }
    if (req.piiHandled) patch.piiFlag = false;
    const n = await this.d.store.reviewOutcome(id, patch);
    if (!n) throw conflict("already_reviewed", "This record has already been reviewed.");
    this.log({ event: "review_updated", outcomeId: id, status });
    return this.reviewView(n);
  }
}
