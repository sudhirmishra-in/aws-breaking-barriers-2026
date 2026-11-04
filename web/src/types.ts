// Mirrors backend/src/contracts.ts response shapes.
export type Lang = "en" | "es";
export type Stage = "intake" | "playback" | "response" | "consent" | "feedback";
export interface Message { seq: number; role: "user" | "assistant"; text: string; at: string; stage?: Stage | null }
export interface ConversationDto {
  conversationId: string; language: Lang;
  workflow: "intake" | "playback_pending" | "guidance_pending" | "consent_pending" | "closed";
  confirmation: string; consent: "unanswered" | "granted" | "declined"; status: "active" | "completed" | "declined";
  title?: string | null; playbackSummary?: string; summaryEn?: string; summaryEs?: string; expiresAt: string | null;
}
export interface ConversationView { conversation: ConversationDto; messages: Message[]; retention: { activeDays: number; savedDays?: number; text: string }; syntheticDemo: true }
export interface ConversationSummary { conversationId: string; title: string | null; language: Lang; createdAt: string; updatedAt: string; status: "in_progress" | "saved"; summary: string | null }
export interface CurrentView { conversation: ConversationDto | null; messages?: Message[]; retention?: ConversationView["retention"] }
export interface Me { roles: ("producer" | "reviewer")[]; profile?: { displayName: string; entityType: string; location: string; crop: string; preferredLanguage: Lang }; syntheticDemo: true }
export interface ReviewItem {
  outcomeId: string; source: string; producerId: string; entityType?: string; language: Lang; summaryEn?: string; summaryEs?: string;
  piiFlag?: boolean; piiTypes?: string[]; evidenceStatus?: string; reviewStatus: "pending" | "approved" | "corrected"; reviewedAt?: string; createdAt: string;
}
export class ApiFailure extends Error {
  constructor(public status: number, public code: string, message: string, public retryable: boolean) { super(message); }
}
export interface AskResponse { answer: string; evidence: { status: "unavailable" }; piiFlag: boolean; language: Lang; syntheticDemo: true }
export interface Overview {
  producer?: { activeConversation: { workflow: ConversationDto["workflow"]; updatedAt: string } | null };
  reviewer?: { pending: number; approved: number; corrected: number; piiFlagged: number; recent: ReviewItem[] };
}
