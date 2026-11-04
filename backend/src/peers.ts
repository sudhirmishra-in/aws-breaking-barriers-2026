import type { Outcome } from "./contracts";

/** Peer case retrieval rules. Everything a producer or the model may see about another producer's case is built here, from the CURRENT authoritative record. */
export const OUTCOME_NOT_REPORTED = "Outcome not yet reported";
export interface Viewer { producerId: string; organizationId?: string }

/** Producer-confirmed text of a record: never a reviewer revision that the producer has not confirmed. */
export function confirmedSummary(o: Outcome): { original: string; en: string } {
  const v = [...(o.versions ?? [])].reverse().find((x) => x.kind === "producer_confirmed");
  return { original: v?.summaryOriginal ?? o.summaryOriginal ?? "", en: v?.summaryEn ?? o.summaryEn ?? "" };
}
export const versionOf = (o: Pick<Outcome, "publishedVersion" | "summaryVersion">) => o.publishedVersion ?? o.summaryVersion ?? 1;
export const caseIdOf = (o: Pick<Outcome, "outcomeId" | "publishedVersion" | "summaryVersion">) => `${o.outcomeId}@${versionOf(o)}`;
export function parseCaseId(caseId: string): { outcomeId: string; version: number } | undefined {
  const m = /^(rec-[A-Za-z0-9-]{8,80})@(\d{1,6})$/.exec(caseId);
  return m ? { outcomeId: m[1], version: Number(m[2]) } : undefined;
}

const hasRecord = (o: Outcome, v: Viewer) => o.kind === "record" && o.producerId !== v.producerId && !o.deletionRequestedAt;

/**
 * Same organization: colleagues' confirmed SUMMARIES are visible whatever sharing choice was made ("do not share" limits other organizations and
 * the conversation itself, not the organization's view of what its own members are working on). Never the transcript. Records with a PII flag stay
 * hidden until a reviewer clears them.
 */
export function isOrgVisible(o: Outcome, v: Viewer): boolean {
  return hasRecord(o, v) && !!v.organizationId && o.organizationId === v.organizationId && !o.piiFlag && confirmedSummary(o).en !== "";
}

/**
 * Other organizations: reviewed, currently published at exactly the published version, shared beyond FTUSA, no deletion request. Pending,
 * FTUSA-only, withdrawn, failed and awaiting-reconfirmation cases are never visible outside the organization.
 */
export function isEligible(o: Outcome, v: Viewer): boolean {
  if (isOrgVisible(o, v)) return true;
  return hasRecord(o, v)
    && (o.reviewStatus === "approved" || o.reviewStatus === "corrected")
    && o.publicationStatus === "published" && !!o.publication && o.publishedVersion === o.publication.version
    && (o.sharingChoice === "share_conversation" || o.sharingChoice === "share_summary");
}

export interface PeerCase {
  caseId: string; version: number; sameOrganization: boolean; origin: "your_organization" | "other_organization";
  visibility: "published" | "organization_only"; language?: string; summaryOriginal?: string;
  producer: { name: string } | null; anonymousLabel: string;
  challenge: string; action: string | null; result: string; resultReported: boolean;
  tags: string[]; standards: string[]; citations: { label: string; url?: string }[]; publishedAt: string | null; illustrative: boolean;
}

/** Projection: no transcript, no ids of other producers, names only with explicit identity permission (conversation-sharing choice only). */
export function projectCase(o: Outcome, v: Viewer): PeerCase {
  const same = !!v.organizationId && o.organizationId === v.organizationId;
  const published = o.publicationStatus === "published" && !!o.publication && (o.sharingChoice === "share_conversation" || o.sharingChoice === "share_summary");
  const named = o.identityPermitted === true && o.sharingChoice === "share_conversation" && !!(o.confirmedByName ?? o.producerName);
  const c = confirmedSummary(o);
  const pay = published ? o.publication!.payload : { challenge: c.en, action: o.caseCard?.action ?? null, result: o.caseCard?.result ?? null, tags: o.challengeTags ?? [], standards: o.caseCard?.standards ?? [], citations: o.caseCard?.citations ?? [] };
  return {
    caseId: caseIdOf(o), version: versionOf(o), sameOrganization: same, origin: same ? "your_organization" : "other_organization",
    visibility: published ? "published" : "organization_only", language: o.language, summaryOriginal: same ? c.original : undefined,
    producer: named ? { name: (o.confirmedByName ?? o.producerName)! } : null,
    anonymousLabel: same ? "A producer in your organization" : "A producer in another organization",
    challenge: pay.challenge, action: pay.action, result: pay.result ?? OUTCOME_NOT_REPORTED, resultReported: !!pay.result,
    tags: pay.tags, standards: pay.standards, citations: pay.citations, publishedAt: o.publishedAt ?? o.confirmedAt ?? null, illustrative: true,
  };
}
