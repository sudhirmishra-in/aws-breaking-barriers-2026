import type { IssueEvent, IssueRecord, IssueStatus } from "./contracts";

/** Pure issue-history rules. Nothing here marks an issue resolved because advice was given or a conversation ended. */
export const SAME_INCIDENT_DAYS = 45;
const DAY = 86_400_000;

export function deriveStatus(events: IssueEvent[]): IssueStatus {
  const live = events.filter((e) => !events.some((o) => o.supersedes === e.eventId)); // a superseded fact stays in history but no longer counts
  const t = (type: IssueEvent["type"]) => live.filter((e) => e.type === type).map((e) => e.at).sort();
  const last = (a: string[]) => (a.length ? a[a.length - 1] : "");
  const resolved = last(t("resolution_confirmed")), recurrence = last(t("recurrence")), outcome = last(t("outcome"));
  if (recurrence && recurrence > resolved) return "recurring";
  if (resolved) return "resolved"; // only an explicit, dated confirmation
  if (t("action").length) return outcome && outcome > last(t("action")) ? "unknown" : "action_in_progress"; // an outcome is not a verified resolution
  if (t("action_planned").length) return "action_planned";
  return "open";
}

export function withEvent(issue: IssueRecord, ev: IssueEvent): IssueRecord {
  if (issue.events.some((e) => e.eventId === ev.eventId)) return issue; // idempotent: a retry changes nothing
  const events = [...issue.events, ev].sort((a, b) => a.at.localeCompare(b.at) || a.eventId.localeCompare(b.eventId));
  const reporters = ev.producerId && !issue.reportingProducerIds.includes(ev.producerId) ? [...issue.reportingProducerIds, ev.producerId] : issue.reportingProducerIds;
  const reported = events.filter((e) => e.type === "reported" || e.type === "recurrence").map((e) => e.at);
  return { ...issue, events, reportingProducerIds: reporters, status: deriveStatus(events), version: issue.version + 1,
    lastReportedAt: reported.length ? reported[reported.length - 1] : issue.lastReportedAt,
    linkedConversations: ev.conversationId && !issue.linkedConversations.includes(ev.conversationId) ? [...issue.linkedConversations, ev.conversationId] : issue.linkedConversations };
}

export interface Candidate { issue: IssueRecord; sameProducer: boolean; sharedTags: string[]; daysSince: number }
/**
 * A matching tag alone never establishes the same incident. Auto-link only when the same producer, same crop, a shared tag, and a recent, unresolved issue all agree.
 * Anything else that shares crop and a tag is a candidate the producer is asked about.
 */
export function matchIssue(issues: IssueRecord[], q: { producerId: string; tags: string[]; crop: string; nowMs: number }): { link?: IssueRecord; candidates: Candidate[] } {
  const cands: Candidate[] = [];
  for (const i of issues) {
    if (i.crop.toLowerCase() !== q.crop.toLowerCase()) continue;
    const sharedTags = i.tags.filter((t) => q.tags.includes(t));
    if (!sharedTags.length) continue;
    cands.push({ issue: i, sameProducer: i.reportingProducerIds.includes(q.producerId), sharedTags, daysSince: Math.floor((q.nowMs - Date.parse(i.lastReportedAt)) / DAY) });
  }
  cands.sort((a, b) => a.daysSince - b.daysSince);
  const link = cands.find((c) => c.sameProducer && c.daysSince <= SAME_INCIDENT_DAYS && c.issue.status !== "resolved")?.issue;
  return { link, candidates: link ? [] : cands.slice(0, 3) };
}

/** What other members of the organization may see: no producer ids, dated events, synthetic flag preserved. */
export function issueView(i: IssueRecord) {
  return { issueId: i.issueId, description: i.description, tags: i.tags, crop: i.crop, geography: i.geography, status: i.status, firstReportedAt: i.firstReportedAt, lastReportedAt: i.lastReportedAt,
    reporterCount: i.reportingProducerIds.length, synthetic: !!i.synthetic,
    events: i.events.map((e) => ({ eventId: e.eventId, type: e.type, at: e.at, text: e.text ?? null, source: e.source, synthetic: !!e.synthetic, supersedes: e.supersedes ?? null,
      superseded: i.events.some((o) => o.supersedes === e.eventId) })) };
}
