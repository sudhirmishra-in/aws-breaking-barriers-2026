import { randomUUID } from "node:crypto";
import type { AgentClient, AgentTurnResponse } from "./agent";
import { runtimeSessionIdFor } from "./agent";
import { createHash } from "node:crypto";
import type { ChallengeTag, Conversation, Language, Message, Outcome, ProducerProfile, Stage, Workflow } from "./contracts";
import { CHALLENGE_TAGS, ENTITY_TYPES } from "./contracts";
import { relatedFor, teamProducer } from "./relatedData";
import { SYNTHETIC_LABEL } from "./contracts";
import { ApiError, conflict, forbidden, notFound } from "./errors";
import type { Store } from "./store";
import type { Transcriber } from "./transcribe";
import { toSpokenText, type Speaker } from "./speech";

export interface Principal { sub: string; groups: string[]; name?: string }
export interface Deps {
  store: Store;
  agent: AgentClient;
  transcriber?: Transcriber;
  speaker?: Speaker;
  now?: () => number;
  log?: (event: Record<string, unknown>) => void;
  /** Called by the publisher before a record becomes "published" (derived memory / index update). A throw leaves the record "failed". */
  publishSideEffect?: (o: Outcome) => Promise<void>;
  /** Retrieval over public project records (local concept retriever by default; a Bedrock Knowledge Base adapter implements the same port). */
  projects?: import("./projectEvidence").ProjectRetriever;
  /** Derived memory (AgentCore Memory). Absent in unit tests and when no memory resources are provisioned. */
  memory?: import("./memory").MemoryPort;
  /** Cached external environmental facts (country level). */
  facts?: import("./externalFacts").FactsPort;
  /** Metrics sink (CloudWatch EMF in production). */
  metric?: (name: string, value?: number, unit?: string, dims?: Record<string, string>) => void;
}

export const MIN_USER_TURNS_BEFORE_PLAYBACK = 2;
export const FORCE_PLAYBACK_TURN = 4; // by the 4th producer message the agent must play back, so intake cannot loop
export const AUDIO_BYTES_PER_SECOND = 32000; // 16 kHz x 2 bytes, mono
export const AUDIO_MIN_BYTES = Math.round(AUDIO_BYTES_PER_SECOND * 0.3);
export const AUDIO_MAX_BYTES = AUDIO_BYTES_PER_SECOND * 60;
export { ENTITY_TYPES };
const LOCK_MS = 120_000;
const ACTIVE_TTL_S = 7 * 86400; // sandbox retention: active conversations expire 7 days after last activity
const CLOSED_META_TTL_S = 30 * 86400; // closed: narrative-free metadata kept 30 days
// Sandbox retention (docs/REDESIGN_V2.md section 6): no indefinite default. Completed or stopped conversations (transcript + summary) 90 days,
// finalized FTUSA records 180 days (set on the record by the finalize step). Producers can request earlier deletion.
export const RETENTION = { completedConversationS: 90 * 86400, recordS: 180 * 86400 } as const;
const SAVED_TRANSCRIPT_TTL_S = RETENTION.completedConversationS;
const IDEM_TTL_S = 86400;

// Synthetic producer turns sent to the agent are natural phrases, not instructions: instruction-like text is
// flagged by the guardrail's prompt-attack filter (seen in the sandbox), which blocked the agent's opener.
const GREETING: Record<Language, string> = { en: "Hello", es: "Hola", fr: "Bonjour" };
const CONFIRMED: Record<Language, string> = { en: "Yes, that's right.", es: "Sí, es correcto.", fr: "Oui, c'est exact." };

const OPENER: Record<Language, string> = {
  en: "What has been difficult recently?",
  es: "¿Qué ha sido difícil últimamente?",
  fr: "Qu'est-ce qui a été difficile ces derniers temps ?",
};

const STAGE_OF: Record<Workflow, Stage> = { intake: "intake", playback_pending: "playback", guidance_pending: "response", consent_pending: "consent", closed: "consent" };
/** Stable hash of exactly what the producer confirms (original-language summary, English summary, tags, language). */
export function summaryHashOf(c: Pick<Conversation, "summaryOriginal" | "summaryEn" | "challengeTags" | "language">): string {
  return createHash("sha256").update(JSON.stringify([c.language, c.summaryOriginal ?? "", c.summaryEn ?? "", [...(c.challengeTags ?? [])].sort()])).digest("hex");
}
export type DayGroup = "today" | "previous_7_days" | "older";
export function dayGroupOf(iso: string, nowMs: number): DayGroup {
  const d = new Date(nowMs); d.setUTCHours(0, 0, 0, 0);
  const t = Date.parse(iso);
  if (t >= d.getTime()) return "today";
  return t >= d.getTime() - 7 * 86400_000 ? "previous_7_days" : "older";
}
/** Short, single-line history title. The model proposes it; it is display text only and never used as scope. */
export function cleanTitle(title: string | null | undefined, fallback?: string): string | undefined {
  const t = (title ?? "").replace(/\s+/g, " ").trim();
  if (t) return t.slice(0, 80);
  const f = (fallback ?? "").replace(/\s+/g, " ").trim();
  return f ? (f.length > 60 ? f.slice(0, 57).trimEnd() + "…" : f) : undefined;
}

export const requireProducer = (p: Principal) => { if (!p.groups.includes("producer")) throw forbidden("Producer access required."); };
export const requireReviewer = (p: Principal) => { if (!p.groups.includes("reviewer")) throw forbidden("Reviewer access required."); };

export class Service {
  protected now: () => number;
  constructor(protected d: Deps) { this.now = d.now ?? Date.now; }
  protected iso = () => new Date(this.now()).toISOString();
  protected log = (e: Record<string, unknown>) => this.d.log?.(e);

  // ---- identity -------------------------------------------------------
  async me(p: Principal) {
    const isProducer = p.groups.includes("producer");
    const profile = isProducer ? await this.d.store.getProfileBySub(p.sub) : undefined;
    return {
      roles: p.groups.filter((g) => g === "producer" || g === "reviewer"),
      profile: profile && { displayName: profile.displayName, entityType: profile.entityType, location: profile.location, crop: profile.crop, preferredLanguage: profile.preferredLanguage },
      // V2 identity, resolved server-side from the Cognito subject. Four distinct identifiers; none is accepted from the browser.
      identity: profile && { producerId: profile.producerId, organizationId: profile.organizationId ?? null, applicationUserId: profile.applicationUserId ?? null },
      preferred_language: profile ? profile.preferredLanguage ?? "en" : null, // English is the explicit missing-language fallback
      // A producer without a mapping gets a configuration error, never a default producer.
      configurationError: isProducer ? (!profile ? "producer_mapping_missing" as const : !profile.organizationId ? "organization_missing" as const : null) : null,
      syntheticDemo: true,
      syntheticLabel: SYNTHETIC_LABEL,
    };
  }

  protected async factsForAgent(profile: ProducerProfile) {
    const country = await this.countryOf(profile);
    if (!country || !this.d.facts) return [];
    const all = await this.d.facts.forCountry(country, ["climate", "water", "soil_land", "market", "biodiversity", "tenure", "elevation"]).catch(() => []);
    return all.filter((f) => !f.isStandIn && f.value !== null && !f.isProjection).slice(0, 8)
      .map((f) => ({ dataset: f.dataset, indicator: f.indicator, value: f.value, unit: f.unit, period: f.period, baselineValue: f.baselineValue, baselineDeltaPct: f.baselineDeltaPct, baselinePeriod: f.baselinePeriod }));
  }

  /** The producer's country, from the organization record (server side). Used by the agent's external-data tool; never taken from free text. */
  protected async countryOf(profile: ProducerProfile): Promise<string | undefined> {
    const org = profile.organizationId ? await this.d.store.getOrganization(profile.organizationId) : undefined;
    return org?.info.countryName ?? undefined;
  }

  protected async profileFor(p: Principal): Promise<ProducerProfile> {
    const profile = await this.d.store.getProfileBySub(p.sub);
    if (!profile) throw new ApiError(403, "no_profile", "No producer profile is linked to this account.");
    // Every producer is a member of an organization; there is no individual-farmer entity. An unlinked account is a configuration error, never a default.
    if (!profile.organizationId) throw new ApiError(403, "no_organization", "This account is not linked to an organization.");
    return profile;
  }

  // ---- views ----------------------------------------------------------
  protected async view(c: Conversation) {
    // Active and saved conversations show their transcript; declined ones have none (deleted on decline).
    const messages = c.status === "declined" ? [] : await this.d.store.listMessages(c.conversationId);
    return {
      conversation: {
        conversationId: c.conversationId, language: c.language, workflow: c.workflow, confirmation: c.confirmation,
        // No PII flag here: the producer side never shows it (spec CHAT-19).
        consent: c.consent, status: c.status, title: c.title ?? null, playbackSummary: c.playbackSummary,
        summaryOriginal: c.workflow === "consent_pending" || c.status === "completed" ? c.summaryOriginal : undefined,
        summaryEn: c.workflow === "consent_pending" || c.status === "completed" ? c.summaryEn : undefined,
        createdAt: c.createdAt, updatedAt: c.updatedAt, expiresAt: c.expiresAt ? new Date(c.expiresAt * 1000).toISOString() : null,
      },
      messages: messages.map((m) => ({ seq: m.seq, role: m.role, text: m.text, at: m.at, stage: m.stage ?? null })),
      confirmation: c.workflow === "consent_pending" && c.summaryEn && c.summaryOriginal
        ? { summaryHash: summaryHashOf(c), summaryOriginal: c.summaryOriginal, summaryEn: c.summaryEn, tags: c.challengeTags ?? [], language: c.language } : null,
      record: await this.recordState(c),
      referencedCase: c.referencedCase ?? null,
      referencedCaseCard: c.referencedCase ? await this.referenceCard(c) : null,
      retention: {
        activeDays: 7, savedDays: 30,
        text: "Messages are kept so you can continue, for up to 7 days without activity. If you save the conversation, its summary stays in your history until you delete it, and the full conversation is kept for 30 days in this sandbox. If you don't save it, its messages are deleted when it ends.",
      },
      syntheticDemo: true,
    };
  }

  protected async referenceCard(_c: Conversation): Promise<unknown> { return null; }

  /** What the producer may see about their own finalized record: sharing, review and publication are independent and all shown. */
  protected async recordState(c: Conversation) {
    if (c.status !== "completed") return null;
    const o = await this.d.store.getOutcome(`rec-${c.conversationId}`);
    if (!o || o.kind !== "record") return null;
    return { sharingChoice: o.sharingChoice ?? "ftusa_only", identityPermitted: !!o.identityPermitted, reviewStatus: o.reviewStatus ?? "pending",
      publicationStatus: o.publicationStatus ?? "not_shared", tags: o.challengeTags ?? [], feedback: o.feedback ?? null, summaryVersion: o.summaryVersion ?? 1, deletionRequested: !!o.deletionRequestedAt,
      reconfirmation: o.pendingRevision ? { summaryHash: o.pendingRevision.hash, summaryOriginal: o.pendingRevision.summaryOriginal, summaryEn: o.pendingRevision.summaryEn, version: o.pendingRevision.version } : null };
  }

  protected async owned(p: Principal, id: string): Promise<Conversation> {
    requireProducer(p);
    const c = await this.d.store.getConversation(id);
    if (!c || c.ownerSub !== p.sub) throw notFound(); // same response for missing and foreign
    return c;
  }

  async getConversation(p: Principal, id: string) { return this.view(await this.owned(p, id)); }

  /** My conversations: own transcripts only, newest first, grouped Today / Previous 7 days / Older. Declined (purged) ones are never listed. */
  async listConversations(p: Principal) {
    requireProducer(p);
    const items = (await this.d.store.listByOwner(p.sub))
      .filter((c) => c.ownerSub === p.sub && c.status !== "declined")
      .map((c) => ({ conversationId: c.conversationId, title: c.title ?? null, language: c.language, createdAt: c.createdAt, updatedAt: c.updatedAt,
        status: c.status === "active" ? "in_progress" as const : "completed" as const, stopped: c.status === "stopped",
        group: dayGroupOf(c.createdAt, this.now()), summary: this.producerSummary(c) }));
    return { items };
  }

  /** The summary the producer saw, in their language: the saved summary, else the latest playback. */
  protected producerSummary(c: Conversation): string | null {
    const saved = c.summaryOriginal ?? (c.language === "en" ? c.summaryEn : undefined);
    return saved ?? c.confirmedAccount ?? c.playbackSummary ?? null;
  }

  async getCurrent(p: Principal) {
    requireProducer(p);
    const c = await this.d.store.findActiveByOwner(p.sub);
    return c ? this.view(c) : { conversation: null };
  }

  // ---- turn execution wrapper (ownership, idempotency, lock) -----------
  protected async guarded<T>(p: Principal, id: string, requestId: string, fn: (c: Conversation) => Promise<T>): Promise<T> {
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

  protected async runAgent(c: Conversation, profile: ProducerProfile, mode: "intake" | "guidance" | "followup", history: Message[], newUser: string, allowPlayback: boolean, p: Principal): Promise<AgentTurnResponse> {
    const t0 = Date.now();
    try {
      const out = await this.d.agent.turn({
        context: {
          conversationId: c.conversationId, language: c.language, mode, allowPlayback, forcePlayback: allowPlayback && c.userTurns + 1 >= FORCE_PLAYBACK_TURN,
          // Trusted: built from the server-side profile, never from the request.
          producer: { producerId: profile.producerId, entityType: profile.entityType, location: profile.location, crop: profile.crop, country: await this.countryOf(profile) },
          confirmedAccount: c.confirmedAccount ?? null,
          // The application looks up the producer's own country's cached facts; the closing turn cites them. Stand-ins (failed fetches) never reach the model.
          externalFacts: await this.factsForAgent(profile), // every turn: the agent should never claim to have no data when the app already holds it
        },
        messages: [...history.map((m) => ({ role: m.role, text: m.text })), { role: "user" as const, text: newUser }],
      }, runtimeSessionIdFor(c.conversationId), p.sub);
      this.d.metric?.("AgentTurnLatencyMs", Date.now() - t0, "Milliseconds", { Mode: mode });
      if (out.piiFlag) this.d.metric?.("PiiFlagged", 1);
      return out;
    } catch (e) {
      this.d.metric?.("AgentFailure", 1, "Count", { Mode: mode });
      this.log({ event: "agent_failure", conversationId: c.conversationId, mode, errorName: (e as Error).name });
      throw new ApiError(502, "agent_unavailable", "The assistant could not answer just now. Your message was not lost; please try again.", true);
    }
  }

  protected async save(c: Conversation, patch: Partial<Conversation>): Promise<Conversation> {
    const n = await this.d.store.updateConversation(c.conversationId, c.version, {
      ...patch, updatedAt: this.iso(),
      expiresAt: patch.expiresAt ?? (patch.status && patch.status !== "active" ? Math.floor(this.now() / 1000) + CLOSED_META_TTL_S : Math.floor(this.now() / 1000) + ACTIVE_TTL_S),
    });
    if (!n) throw conflict("stale_state", "The conversation changed. Please reload and try again.", true);
    return n;
  }

  protected async append(c: Conversation, entries: { role: "user" | "assistant"; text: string; stage?: Stage }[]): Promise<number> {
    const msgs: Message[] = entries.map((e, i) => ({ seq: c.messageCount + i + 1, role: e.role, text: e.text, at: this.iso(), stage: e.stage ?? STAGE_OF[c.workflow] }));
    await this.d.store.addMessages(c.conversationId, msgs);
    return c.messageCount + msgs.length;
  }

  // ---- operations -------------------------------------------------------
  /** Starts a new conversation. Retrying with the same requestId returns the same conversation (no duplicates). */
  /** Hook for "Ask about this": ServiceV2 validates the referenced peer case against current eligibility. */
  protected async resolveReference(_p: Principal, _profile: ProducerProfile, _caseId: string): Promise<{ caseId: string; version: number; challenge?: string }> { throw new ApiError(400, "validation_error", "Case references are not available."); }

  async create(p: Principal, requested: Language | undefined, requestId: string, referenceCaseId?: string) {
    requireProducer(p);
    const profile = await this.profileFor(p);
    // New conversations start in the producer's preferred language unless a temporary language was requested. The profile is never modified.
    const language: Language = requested ?? profile.preferredLanguage ?? "en";
    const ref = referenceCaseId ? await this.resolveReference(p, profile, referenceCaseId) : undefined;
    const referencedCase = ref && { caseId: ref.caseId, version: ref.version };
    const scope = `owner-${p.sub}`;
    const claim = await this.d.store.claimRequest(scope, requestId, Math.floor(this.now() / 1000) + IDEM_TTL_S);
    if (claim === "pending") throw conflict("request_in_progress", "This conversation is still being started. Please wait a moment.", true);
    if (claim !== "claimed") return claim.response as Awaited<ReturnType<Service["view"]>>;
    try {
      const id = randomUUID();
      const nowIso = this.iso();
      const conv: Conversation = {
        conversationId: id, ownerSub: p.sub, producerId: profile.producerId, language, workflow: "intake",
        confirmation: "none", consent: "unanswered", status: "active", piiFlag: false, piiTypes: [],
        messageCount: 0, userTurns: 0, version: 1, createdAt: nowIso, updatedAt: nowIso, organizationId: profile.organizationId, referencedCase,
        expiresAt: Math.floor(this.now() / 1000) + ACTIVE_TTL_S,
      };
      await this.d.store.putConversation(conv);
      await this.d.store.setCurrent(p.sub, id, this.now());
      // Real agent opener; deterministic fallback so a model outage cannot block starting.
      let opener = OPENER[language];
      // The plain opener is deterministic and localized: a bare greeting makes the guardrail intervene (seen live), so calling the model for it only added latency and a failed call.
      // When asking about a colleague's case, the (already authorized, projected) case summary is part of what the producer says and the model answers it.
      if (ref?.challenge) {
        try {
          const r = await this.runAgent(conv, profile, "intake", [], `${GREETING[language]}. I would like to talk about this case: ${ref.challenge}`, false, p);
          opener = r.reply;
        } catch { this.d.metric?.("OpenerFallback"); this.log({ event: "opener_fallback", conversationId: id }); }
      }
      const count = await this.append(conv, [{ role: "assistant", text: opener }]);
      const result = await this.view(await this.save(conv, { messageCount: count }));
      await this.d.store.putIdem(scope, requestId, result, Math.floor(this.now() / 1000) + IDEM_TTL_S);
      this.log({ event: "conversation_created", conversationId: id });
      return result;
    } catch (e) {
      await this.d.store.dropRequestClaim(scope, requestId);
      throw e;
    }
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
      const count = await this.append(c, [{ role: "user", text, stage: "intake" }, { role: "assistant", text: r.reply, stage: toPlayback ? "playback" : "intake" }]);
      const saved = await this.save(c, {
        messageCount: count, userTurns: c.userTurns + 1,
        piiFlag: c.piiFlag || r.piiFlag, piiTypes: [...new Set([...c.piiTypes, ...r.piiTypes])],
        ...(toPlayback ? { workflow: "playback_pending", confirmation: "pending", playbackSummary: r.playbackSummary!, title: cleanTitle(r.title, r.playbackSummary!) } : {}),
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
          const count = await this.append(c, [{ role: "user", text: "(confirmed)", stage: "playback" }]);
          cur = await this.save(c, { workflow: "guidance_pending", confirmation: "confirmed", confirmedAccount: c.playbackSummary, messageCount: count });
        }
        const history = await this.d.store.listMessages(id);
        const r = await this.runAgent(cur, profile, "guidance", history.slice(0, -1), CONFIRMED[cur.language], false, p);
        // The model sometimes answers the guidance turn without the summary fields. The confirmed account is the producer's own text, so for English
        // conversations it is a safe summary; other languages are retried (Continue) because an English translation must not be invented.
        if (!(r.summaryEn && r.summaryOriginal) && cur.language === "en" && cur.confirmedAccount) { r.summaryEn = cur.confirmedAccount; r.summaryOriginal = cur.confirmedAccount; if (!r.challengeTags?.length) r.challengeTags = []; }
        const count2 = await this.append(cur, [{ role: "assistant", text: r.reply, stage: r.summaryEn && r.summaryOriginal ? "consent" : "response" }]);
        const saved = await this.save(cur, {
          messageCount: count2, summaryOriginal: r.summaryOriginal ?? undefined, summaryEn: r.summaryEn ?? undefined,
          challengeTags: (r.challengeTags ?? []).filter((t): t is ChallengeTag => (CHALLENGE_TAGS as readonly string[]).includes(t)).slice(0, 3),
          workflow: r.summaryEn && r.summaryOriginal ? "consent_pending" : "guidance_pending",
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
        if (pc.field === "entityType" && !(ENTITY_TYPES as readonly string[]).includes(pc.value)) throw new ApiError(400, "validation_error", "Unknown entity type.");
        assertions[pc.field] = pc.value;
        text = text || `Correction: my ${pc.field === "entityType" ? "entity type" : "location"} is ${pc.value}.`;
      }
      const history = await this.d.store.listMessages(id);
      const r = await this.runAgent(c, profile, "intake", history, text, true, p);
      const again = r.phase === "playback" && !!r.playbackSummary;
      const count = await this.append(c, [{ role: "user", text, stage: "playback" }, { role: "assistant", text: r.reply, stage: again ? "playback" : "intake" }]);
      const saved = await this.save(c, {
        messageCount: count, userTurns: c.userTurns + 1, producerAssertions: assertions,
        piiFlag: c.piiFlag || r.piiFlag, piiTypes: [...new Set([...c.piiTypes, ...r.piiTypes])],
        ...(again ? { playbackSummary: r.playbackSummary!, confirmation: "pending" as const, title: cleanTitle(r.title, r.playbackSummary!) ?? c.title } : { workflow: "intake" as const, confirmation: "none" as const }),
      });
      return this.view(saved);
    });
  }

  async consent(p: Principal, id: string, requestId: string, storeSummary: boolean) {
    return this.guarded(p, id, requestId, async (c) => {
      this.assertActive(c);
      if (c.workflow !== "consent_pending") throw conflict("wrong_state", "Storage permission is not requested yet.");
      if (storeSummary && !(c.summaryEn && c.summaryOriginal)) throw conflict("no_summary", "There is no summary to store.");
      return this.close(c, storeSummary ? "granted" : "declined", "declined_storage");
    });
  }

  /** Stopping a conversation is not deleting it: the transcript stays for the retention period and the producer can still request deletion.
   *  No FTUSA record is created (nothing was confirmed or shared); a narrative-free marker keeps reviewer statistics. */
  async end(p: Principal, id: string, requestId: string) {
    return this.guarded(p, id, requestId, async (c) => {
      if (c.status !== "active") return this.view(c);
      const profile = await this.d.store.getProfileBySub(c.ownerSub);
      await this.d.store.putOutcome({ outcomeId: `dec-${c.conversationId}`, kind: "declined", ownerSub: c.ownerSub, producerId: c.producerId, conversationId: c.conversationId,
        language: c.language, createdAt: this.iso(), producerName: profile?.displayName, declineReason: "ended_early", organizationId: c.organizationId });
      const ttl = Math.floor(this.now() / 1000) + RETENTION.completedConversationS;
      await this.d.store.retainMessages(c.conversationId, ttl);
      const saved = await this.save(c, { workflow: "closed", status: "stopped", expiresAt: ttl });
      await this.d.store.clearCurrent(c.ownerSub, c.conversationId);
      this.log({ event: "conversation_stopped", conversationId: c.conversationId });
      return this.view(saved);
    });
  }

  protected async close(c: Conversation, consent: "granted" | "declined", reason: "declined_storage" | "ended_early", extra: Partial<Outcome> = {}) {
    const profile = await this.d.store.getProfileBySub(c.ownerSub);
    const base = { outcomeId: "", ownerSub: c.ownerSub, producerId: c.producerId, conversationId: c.conversationId, language: c.language, createdAt: this.iso(),
      producerName: profile?.displayName, organizationId: c.organizationId ?? profile?.organizationId }; // identity reference only, no narrative
    if (consent === "granted") {
      const o: Outcome = {
        ...base, outcomeId: `rec-${c.conversationId}`, kind: "record", source: "agent conversation",
        entityType: profile?.entityType, crop: profile?.crop, location: profile?.location,
        summaryOriginal: c.summaryOriginal, summaryEn: c.summaryEn, challengeTags: c.challengeTags ?? [], agentChallengeTags: c.challengeTags ?? [],
        piiFlag: c.piiFlag, piiTypes: c.piiTypes, evidenceStatus: "unavailable", reviewStatus: "pending",
        sharingChoice: "ftusa_only", identityPermitted: false, publicationStatus: "not_shared", summaryVersion: 1, ...extra,
      };
      await this.d.store.putOutcome(o);
    } else {
      await this.d.store.putOutcome({ ...base, outcomeId: `dec-${c.conversationId}`, kind: "declined", declineReason: reason });
    }
    if (consent === "granted") {
      // Saved: the transcript stays readable in the producer's own history (CONV-02) for the sandbox retention period.
      await this.d.store.retainMessages(c.conversationId, Math.floor(this.now() / 1000) + SAVED_TRANSCRIPT_TTL_S);
    } else {
      // Declined: transcript, idempotency snapshots and challenge-derived title are removed; it leaves the history (CONV-04).
      await this.d.store.purgeConversation(c.conversationId, { keepMeta: true });
    }
    const saved = await this.save(c, {
      workflow: "closed", consent, status: consent === "granted" ? "completed" : "declined",
      playbackSummary: undefined, confirmedAccount: undefined, producerAssertions: undefined,
      // Saved: the confirmed summary stays with the transcript for the producer's history. Declined: nothing narrative is kept.
      // Saved: the summary and title stay until the producer deletes them (no expiry). Declined: nothing narrative is kept.
      ...(consent === "granted" ? { expiresAt: Math.floor(this.now() / 1000) + RETENTION.completedConversationS } : { title: undefined, summaryOriginal: undefined, summaryEn: undefined, challengeTags: undefined }),
    });
    await this.d.store.clearCurrent(c.ownerSub, c.conversationId);
    this.log({ event: "conversation_closed", conversationId: c.conversationId, consent });
    return this.view(saved);
  }

  /** Removes a saved conversation from the producer's own history: summary, title, transcript and snapshots.
   *  The record already shared with Fair Trade USA for review is a separate, consented record and is not changed here. */
  async deleteConversation(p: Principal, id: string) {
    const c = await this.owned(p, id);
    if (c.status === "active") throw conflict("wrong_state", "End this conversation before deleting it.");
    await this.d.store.purgeConversation(id, { keepMeta: false });
    await this.d.store.clearCurrent(p.sub, id);
    this.log({ event: "conversation_deleted", conversationId: id });
    return { deleted: true, conversationId: id };
  }

  protected assertActive(c: Conversation) { if (c.status !== "active") throw conflict("conversation_closed", "This conversation has ended."); }

  // ---- read aloud: speech for one of the caller's own agent replies (nothing is stored) -----------------
  async speech(p: Principal, id: string, seq: number) {
    const c = await this.owned(p, id); // ownership: another producer's conversation is a 404
    if (!this.d.speaker) throw new ApiError(501, "not_configured", "Read aloud is not available.");
    const m = (await this.d.store.listMessages(id)).find((x) => x.seq === seq);
    if (!m || m.role !== "assistant") throw notFound(); // only the agent's own replies are spoken
    const text = toSpokenText(m.text);
    if (!text) throw new ApiError(400, "nothing_to_say", "This message has no text to read.");
    let out: { audio: Uint8Array; voice: string };
    try { out = await this.d.speaker.speak(text, c.language); }
    catch (e) {
      this.log({ event: "speech_failure", errorName: (e as Error).name });
      throw new ApiError(502, "speech_unavailable", "We could not read this aloud just now. Please try again.", true);
    }
    this.log({ event: "speech", chars: text.length, bytes: out.audio.length }); // never the text
    return { contentType: "audio/mpeg", audio: Buffer.from(out.audio).toString("base64"), voice: out.voice, language: c.language };
  }

  // ---- dictation (stateless: audio is never stored, transcript is returned to the browser only) -------
  async transcribe(p: Principal, language: Language, audioBase64: string) {
    requireProducer(p);
    if (!this.d.transcriber) throw new ApiError(501, "not_configured", "Dictation is not available.");
    if (!/^[A-Za-z0-9+/]+={0,2}$/.test(audioBase64)) throw new ApiError(400, "audio_invalid", "The recording could not be read.");
    const pcm = Buffer.from(audioBase64, "base64");
    if (pcm.length % 2 !== 0 || pcm.length < AUDIO_MIN_BYTES) throw new ApiError(400, "audio_too_short", "The recording was too short.");
    if (pcm.length > AUDIO_MAX_BYTES) throw new ApiError(400, "audio_too_long", "The recording was too long. The limit is 60 seconds.");
    let text: string;
    try { text = await this.d.transcriber.transcribe(pcm, language); }
    catch (e) {
      this.log({ event: "transcribe_failure", errorName: (e as Error).name });
      throw new ApiError(502, "transcription_unavailable", "We could not turn that into text just now. Please try again or type.", true);
    }
    this.log({ event: "transcribed", seconds: Math.round(pcm.length / AUDIO_BYTES_PER_SECOND), chars: text.length }); // never the text
    return { text, language, syntheticDemo: true };
  }

  // ---- ask (stateless Q&A: nothing is stored) ------------------------------
  async ask(p: Principal, text: string, language: Language) {
    requireProducer(p);
    const profile = await this.profileFor(p);
    let r: AgentTurnResponse;
    try {
      r = await this.d.agent.turn({
        context: { conversationId: `ask-${randomUUID()}`, language, mode: "ask", allowPlayback: false,
          producer: { producerId: profile.producerId, entityType: profile.entityType, location: profile.location, crop: profile.crop, country: await this.countryOf(profile) }, confirmedAccount: null },
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

  // ---- review screen (spec REV-01..24); reviewer role checked on every call ---------------------------
  private outcomeKind(o: Outcome): "completed" | "declined" | "out_of_scope" { return o.kind === "record" ? "completed" : "declined"; }
  private producerInfo(o: Outcome) {
    const t = teamProducer(o.producerId);
    return { producerId: o.producerId, producerName: o.producerName ?? t?.name ?? o.producerId, entityType: o.entityType ?? t?.entityType ?? null,
      crop: o.crop ?? t?.crop ?? null, location: o.location ?? t?.location ?? null };
  }
  /** Declined records expose only producer, time, language and outcome (REV-12): no narrative, tags or claims. */
  protected recordView(o: Outcome) {
    const base = { recordId: o.outcomeId, ...this.producerInfo(o), language: o.language, createdAt: o.createdAt, outcome: this.outcomeKind(o) };
    if (o.kind !== "record") return { ...base, reviewStatus: null };
    return { ...base, source: "agent conversation" as const, reviewStatus: o.reviewStatus ?? "pending",
      summaryOriginal: o.summaryOriginal ?? o.summaryEs ?? null, summaryEn: o.summaryEn ?? null,
      challengeTags: o.challengeTags ?? [], agentChallengeTags: o.agentChallengeTags ?? o.challengeTags ?? [],
      claims: [] as unknown[], evidenceStatus: o.evidenceStatus ?? "unavailable",
      piiFlag: !!o.piiFlag, piiEntityTypes: o.piiTypes ?? [], feedbackHelpful: null as string | null, peerExampleOk: false, reasoningLogRef: null,
      reviewerNote: o.reviewerNote ?? null, reviewedBy: o.reviewedByName ?? (o.reviewedBy ? "Reviewer" : null), reviewedAt: o.reviewedAt ?? null };
  }
  async reviewStats(p: Principal) {
    requireReviewer(p);
    const all = await this.d.store.listOutcomes();
    const recs = all.filter((o) => o.kind === "record");
    const today = new Date(this.now()).toISOString().slice(0, 10);
    const n = (s: string) => recs.filter((o) => (o.reviewStatus ?? "pending") === s).length;
    return { pending: n("pending"), approved: n("approved"), corrected: n("corrected"), declined: all.filter((o) => o.kind === "declined").length,
      piiFlagged: recs.filter((o) => o.piiFlag).length, conversationsToday: all.filter((o) => o.createdAt.slice(0, 10) === today).length, asOf: this.iso() };
  }
  async reviewProducers(p: Principal, f: { q?: string; review_status?: string; outcome?: string; pii_only?: string }) {
    requireReviewer(p);
    const all = await this.d.store.listOutcomes();
    const q = (f.q ?? "").toLowerCase();
    const status = f.review_status ?? "all", outcome = f.outcome ?? "all", piiOnly = f.pii_only === "true";
    const matches = (o: Outcome) => {
      const kind = this.outcomeKind(o);
      if (outcome !== "all" && kind !== outcome) return false;
      if (status !== "all" && (o.kind !== "record" || (o.reviewStatus ?? "pending") !== status)) return false;
      if (piiOnly && !o.piiFlag) return false;
      if (!q) return true;
      const info = this.producerInfo(o);
      const hay = [info.producerName, info.producerId, o.outcomeId, ...(o.kind === "record" ? o.challengeTags ?? [] : [])].join(" ").toLowerCase();
      return hay.includes(q);
    };
    const groups = new Map<string, Outcome[]>();
    for (const o of all) { if (!groups.has(o.producerId)) groups.set(o.producerId, []); groups.get(o.producerId)!.push(o); }
    const items = [...groups.values()].filter((list) => list.some(matches)).map((list) => {
      const recs = list.filter((o) => o.kind === "record");
      return { ...this.producerInfo(list[0]), recordCount: list.length, pendingCount: recs.filter((o) => (o.reviewStatus ?? "pending") === "pending").length,
        piiFlag: recs.some((o) => o.piiFlag), latestAt: list[0].createdAt, matchingRecords: list.filter(matches).length };
    }).sort((a, b) => (b.pendingCount > 0 ? 1 : 0) - (a.pendingCount > 0 ? 1 : 0) || b.latestAt.localeCompare(a.latestAt));
    return { items };
  }
  async reviewProducerRecords(p: Principal, producerId: string) {
    requireReviewer(p);
    return { items: (await this.d.store.listOutcomes()).filter((o) => o.producerId === producerId).map((o) => this.recordView(o)) };
  }
  async reviewRelated(p: Principal, producerId: string) {
    requireReviewer(p);
    return relatedFor(producerId);
  }
  async getRecord(p: Principal, id: string) {
    requireReviewer(p);
    const o = await this.d.store.getOutcome(id);
    if (!o) throw notFound();
    return this.recordView(o);
  }
  async patchRecord(p: Principal, id: string, req: { review_status: "approved" | "corrected"; summary_original?: string; summary_en?: string; challenge_tags?: string[]; reviewer_note?: string }) {
    requireReviewer(p);
    const o = await this.d.store.getOutcome(id);
    if (!o) throw notFound();
    if (o.kind !== "record") throw conflict("not_reviewable", "Declined outcomes have nothing to review.");
    const name = p.name ?? "Reviewer";
    if (o.reviewStatus && o.reviewStatus !== "pending") {
      if (o.reviewStatus === req.review_status && o.reviewedBy === p.sub) return this.recordView(o); // retry of a completed review
      throw conflict("already_reviewed", "This record has already been reviewed.");
    }
    const patch: Partial<Outcome> = { reviewStatus: req.review_status, reviewedBy: p.sub, reviewedByName: name, reviewedAt: this.iso() };
    if (req.reviewer_note) patch.reviewerNote = req.reviewer_note;
    if (req.review_status === "corrected") {
      if (req.summary_original !== undefined) patch.summaryOriginal = req.summary_original;
      if (req.summary_en !== undefined) patch.summaryEn = req.summary_en;
      if (req.challenge_tags !== undefined) patch.challengeTags = [...new Set(req.challenge_tags)];
    }
    const n = await this.d.store.reviewOutcome(id, patch);
    if (!n) throw conflict("already_reviewed", "This record has already been reviewed.");
    this.log({ event: "review_updated", outcomeId: id, status: req.review_status });
    return this.recordView(n);
  }

  // ---- reviewer ---------------------------------------------------------
  private reviewView(o: Outcome) {
    return { outcomeId: o.outcomeId, source: o.source, producerId: o.producerId, entityType: o.entityType, language: o.language,
      summaryOriginal: o.summaryOriginal ?? o.summaryEs, summaryEn: o.summaryEn, piiFlag: o.piiFlag, piiTypes: o.piiTypes, evidenceStatus: o.evidenceStatus,
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
  async updateReview(p: Principal, id: string, req: { decision: "approve" | "correct"; correctedSummaryOriginal?: string; correctedSummaryEn?: string; piiHandled?: boolean }) {
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
      if (req.correctedSummaryOriginal) patch.summaryOriginal = req.correctedSummaryOriginal;
    }
    if (req.piiHandled) patch.piiFlag = false;
    const n = await this.d.store.reviewOutcome(id, patch);
    if (!n) throw conflict("already_reviewed", "This record has already been reviewed.");
    this.log({ event: "review_updated", outcomeId: id, status });
    return this.reviewView(n);
  }
}
