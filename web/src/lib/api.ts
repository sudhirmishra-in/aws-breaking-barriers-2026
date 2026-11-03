import { accessToken } from "./auth";
import { loadConfig } from "./config";
import { ApiFailure, type AskResponse, type Overview, type ConversationView, type CurrentView, type Lang, type Me, type ReviewItem } from "../types";

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
  overview: () => call<Overview>("GET", "/overview"),
  ask: (requestId: string, text: string, language: Lang) => call<AskResponse>("POST", "/ask", { requestId, text, language }),
  current: () => call<CurrentView>("GET", "/conversations/current"),
  create: (language: Lang) => call<ConversationView>("POST", "/conversations", { requestId: newRequestId(), language }),
  message: (id: string, requestId: string, text: string) => call<ConversationView>("POST", `/conversations/${id}/messages`, { requestId, text }),
  playback: (id: string, requestId: string, body: { decision: "confirm" | "correct"; correction?: string; profileCorrection?: { field: "location" | "entityType"; value: string } }) =>
    call<ConversationView>("POST", `/conversations/${id}/playback`, { requestId, ...body }),
  consent: (id: string, requestId: string, storeSummary: boolean) => call<ConversationView>("POST", `/conversations/${id}/consent`, { requestId, storeSummary }),
  end: (id: string, requestId: string) => call<ConversationView>("POST", `/conversations/${id}/end`, { requestId }),
  reviews: () => call<{ items: ReviewItem[] }>("GET", "/reviews"),
  review: (id: string) => call<ReviewItem>("GET", `/reviews/${id}`),
  updateReview: (id: string, body: { decision: "approve" | "correct"; correctedSummaryEn?: string; correctedSummaryEs?: string; piiHandled?: boolean }) =>
    call<ReviewItem>("PUT", `/reviews/${id}`, { requestId: newRequestId(), ...body }),
};
