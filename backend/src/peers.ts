import type { Outcome } from "./contracts";

/** Peer case retrieval rules. Everything a producer or the model may see about another producer's case is built here, from the CURRENT authoritative record. */
export const OUTCOME_NOT_REPORTED = "Outcome not yet reported";
export interface Viewer { producerId: string; organizationId?: string }

export const caseIdOf = (o: Pick<Outcome, "outcomeId" | "publishedVersion">) => `${o.outcomeId}@${o.publishedVersion}`;
export function parseCaseId(caseId: string): { outcomeId: string; version: number } | undefined {
  const m = /^(rec-[A-Za-z0-9-]{8,80})@(\d{1,6})$/.exec(caseId);
  return m ? { outcomeId: m[1], version: Number(m[2]) } : undefined;
}

/**
 * Eligible = a different producer's record that is reviewed (approved/corrected), currently published at exactly the published version, shared beyond
 * FTUSA, and not subject to a deletion request. Pending, FTUSA-only, withdrawn, failed and awaiting-reconfirmation cases are never eligible, and
 * "do not share" is never exposed to the producer's organization as a workaround.
 */
export function isEligible(o: Outcome, v: Viewer): boolean {
  return o.kind === "record" && o.producerId !== v.producerId
    && (o.reviewStatus === "approved" || o.reviewStatus === "corrected")
    && o.publicationStatus === "published" && !!o.publication && o.publishedVersion === o.publication.version
    && (o.sharingChoice === "share_conversation" || o.sharingChoice === "share_summary")
    && !o.deletionRequestedAt;
}

export interface PeerCase {
  caseId: string; version: number; sameOrganization: boolean; origin: "your_organization" | "other_organization";
  producer: { name: string } | null; anonymousLabel: string;
  challenge: string; action: string | null; result: string; resultReported: boolean;
  tags: string[]; standards: string[]; citations: { label: string; url?: string }[]; publishedAt: string | null; illustrative: boolean;
}

/** Projection: no transcript, no ids of other producers, names only with explicit identity permission (conversation-sharing choice only). */
export function projectCase(o: Outcome, v: Viewer): PeerCase {
  const pub = o.publication!;
  const same = !!v.organizationId && o.organizationId === v.organizationId;
  const named = o.identityPermitted === true && o.sharingChoice === "share_conversation" && !!(o.confirmedByName ?? o.producerName);
  return {
    caseId: caseIdOf(o), version: pub.version, sameOrganization: same, origin: same ? "your_organization" : "other_organization",
    producer: named ? { name: (o.confirmedByName ?? o.producerName)! } : null,
    anonymousLabel: same ? "A producer in your organization" : "A producer in another organization",
    challenge: pub.payload.challenge, action: pub.payload.action, result: pub.payload.result ?? OUTCOME_NOT_REPORTED, resultReported: !!pub.payload.result,
    tags: pub.payload.tags, standards: pub.payload.standards, citations: pub.payload.citations, publishedAt: o.publishedAt ?? null, illustrative: true,
  };
}
