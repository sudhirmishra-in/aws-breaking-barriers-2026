import { createHash } from "node:crypto";
import type { CorrectionRecord, CorrectableField, Organization, Outcome, ProducerProfile, Publication, SharingChoice, SummaryVersion } from "./contracts";
import { SYNTHETIC_LABEL } from "./contracts";
import { ApiError, conflict, notFound } from "./errors";
import { evidenceFor } from "./evidence";
import { isoOf, LocalProjectRetriever, projectEvidence } from "./projectEvidence";
import { isEligible, parseCaseId, projectCase, versionOf, type Viewer } from "./peers";
import { RETENTION, requireProducer, requireReviewer, Service, summaryHashOf, type Principal } from "./service";

/** Source columns for the producer-information view. Source meanings are preserved; the browser translates labels only. */
export const INFO_FIELDS = ["account_sk", "account_category_name", "product_category_name", "account_type_name", "certification_scope_name",
  "certification_status_name", "country_name", "raw_supply_chain_role_txt", "structure_txt"] as const;
type InfoKey = (typeof INFO_FIELDS)[number];
const CAMEL: Record<InfoKey, keyof Organization["info"]> = {
  account_sk: "accountSk", account_category_name: "accountCategoryName", product_category_name: "productCategoryName", account_type_name: "accountTypeName",
  certification_scope_name: "certificationScopeName", certification_status_name: "certificationStatusName", country_name: "countryName",
  raw_supply_chain_role_txt: "rawSupplyChainRoleTxt", structure_txt: "structureTxt",
};
const flat = (v: string | string[] | null | undefined): string | null => (Array.isArray(v) ? (v.length ? v.join("; ") : null) : v ?? null);
const sha = (...parts: string[]) => createHash("sha256").update(JSON.stringify(parts)).digest("hex");
const OPEN_CORRECTION: CorrectionRecord["status"][] = ["pending", "accepted_awaiting_source_update"];

export const DELETION_NOTE = "Publication is withdrawn now and no new answers will use this case. FTUSA will review deletion of the retained record. Answers already given are not recalled.";
export const VISIBILITY_NOTE = "You see the summaries of colleagues in your organization, whatever they chose to share, but never their conversations. Producers in other organizations appear only if they chose to share and FTUSA approved. Names appear only when the producer allowed it.";

export class ServiceV2 extends Service {
  // ---- producer information and corrections ----------------------------------------------------------------------------
  private async orgFor(profile: ProducerProfile): Promise<Organization | undefined> {
    return profile.organizationId ? this.d.store.getOrganization(profile.organizationId) : undefined;
  }

  /** "Your producer information": individual details (and preferred language) are separate from shared organization attributes. Read-only. */
  async producerInformation(p: Principal) {
    requireProducer(p);
    const profile = await this.profileFor(p);
    const org = await this.orgFor(profile);
    const fields = org ? Object.fromEntries(INFO_FIELDS.map((k) => { const v = org.info[CAMEL[k]]; return [k, Array.isArray(v) ? v : v ?? null]; })) : null;
    const pending = org ? (await this.d.store.listCorrections({ organizationId: org.organizationId })).filter((c) => OPEN_CORRECTION.includes(c.status)) : [];
    return {
      individual: { producerId: profile.producerId, displayName: profile.displayName, preferredLanguage: profile.preferredLanguage ?? "en" },
      organization: org ? { organizationId: org.organizationId, name: org.name, fields } : null,
      summary: { products: org?.info.productCategoryName ?? [], country: org?.info.countryName ?? null },
      // Pending corrections are proposals, not verified facts. The explanation is shown only to the person who wrote it.
      pendingCorrections: pending.map((c) => this.correctionView(c, c.requesterSub === p.sub)),
      correctableFields: INFO_FIELDS.filter((k) => k !== "account_sk"),
      verified: false as const, syntheticDemo: true,
    };
  }

  private correctionView(c: CorrectionRecord, own: boolean) {
    return { correctionId: c.correctionId, status: c.status, createdAt: c.createdAt, requestedByYou: own, changes: c.changes,
      explanation: own ? c.explanation ?? null : null, decidedAt: c.decidedAt ?? null, appliedAt: c.appliedAt ?? null, decisionNote: own ? c.decisionNote ?? null : null };
  }

  /** Submit a correction request. Source records are never touched; current values come from the server, not the browser. */
  async createCorrection(p: Principal, req: { requestId: string; changes: { field: CorrectableField; proposed: string }[]; explanation?: string }) {
    requireProducer(p);
    const profile = await this.profileFor(p);
    const org = await this.orgFor(profile);
    if (!org) throw new ApiError(403, "no_organization", "No organization is linked to this account.");
    const id = `corr-${profile.producerId}-${req.requestId}`;
    const now = this.iso();
    const changes = req.changes.map((c) => ({ field: c.field, original: flat(org.info[CAMEL[c.field]] as string | string[] | null), proposed: c.proposed }));
    for (const c of changes) if (c.original === c.proposed) throw new ApiError(400, "validation_error", "The proposed value is the same as the recorded value.");
    const rec: CorrectionRecord = { correctionId: id, organizationId: org.organizationId, requesterProducerId: profile.producerId, requesterSub: p.sub,
      createdAt: now, updatedAt: now, changes, explanation: req.explanation, status: "pending" };
    if (!(await this.d.store.putCorrection(rec))) {
      const ex = await this.d.store.getCorrection(id);
      if (!ex || ex.requesterSub !== p.sub) throw conflict("request_in_progress", "This request id is already in use.");
      return this.correctionView(ex, true); // retry: same request, same result
    }
    this.log({ event: "correction_submitted", correctionId: id });
    return this.correctionView(rec, true);
  }

  async listMyCorrections(p: Principal) {
    requireProducer(p);
    const profile = await this.profileFor(p);
    const items = profile.organizationId ? await this.d.store.listCorrections({ organizationId: profile.organizationId }) : [];
    return { items: items.filter((c) => c.requesterSub === p.sub).map((c) => this.correctionView(c, true)) };
  }

  async reviewCorrections(p: Principal, status?: string) {
    requireReviewer(p);
    const all = await this.d.store.listCorrections({});
    return { items: all.filter((c) => !status || status === "all" || c.status === status).map((c) => ({ ...this.correctionView(c, true),
      organizationId: c.organizationId, requesterProducerId: c.requesterProducerId, decidedBy: c.decidedBy ?? null })) };
  }

  /** accept -> accepted_awaiting_source_update; mark_applied -> applied (recorded after the source table was updated elsewhere); reject. Reviewer is server-derived. */
  async decideCorrection(p: Principal, id: string, req: { decision: "accept" | "reject" | "mark_applied"; note?: string }) {
    requireReviewer(p);
    const cur = await this.d.store.getCorrection(id);
    if (!cur) throw notFound();
    const target: CorrectionRecord["status"] = req.decision === "accept" ? "accepted_awaiting_source_update" : req.decision === "reject" ? "rejected" : "applied";
    const from: CorrectionRecord["status"][] = req.decision === "mark_applied" ? ["accepted_awaiting_source_update"] : ["pending"];
    const who = p.name ?? p.sub;
    if (cur.status === target && cur.decidedBy === who) return this.correctionView(cur, true); // retry of the same decision
    const now = this.iso();
    const n = await this.d.store.updateCorrection(id, from, { status: target, updatedAt: now, decidedBy: who, decidedAt: now,
      ...(req.note ? { decisionNote: req.note } : {}), ...(target === "applied" ? { appliedAt: now } : {}) });
    if (!n) throw conflict("already_decided", "This request has already been decided or is not in a state that allows this decision.");
    this.log({ event: "correction_decided", correctionId: id, status: target });
    return this.correctionView(n, true);
  }

  override async reviewStats(p: Principal) {
    const base = await super.reviewStats(p);
    return { ...base, correctionsPending: (await this.d.store.listCorrections({})).filter((c) => c.status === "pending").length };
  }

  // ---- finalize: confirmation + sharing (replaces the old "save or delete" consent question) ------------------------------
  /** Confirms exactly the summary the producer saw (hash) and records the sharing choice. Every finalized record enters FTUSA review, FTUSA-only included. */
  async finalize(p: Principal, id: string, req: { requestId: string; summaryHash: string; sharing: SharingChoice; identityPermitted: boolean }) {
    return this.guarded(p, id, req.requestId, async (c) => {
      this.assertActive(c);
      if (c.workflow !== "consent_pending" || !(c.summaryEn && c.summaryOriginal)) throw conflict("wrong_state", "There is no summary to confirm right now.");
      const hash = summaryHashOf(c);
      if (req.summaryHash !== hash) throw conflict("stale_confirmation", "The summary changed since you reviewed it. Please review the current version.", true);
      const profile = await this.profileFor(p);
      const now = this.iso();
      const v1: SummaryVersion = { version: 1, kind: "producer_confirmed", summaryOriginal: c.summaryOriginal, summaryEn: c.summaryEn, hash, at: now, by: profile.producerId };
      return this.close(c, "granted", "declined_storage", {
        organizationId: profile.organizationId, sharingChoice: req.sharing, identityPermitted: req.sharing === "share_conversation" && req.identityPermitted,
        confirmationHash: hash, confirmedAt: now, confirmedByProducerId: profile.producerId, confirmedByName: profile.displayName,
        summaryVersion: 1, versions: [v1], publicationStatus: req.sharing === "ftusa_only" ? "not_shared" : "awaiting_review",
        ttl: Math.floor(this.now() / 1000) + RETENTION.recordS,
      });
    });
  }

  private async ownRecord(p: Principal, conversationId: string): Promise<Outcome> {
    requireProducer(p);
    const c = await this.d.store.getConversation(conversationId);
    if (!c || c.ownerSub !== p.sub) throw notFound();
    const o = await this.d.store.getOutcome(`rec-${conversationId}`);
    if (!o || o.kind !== "record" || o.ownerSub !== p.sub) throw notFound();
    return o;
  }

  /** Change who can see the finalized case. Narrowing takes effect immediately because peer retrieval checks the authoritative record on every call. */
  async updateSharing(p: Principal, conversationId: string, req: { sharing: SharingChoice; identityPermitted: boolean }) {
    const o = await this.ownRecord(p, conversationId);
    if (o.deletionRequestedAt) throw conflict("deletion_requested", "A deletion request is open for this record.");
    const identity = req.sharing === "share_conversation" && req.identityPermitted;
    const patch: Partial<Outcome> = { sharingChoice: req.sharing, identityPermitted: identity };
    const st = o.publicationStatus ?? "not_shared";
    if (req.sharing === "ftusa_only") patch.publicationStatus = ["published", "pending_publication", "failed"].includes(st) ? "withdrawn" : "not_shared";
    else if (st === "not_shared" || st === "withdrawn") {
      if (o.reviewStatus === "pending" || !o.reviewStatus) patch.publicationStatus = "awaiting_review";
      else { patch.publicationStatus = "pending_publication"; patch.publication = this.buildPublication({ ...o, ...patch } as Outcome, o.reviewedBy ?? "reviewer"); }
    }
    const n = await this.d.store.updateOutcome(o.outcomeId, null, patch);
    if (!n) throw notFound();
    this.log({ event: "sharing_updated", outcomeId: o.outcomeId, sharing: req.sharing });
    return this.sharingState(n.publicationStatus === "pending_publication" ? await this.runPublication(n) : n);
  }
  private sharingState(o: Outcome) {
    return { sharingChoice: o.sharingChoice ?? "ftusa_only", identityPermitted: !!o.identityPermitted, reviewStatus: o.reviewStatus ?? "pending", publicationStatus: o.publicationStatus ?? "not_shared" };
  }

  /** Request deletion of the retained record: publication is withdrawn at once (retrieval is blocked); FTUSA fulfils the deletion. Answers already delivered are not recalled. */
  async requestDeletion(p: Principal, conversationId: string) {
    const o = await this.ownRecord(p, conversationId);
    if (o.deletionRequestedAt) return { ...this.sharingState(o), deletionRequested: true, note: DELETION_NOTE };
    const n = await this.d.store.updateOutcome(o.outcomeId, null, { deletionRequestedAt: this.iso(), publicationStatus: "withdrawn", sharingChoice: "ftusa_only", identityPermitted: false });
    this.log({ event: "deletion_requested", outcomeId: o.outcomeId });
    return { ...this.sharingState(n ?? o), deletionRequested: true, note: DELETION_NOTE };
  }

  /** Producer answers a reviewer's material change to the summary. Accept publishes the revision as producer-confirmed; decline publishes the original confirmed version. */
  async reconfirm(p: Principal, conversationId: string, req: { summaryHash: string; accept: boolean }) {
    const o = await this.ownRecord(p, conversationId);
    if (o.publicationStatus !== "awaiting_reconfirmation" || !o.pendingRevision) throw conflict("wrong_state", "Nothing needs re-confirmation.");
    if (o.pendingRevision.hash !== req.summaryHash) throw conflict("stale_confirmation", "The proposed summary changed. Please review the current version.", true);
    const now = this.iso(); const versions = [...(o.versions ?? [])];
    let patch: Partial<Outcome>;
    if (req.accept) {
      versions.push({ ...o.pendingRevision, kind: "producer_confirmed", at: now, by: o.producerId });
      patch = { versions, pendingRevision: undefined, confirmationHash: o.pendingRevision.hash, confirmedAt: now };
    } else {
      const orig = [...versions].reverse().find((v) => v.kind === "producer_confirmed")!;
      patch = { summaryOriginal: orig.summaryOriginal, summaryEn: orig.summaryEn, summaryVersion: orig.version, pendingRevision: undefined, versions };
    }
    const n = await this.d.store.updateOutcome(o.outcomeId, ["awaiting_reconfirmation"], { ...patch, publicationStatus: "pending_publication",
      publication: this.buildPublication({ ...o, ...patch } as Outcome, o.reviewedBy ?? "reviewer") });
    if (!n) return this.sharingState((await this.d.store.getOutcome(o.outcomeId)) ?? o); // a concurrent retry already moved it
    return this.sharingState(await this.runPublication(n));
  }

  // ---- publication (specifically approved, permission-filtered payload; idempotent; failures are visible) -------------------
  private buildPublication(o: Outcome, approvedBy: string): Publication {
    // Built only from producer-confirmed content plus the reviewer's case card. Transcripts are never read here.
    return { version: (o.publication?.version ?? 0) + 1, approvedBy, approvedAt: this.iso(),
      payload: { challenge: o.summaryEn ?? "", action: o.caseCard?.action ?? null, result: o.caseCard?.result ?? null, tags: o.challengeTags ?? [],
        standards: o.caseCard?.standards ?? [], citations: o.caseCard?.citations ?? [] } };
  }

  /** The publisher. Safe to repeat: an already-published record is returned unchanged; failure leaves "failed", never "published". */
  async runPublication(o: Outcome): Promise<Outcome> {
    const cur = (await this.d.store.getOutcome(o.outcomeId)) ?? o;
    if (cur.publicationStatus === "published") return cur;
    if (cur.publicationStatus !== "pending_publication" && cur.publicationStatus !== "failed") return cur;
    if (!cur.publication) throw conflict("not_approved", "No approved publication payload exists.");
    try {
      await this.d.publishSideEffect?.(cur); // derived-memory/index update hooks in here; a failure keeps the record unpublished
      const n = await this.d.store.updateOutcome(cur.outcomeId, ["pending_publication", "failed"],
        { publicationStatus: "published", publishedVersion: cur.publication.version, publishedAt: this.iso(), publishError: undefined });
      return n ?? (await this.d.store.getOutcome(cur.outcomeId)) ?? cur;
    } catch (e) {
      this.log({ event: "publication_failed", outcomeId: cur.outcomeId, errorName: (e as Error).name });
      return (await this.d.store.updateOutcome(cur.outcomeId, ["pending_publication", "failed"], { publicationStatus: "failed", publishError: (e as Error).name })) ?? cur;
    }
  }
  async retryPublication(p: Principal, id: string) {
    requireReviewer(p);
    const o = await this.d.store.getOutcome(id);
    if (!o || o.kind !== "record") throw notFound();
    return this.recordView(await this.runPublication(o));
  }

  override async patchRecord(p: Principal, id: string, req: { review_status: "approved" | "corrected"; summary_original?: string; summary_en?: string; challenge_tags?: string[]; reviewer_note?: string; case_card?: Outcome["caseCard"] }) {
    requireReviewer(p);
    const o = await this.d.store.getOutcome(id);
    if (!o) throw notFound();
    if (o.kind !== "record") throw conflict("not_reviewable", "Declined outcomes have nothing to review.");
    if (o.reviewStatus && o.reviewStatus !== "pending") {
      if (o.reviewStatus === req.review_status && o.reviewedBy === p.sub) return this.recordView(await this.runPublication(o)); // retry of a completed review
      throw conflict("already_reviewed", "This record has already been reviewed.");
    }
    const patch: Partial<Outcome> = { reviewStatus: req.review_status, reviewedBy: p.sub, reviewedByName: p.name ?? "Reviewer", reviewedAt: this.iso() };
    if (req.reviewer_note) patch.reviewerNote = req.reviewer_note;
    if (req.case_card) patch.caseCard = req.case_card;
    let revised: SummaryVersion | undefined;
    if (req.review_status === "corrected") {
      if (req.challenge_tags !== undefined) patch.challengeTags = [...new Set(req.challenge_tags)];
      const so = req.summary_original ?? o.summaryOriginal ?? "", se = req.summary_en ?? o.summaryEn ?? "";
      if (so !== (o.summaryOriginal ?? "") || se !== (o.summaryEn ?? "")) {
        // The producer-confirmed version stays in `versions`; the revision is a new version that must be re-confirmed before publication.
        revised = { version: (o.summaryVersion ?? 1) + 1, kind: "reviewer_revision", summaryOriginal: so, summaryEn: se, hash: sha(so, se), at: this.iso(), by: p.sub };
        Object.assign(patch, { summaryOriginal: so, summaryEn: se, summaryVersion: revised.version, versions: [...(o.versions ?? []), revised] });
      }
    }
    const shared = o.sharingChoice === "share_conversation" || o.sharingChoice === "share_summary";
    if (!shared) patch.publicationStatus = o.deletionRequestedAt ? "withdrawn" : "not_shared";
    else if (o.deletionRequestedAt) patch.publicationStatus = "withdrawn";
    else if (revised) { patch.publicationStatus = "awaiting_reconfirmation"; patch.pendingRevision = revised; }
    else { patch.publicationStatus = "pending_publication"; patch.publication = this.buildPublication({ ...o, ...patch } as Outcome, p.sub); }
    const n = await this.d.store.reviewOutcome(id, patch);
    if (!n) throw conflict("already_reviewed", "This record has already been reviewed.");
    this.log({ event: "review_updated", outcomeId: id, status: req.review_status });
    return this.recordView(n.publicationStatus === "pending_publication" ? await this.runPublication(n) : n);
  }

  protected override recordView(o: Outcome) {
    const base = super.recordView(o);
    if (o.kind !== "record") return base;
    return { ...base, organizationId: o.organizationId ?? null, sharingChoice: o.sharingChoice ?? "ftusa_only", identityPermitted: !!o.identityPermitted,
      publicationStatus: o.publicationStatus ?? "not_shared", publishedVersion: o.publishedVersion ?? null, publishError: o.publishError ?? null,
      summaryVersion: o.summaryVersion ?? 1, summaryVersions: o.versions ?? [], pendingRevision: o.pendingRevision ?? null, caseCard: o.caseCard ?? null,
      publicationPreview: o.publication?.payload ?? null,
      confirmation: o.confirmedAt ? { hash: o.confirmationHash ?? null, at: o.confirmedAt, byProducerId: o.confirmedByProducerId ?? null } : null,
      deletionRequested: !!o.deletionRequestedAt, feedbackHelpful: o.feedback?.helpful ?? null, feedbackComment: o.feedback?.comment ?? null };
  }

  /** Helpfulness feedback on the finished conversation. Safe to repeat: the latest answer replaces the previous one. */
  async feedback(p: Principal, conversationId: string, req: { helpful: "yes" | "partly" | "no"; comment?: string }) {
    const o = await this.ownRecord(p, conversationId);
    await this.d.store.updateOutcome(o.outcomeId, null, { feedback: { helpful: req.helpful, ...(req.comment ? { comment: req.comment } : {}), at: this.iso() } });
    this.log({ event: "feedback", helpful: req.helpful });
    return { helpful: req.helpful };
  }

  /** Evidence for one of the caller's own finalized conversations. Missing evidence is reported as a limitation, never invented. */
  async evidence(p: Principal, conversationId: string) {
    const o = await this.ownRecord(p, conversationId);
    const profile = await this.profileFor(p);
    const org = await this.orgFor(profile);
    const items = evidenceFor(org?.info.countryName ?? null, o.challengeTags ?? []);
    // Public project records: scope (country, crop) comes from the caller's own organization and record, never from the request.
    const hits = await (this.d.projects ?? new LocalProjectRetriever()).search({ text: `${o.summaryEn ?? ""} ${(o.challengeTags ?? []).join(" ")}`,
      countryIso2: isoOf(org?.info.countryName), crop: (o.crop ?? profile.crop) || null, limit: 3 }).catch(() => []);
    const projects = hits.map((h) => projectEvidence(h.project));
    return { items, projects, limitation: items.length || projects.length ? null : "No prepared evidence matches this topic and location.", syntheticDemo: true };
  }

  // ---- peers ------------------------------------------------------------------------------------------------------------------
  private async viewer(p: Principal): Promise<Viewer> {
    requireProducer(p);
    const profile = await this.profileFor(p);
    return { producerId: profile.producerId, organizationId: profile.organizationId };
  }

  /** Eligible approved, sharing-permitted summaries from other producers: same organization and/or other organizations. Never transcripts. */
  async peerSummaries(p: Principal, scope: "organization" | "other" | "all" = "organization") {
    const v = await this.viewer(p);
    const seen = new Map<string, Outcome>();
    if (scope !== "other" && v.organizationId) for (const o of await this.d.store.listRecordsByOrganization(v.organizationId)) seen.set(o.outcomeId, o);
    if (scope !== "organization") for (const o of await this.d.store.listPublishedRecords()) if (!v.organizationId || o.organizationId !== v.organizationId) seen.set(o.outcomeId, o);
    const items = [...seen.values()].filter((o) => isEligible(o, v)).sort((a, b) => (b.publishedAt ?? b.confirmedAt ?? "").localeCompare(a.publishedAt ?? a.confirmedAt ?? "")).map((o) => projectCase(o, v));
    return { items, syntheticLabel: SYNTHETIC_LABEL, visibility: VISIBILITY_NOTE };
  }

  /**
   * "What others have done" for one of the caller's own finalized conversations. Only comparable cases: same crop AND at least one shared challenge tag
   * (scope is derived server-side from the caller's own record, never from the browser). Ranked: same organization, same country, shared tags, a reported result.
   */
  async relatedCases(p: Principal, conversationId: string) {
    const own = await this.ownRecord(p, conversationId);
    const profile = await this.profileFor(p);
    const org = await this.orgFor(profile);
    const v: Viewer = { producerId: profile.producerId, organizationId: profile.organizationId };
    const crop = (own.crop ?? profile.crop ?? "").toLowerCase(); const tags = own.challengeTags ?? [];
    const country = (org?.info.countryName ?? "").toLowerCase();
    const pool = new Map<string, Outcome>();
    if (v.organizationId) for (const o of await this.d.store.listRecordsByOrganization(v.organizationId)) pool.set(o.outcomeId, o);
    for (const o of await this.d.store.listPublishedRecords()) pool.set(o.outcomeId, o);
    // 1. Application code decides what the model may see: authorized, projected cases of the same crop. Tag overlap only ranks; meaning is judged by the agent.
    const cands = [...pool.values()].filter((o) => o.outcomeId !== own.outcomeId && isEligible(o, v) && !!crop && (o.crop ?? "").toLowerCase() === crop).map((o) => {
      const c = projectCase(o, v); const shared = c.tags.filter((t) => tags.includes(t));
      const sameCountry = !!country && (o.location ?? "").toLowerCase().includes(country);
      return { c, shared, sameCountry, score: (c.sameOrganization ? 3 : 0) + (sameCountry ? 2 : 0) + shared.length * 2 + (c.resultReported ? 1 : 0) };
    }).sort((a, b) => b.score - a.score).slice(0, 25);
    const why = (x: (typeof cands)[number]) => [`Same crop: ${crop}`, ...(x.shared.length ? [`Same challenge: ${x.shared.join(", ")}`] : []), ...(x.c.sameOrganization ? ["Your organization"] : []), ...(x.sameCountry ? [`Same country: ${org!.info.countryName}`] : [])];
    let picked: { c: (typeof cands)[number]["c"]; relevance: string[]; fit?: "strong" | "partial"; reason?: string }[] = [];
    let matchedBy: "agent" | "rules" = "agent";
    if (cands.length && this.d.agent.match) {
      try {
        const r = await this.d.agent.match({ task: "match", language: own.language, producer: { producerId: profile.producerId, entityType: profile.entityType, location: profile.location, crop: profile.crop },
          account: (own.summaryEn ?? "").slice(0, 2000), tags,
          candidates: cands.map((x) => ({ caseId: x.c.caseId, challenge: x.c.challenge, action: x.c.action, result: x.c.resultReported ? x.c.result : null, tags: x.c.tags, sameOrganization: x.c.sameOrganization, sameCountry: x.sameCountry })) },
          `ftusa-match-${sha(conversationId).slice(0, 40)}`, p.sub); // AgentCore needs a session id of at least 33 characters
        // 2. The model only ranks: unknown or duplicate ids are dropped, so it can never introduce a case.
        const byId = new Map(cands.map((x) => [x.c.caseId, x]));
        const seen = new Set<string>();
        for (const m of r.matches ?? []) { const x = byId.get(m.caseId); if (x && !seen.has(m.caseId)) { seen.add(m.caseId); picked.push({ c: x.c, relevance: why(x), fit: m.fit, reason: m.reason }); } }
        picked = picked.slice(0, 3);
      } catch { this.log({ event: "match_failure" }); matchedBy = "rules"; picked = []; }
    } else matchedBy = "rules";
    if (matchedBy === "rules") picked = cands.filter((x) => x.shared.length).slice(0, 3).map((x) => ({ c: x.c, relevance: why(x) })); // deterministic fallback
    return { items: picked.map((x) => ({ ...x.c, relevance: x.relevance, fit: x.fit ?? null, reason: x.reason ?? null })), crop, tags, matchedBy, considered: cands.length,
      limitation: picked.length ? null : `No close match yet for ${crop || "this crop"} and this problem.` };
  }

  async peerCase(p: Principal, caseId: string) {
    const v = await this.viewer(p);
    const ref = parseCaseId(caseId);
    const o = ref ? await this.d.store.getOutcome(ref.outcomeId) : undefined;
    // Exact version, current status and permissions are re-checked on every call; stale and withdrawn cases look the same as missing ones.
    if (!ref || !o || !isEligible(o, v) || versionOf(o) !== ref.version) throw new ApiError(404, "case_unavailable", "This case is no longer available.");
    return projectCase(o, v);
  }

  protected override async resolveReference(p: Principal, _profile: ProducerProfile, caseId: string) {
    const c = await this.peerCase(p, caseId).catch(() => { throw new ApiError(409, "case_unavailable", "This case is no longer available."); });
    return { caseId: c.caseId, version: c.version, challenge: c.challenge };
  }

  /** The referenced case as the viewer may see it now (re-checked on every view; null once it is withdrawn). */
  protected override async referenceCard(c: { ownerSub: string; referencedCase?: { caseId: string } }) {
    try { return await this.peerCase({ sub: c.ownerSub, groups: ["producer"] }, c.referencedCase!.caseId); } catch { return null; }
  }
}
