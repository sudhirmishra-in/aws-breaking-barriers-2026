// Mirrors backend/src/contracts.ts response shapes.
export type Lang = "en" | "es" | "fr";
export const LANGS: { code: Lang; name: string }[] = [{ code: "en", name: "English" }, { code: "es", name: "Español" }, { code: "fr", name: "Français" }];
export type Stage = "intake" | "playback" | "response" | "consent" | "feedback";
export interface Message { seq: number; role: "user" | "assistant"; text: string; at: string; stage?: Stage | null }
export interface ConversationDto {
  conversationId: string; language: Lang;
  workflow: "intake" | "playback_pending" | "guidance_pending" | "consent_pending" | "closed";
  confirmation: string; consent: "unanswered" | "granted" | "declined"; status: "active" | "completed" | "declined" | "stopped";
  title?: string | null; playbackSummary?: string; summaryOriginal?: string; summaryEn?: string; expiresAt: string | null;
}
export type SharingChoice = "share_conversation" | "share_summary" | "ftusa_only";
export type PublicationStatus = "not_shared" | "awaiting_review" | "awaiting_reconfirmation" | "pending_publication" | "published" | "failed" | "withdrawn";
export interface ConfirmationDto { summaryHash: string; summaryOriginal: string; summaryEn: string; tags: ChallengeTag[]; language: Lang }
export interface RecordStateDto {
  sharingChoice: SharingChoice; identityPermitted: boolean; reviewStatus: ReviewStatus; publicationStatus: PublicationStatus; summaryVersion: number; deletionRequested: boolean; tags: ChallengeTag[]; feedback: { helpful: "yes" | "partly" | "no" } | null;
  reconfirmation: { summaryHash: string; summaryOriginal: string; summaryEn: string; version: number } | null;
}
export interface ConversationView {
  conversation: ConversationDto; messages: Message[]; retention: { activeDays: number; savedDays?: number; text: string }; syntheticDemo: true;
  confirmation?: ConfirmationDto | null; record?: RecordStateDto | null; referencedCase?: { caseId: string; version: number } | null;
}
export interface ConversationSummary { conversationId: string; title: string | null; language: Lang; createdAt: string; updatedAt: string; status: "in_progress" | "completed"; stopped?: boolean; group?: "today" | "previous_7_days" | "older"; summary: string | null }
export interface CurrentView { conversation: ConversationDto | null; messages?: Message[]; retention?: ConversationView["retention"] }
export interface Me {
  roles: ("producer" | "reviewer")[]; profile?: { displayName: string; entityType: string; location: string; crop: string; preferredLanguage: Lang }; syntheticDemo: true;
  identity?: { producerId: string; organizationId: string | null; applicationUserId: string | null };
  preferred_language?: Lang | null; configurationError?: "producer_mapping_missing" | null;
}
export type InfoKey = "account_sk" | "account_category_name" | "product_category_name" | "account_type_name" | "certification_scope_name" | "certification_status_name" | "country_name" | "raw_supply_chain_role_txt" | "structure_txt";
export type CorrectionStatus = "pending" | "accepted_awaiting_source_update" | "applied" | "rejected";
export interface CorrectionDto { correctionId: string; status: CorrectionStatus; createdAt: string; requestedByYou: boolean; changes: { field: InfoKey; original: string | null; proposed: string }[];
  explanation: string | null; decidedAt: string | null; appliedAt: string | null; decisionNote: string | null; organizationId?: string; requesterProducerId?: string; decidedBy?: string | null }
export interface ProducerInfo {
  individual: { producerId: string; displayName: string; preferredLanguage: Lang };
  organization: { organizationId: string; name: string; fields: Record<InfoKey, string | string[] | null> } | null;
  summary: { products: string[]; country: string | null }; pendingCorrections: CorrectionDto[]; correctableFields: InfoKey[]; verified: false;
}
export interface PeerCase {
  caseId: string; version: number; sameOrganization: boolean; origin: "your_organization" | "other_organization"; visibility: "published" | "organization_only"; language?: string; summaryOriginal?: string; producer: { name: string } | null; anonymousLabel: string;
  challenge: string; action: string | null; result: string; resultReported: boolean; tags: ChallengeTag[]; standards: string[]; citations: { label: string; url?: string }[]; publishedAt: string | null; illustrative: boolean;
}
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
export interface EvidenceItem { evidenceId: string; geography: string; period: string; tag: string; finding: string; source: string;
  origin: "external_imported" | "ftusa_authored"; curationStatus: "ftusa_curated" | "not_curated"; illustrative: boolean; stale?: boolean; standards: string[] }
