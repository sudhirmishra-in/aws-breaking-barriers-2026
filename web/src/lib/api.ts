import { accessToken } from "./auth";
import { loadConfig } from "./config";
import { ApiFailure, type RelatedData, type ReviewProducer, type ReviewRecord, type ReviewStats, type ConversationSummary, type AskResponse, type Overview, type ConversationView, type CurrentView, type Lang, type Me, type ProducerInfo, type CorrectionDto, type PeerCase, type EvidenceItem, type IssueContext, type IssueDto, type SharingChoice, type InfoKey, type PublicationStatus } from "../types";

export const newRequestId = () => crypto.randomUUID();

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const token = accessToken();
  if (!token) throw new ApiFailure(401, "session_expired", "Your session has expired.", false);
  const c = await loadConfig();
  let r: Response;
  try {
    r = await fetch(`${c.apiBaseUrl}${path}`, {
      method, headers: { authorization: `Bearer ${token}`, ...(body ? { "content-type": "application/json" } : {}) }, body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiFailure(0, "network", "Could not reach the service.", true);
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const e = (data as { error?: { code: string; message: string; retryable: boolean } }).error;
    throw new ApiFailure(r.status, r.status === 401 ? "session_expired" : (e?.code ?? "error"), e?.message ?? "Something went wrong.", e?.retryable ?? r.status >= 500);
  }
  return data as T;
}

export const api = {
  me: () => call<Me>("GET", "/me"),
  transcribe: (requestId: string, language: Lang, audio: string) => call<{ text: string; language: Lang }>("POST", "/transcribe", { requestId, language, audio }),
  overview: () => call<Overview>("GET", "/overview"),
  ask: (requestId: string, text: string, language: Lang) => call<AskResponse>("POST", "/ask", { requestId, text, language }),
  current: () => call<CurrentView>("GET", "/conversations/current"),
  list: () => call<{ items: ConversationSummary[] }>("GET", "/conversations"),
  speech: (id: string, seq: number) => call<{ contentType: string; audio: string; voice: string }>("POST", `/conversations/${encodeURIComponent(id)}/messages/${seq}/speech`, {}),
  remove: (id: string) => call<{ deleted: true }>("DELETE", `/conversations/${encodeURIComponent(id)}`),
  get: (id: string) => call<ConversationView>("GET", `/conversations/${encodeURIComponent(id)}`),
  create: (language: Lang | undefined, requestId: string = newRequestId(), referenceCaseId?: string) => call<ConversationView>("POST", "/conversations", { requestId, ...(language ? { language } : {}), ...(referenceCaseId ? { referenceCaseId } : {}) }),
  evidence: (id: string) => call<{ items: EvidenceItem[]; projects: EvidenceItem[]; limitation: string | null }>("GET", `/evidence/${encodeURIComponent(id)}`),
  feedback: (id: string, helpful: "yes" | "partly" | "no") => call<{ helpful: string }>("POST", `/conversations/${id}/feedback`, { requestId: newRequestId(), helpful }),
  comparable: (id: string) => call<{ items: PeerCase[]; limitation: string | null }>("GET", `/related/${encodeURIComponent(id)}`),
  setLanguage: (id: string, requestId: string, language: Lang) => call<ConversationView>("POST", `/conversations/${id}/language`, { requestId, language }),
  issueContext: (conversationId: string) => call<IssueContext>("GET", `/issues/for/${encodeURIComponent(conversationId)}`),
  linkIssue: (conversationId: string, same: boolean, issueId?: string) => call<IssueContext>("POST", `/conversations/${conversationId}/issue-link`, { requestId: newRequestId(), same, ...(issueId ? { issueId } : {}) }),
  addIssueEvent: (issueId: string, type: "action_planned" | "action" | "outcome" | "resolution_confirmed" | "recurrence", text?: string) =>
    call<IssueDto>("POST", `/issues/${encodeURIComponent(issueId)}/events`, { requestId: newRequestId(), type, ...(text ? { text } : {}) }),
  producerInfo: () => call<ProducerInfo>("GET", "/producer-info"),
  submitCorrection: (requestId: string, changes: { field: InfoKey; proposed: string }[], explanation?: string) => call<CorrectionDto>("POST", "/corrections", { requestId, changes, ...(explanation ? { explanation } : {}) }),
  peers: (scope: "organization" | "other" | "all") => call<{ items: PeerCase[]; visibility: string }>("GET", `/peers/summaries?scope=${scope}`),
  finalize: (id: string, requestId: string, summaryHash: string, sharing: SharingChoice, identityPermitted: boolean) => call<ConversationView>("POST", `/conversations/${id}/finalize`, { requestId, summaryHash, sharing, identityPermitted }),
  updateSharing: (id: string, sharing: SharingChoice, identityPermitted: boolean) => call<{ sharingChoice: SharingChoice; publicationStatus: PublicationStatus }>("POST", `/conversations/${id}/sharing`, { requestId: newRequestId(), sharing, identityPermitted }),
  reconfirm: (id: string, summaryHash: string, accept: boolean) => call<{ publicationStatus: PublicationStatus }>("POST", `/conversations/${id}/reconfirm`, { requestId: newRequestId(), summaryHash, accept }),
  requestDeletion: (id: string) => call<{ note: string; publicationStatus: PublicationStatus }>("POST", `/conversations/${id}/deletion-request`, {}),
  reviewCorrections: (status = "pending") => call<{ items: CorrectionDto[] }>("GET", `/review/corrections?status=${status}`),
  decideCorrection: (id: string, decision: "accept" | "reject" | "mark_applied", note?: string) => call<CorrectionDto>("POST", `/review/corrections/${encodeURIComponent(id)}/decision`, { requestId: newRequestId(), decision, ...(note ? { note } : {}) }),
  message: (id: string, requestId: string, text: string) => call<ConversationView>("POST", `/conversations/${id}/messages`, { requestId, text }),
  playback: (id: string, requestId: string, body: { decision: "confirm" | "correct"; correction?: string; profileCorrection?: { field: "location" | "entityType"; value: string } }) =>
    call<ConversationView>("POST", `/conversations/${id}/playback`, { requestId, ...body }),
  consent: (id: string, requestId: string, storeSummary: boolean) => call<ConversationView>("POST", `/conversations/${id}/consent`, { requestId, storeSummary }),
  end: (id: string, requestId: string) => call<ConversationView>("POST", `/conversations/${id}/end`, { requestId }),
  reviewStats: () => call<ReviewStats>("GET", "/review/stats"),
  reviewProducers: (f: Record<string, string>) => call<{ items: ReviewProducer[] }>("GET", `/review/producers?${new URLSearchParams(f).toString()}`),
  producerRecords: (id: string) => call<{ items: ReviewRecord[] }>("GET", `/review/producers/${encodeURIComponent(id)}/records`),
  related: (id: string) => call<RelatedData>("GET", `/review/producers/${encodeURIComponent(id)}/related`),
  record: (id: string) => call<ReviewRecord>("GET", `/records/${encodeURIComponent(id)}`),
  patchRecord: (id: string, body: { review_status: "approved" | "corrected"; summary_original?: string; summary_en?: string; challenge_tags?: string[]; reviewer_note?: string }) =>
    call<ReviewRecord>("PATCH", `/records/${encodeURIComponent(id)}`, { requestId: newRequestId(), ...body }),
};
