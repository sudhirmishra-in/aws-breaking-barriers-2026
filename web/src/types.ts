// Mirrors backend/src/contracts.ts response shapes.
export type Lang = "en" | "es" | "fr";
export const LANGS: { code: Lang; name: string }[] = [{ code: "en", name: "English" }, { code: "es", name: "Español" }, { code: "fr", name: "Français" }];
export type Stage = "intake" | "playback" | "response" | "consent" | "feedback";
export interface Message { seq: number; role: "user" | "assistant"; text: string; at: string; stage?: Stage | null }
export interface ConversationDto {
  conversationId: string; language: Lang;
  workflow: "intake" | "playback_pending" | "guidance_pending" | "consent_pending" | "closed";
  confirmation: string; consent: "unanswered" | "granted" | "declined"; status: "active" | "completed" | "declined";
  title?: string | null; playbackSummary?: string; summaryOriginal?: string; summaryEn?: string; expiresAt: string | null;
}
export interface ConversationView { conversation: ConversationDto; messages: Message[]; retention: { activeDays: number; savedDays?: number; text: string }; syntheticDemo: true }
export interface ConversationSummary { conversationId: string; title: string | null; language: Lang; createdAt: string; updatedAt: string; status: "in_progress" | "saved"; summary: string | null }
export interface CurrentView { conversation: ConversationDto | null; messages?: Message[]; retention?: ConversationView["retention"] }
export interface Me { roles: ("producer" | "reviewer")[]; profile?: { displayName: string; entityType: string; location: string; crop: string; preferredLanguage: Lang }; syntheticDemo: true }
export interface ReviewItem {
  outcomeId: string; source: string; producerId: string; entityType?: string; language: Lang; summaryOriginal?: string; summaryEn?: string;
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

export type ChallengeTag = "climate_weather" | "water" | "soil_land" | "market_price" | "labor_migration" | "financial_capital"
  | "education" | "health" | "infrastructure" | "biodiversity_conservation" | "social_community";
export const CHALLENGE_TAGS: ChallengeTag[] = ["climate_weather", "water", "soil_land", "market_price", "labor_migration", "financial_capital",
  "education", "health", "infrastructure", "biodiversity_conservation", "social_community"];
export type ReviewStatus = "pending" | "approved" | "corrected";
export type RecordOutcome = "completed" | "declined" | "out_of_scope";
export interface ReviewStats { pending: number; approved: number; corrected: number; declined: number; piiFlagged: number; conversationsToday: number; asOf: string }
export interface ReviewProducer { producerId: string; producerName: string; entityType: string | null; crop: string | null; location: string | null;
  recordCount: number; pendingCount: number; piiFlag: boolean; latestAt: string; matchingRecords: number }
export interface ReviewRecord {
  recordId: string; producerId: string; producerName: string; entityType: string | null; crop: string | null; location: string | null;
  language: Lang; createdAt: string; outcome: RecordOutcome; reviewStatus: ReviewStatus | null;
  source?: "agent conversation"; summaryOriginal?: string | null; summaryEn?: string | null; challengeTags?: ChallengeTag[]; agentChallengeTags?: ChallengeTag[];
  claims?: unknown[]; evidenceStatus?: string; piiFlag?: boolean; piiEntityTypes?: string[]; feedbackHelpful?: string | null; peerExampleOk?: boolean;
  reasoningLogRef?: string | null; reviewerNote?: string | null; reviewedBy?: string | null; reviewedAt?: string | null;
}
export interface RelatedData {
  producerId: string; source: string; query: string | null;
  premiumProjects: { year: number; title: string; tags: string[]; amountUsd: number; status: string; outcome: string | null }[];
  surveys: { year: number; topConcern: string | null; concerns: string[]; respondents: number; incomeChangePct: number; lowerYieldPct: number }[];
  certification: { standard: string; version: string; status: string; lastAudit: string }[];
}
