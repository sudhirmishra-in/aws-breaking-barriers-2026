import { z } from "zod";

export const Language = z.enum(["en", "es", "fr"]);
export type Language = z.infer<typeof Language>;

export const CHALLENGE_TAGS = ["climate_weather", "water", "soil_land", "market_price", "labor_migration", "financial_capital",
  "education", "health", "infrastructure", "biodiversity_conservation", "social_community"] as const;
export const ChallengeTag = z.enum(CHALLENGE_TAGS);
export type ChallengeTag = z.infer<typeof ChallengeTag>;
export const ENTITY_TYPES = ["cooperative", "association", "estate", "processing_operation"] as const; // organization types only: every producer belongs to an organization, so there is no "individual farmer" type

export const RequestId = z.string().min(8).max(64).regex(/^[A-Za-z0-9_-]+$/);

// V2: language is optional; the server defaults it to the producer's preferred language (English if missing). caseRef is validated server-side.
export const CreateConversationReq = z.object({ requestId: RequestId, language: Language.optional(), referenceCaseId: z.string().min(3).max(200).optional() }).strict();
export const SubmitMessageReq = z.object({ requestId: RequestId, text: z.string().trim().min(1).max(2000) }).strict();
export const PlaybackReq = z
  .object({
    requestId: RequestId,
    decision: z.enum(["confirm", "correct"]),
    correction: z.string().trim().min(1).max(2000).optional(),
    // Producer-asserted; validated by the app, never used as lookup scope.
    profileCorrection: z.object({ field: z.enum(["location", "entityType"]), value: z.string().trim().min(1).max(120) }).strict().optional(),
  })
  .strict()
  .refine((v) => v.decision === "confirm" || !!v.correction || !!v.profileCorrection, { message: "correction required" });
export const AskReq = z.object({ requestId: RequestId, text: z.string().trim().min(1).max(1000), language: Language }).strict();
// Raw 16 kHz, 16-bit, mono PCM, base64. 60 s is 1.92 MB, about 2.6 MB encoded.
export const TranscribeReq = z.object({ requestId: RequestId, language: Language, audio: z.string().min(1).max(2_700_000) }).strict();
export const CaseCardPatch = z.object({ action: z.string().trim().min(1).max(600).nullable().optional(), result: z.string().trim().min(1).max(600).nullable().optional(),
  standards: z.array(z.string().trim().min(1).max(200)).max(6).optional(), citations: z.array(z.object({ label: z.string().trim().min(1).max(200), url: z.string().url().max(500).optional() }).strict()).max(6).optional() }).strict();
// Review (spec REV-01..24). Approve changes nothing but the status (and an optional note); correct must change something.
export const ReviewPatchReq = z.object({
  requestId: RequestId.optional(),
  review_status: z.enum(["approved", "corrected"]),
  summary_original: z.string().trim().min(1).max(2000).optional(),
  summary_en: z.string().trim().min(1).max(2000).optional(),
  challenge_tags: z.array(ChallengeTag).max(11).optional(),
  reviewer_note: z.string().trim().max(1000).optional(),
  case_card: CaseCardPatch.optional(),
}).strict().refine((v) => v.review_status === "approved"
  ? v.summary_original === undefined && v.summary_en === undefined && v.challenge_tags === undefined
  : v.summary_original !== undefined || v.summary_en !== undefined || v.challenge_tags !== undefined,
  { message: "approve changes only the status; a correction must change the summary or tags" });
export const ReviewProducersQuery = z.object({
  q: z.string().trim().max(100).optional(),
  review_status: z.enum(["pending", "approved", "corrected", "all"]).optional(),
  outcome: z.enum(["completed", "declined", "out_of_scope", "all"]).optional(),
  pii_only: z.enum(["true", "false"]).optional(),
}).strict();
export const ConsentReq = z.object({ requestId: RequestId, storeSummary: z.boolean() }).strict();
export const EndReq = z.object({ requestId: RequestId }).strict();
export const ReviewUpdateReq = z
  .object({
    requestId: RequestId,
    decision: z.enum(["approve", "correct"]),
    correctedSummaryOriginal: z.string().trim().min(1).max(2000).optional(),
    correctedSummaryEn: z.string().trim().min(1).max(2000).optional(),
    piiHandled: z.boolean().optional(),
  })
  .strict()
  .refine((v) => v.decision === "approve" || !!v.correctedSummaryEn || !!v.correctedSummaryOriginal, { message: "corrected summary required" });

// ---- V2 contracts -----------------------------------------------------------------------------------------------
export const SHARING_CHOICES = ["share_conversation", "share_summary", "ftusa_only"] as const;
export const SharingChoice = z.enum(SHARING_CHOICES);
export type SharingChoice = z.infer<typeof SharingChoice>;
/** Organization-level source fields a producer may propose corrections to. Identifiers, membership and permissions are NOT listed on purpose. */
export const CORRECTABLE_FIELDS = ["account_category_name", "product_category_name", "account_type_name", "certification_scope_name",
  "certification_status_name", "country_name", "raw_supply_chain_role_txt", "structure_txt"] as const;
export type CorrectableField = (typeof CORRECTABLE_FIELDS)[number];
export const CorrectionCreateReq = z.object({
  requestId: RequestId,
  changes: z.array(z.object({ field: z.enum(CORRECTABLE_FIELDS), proposed: z.string().trim().min(1).max(300) }).strict()).min(1).max(CORRECTABLE_FIELDS.length),
  explanation: z.string().trim().max(1000).optional(),
}).strict().refine((v) => new Set(v.changes.map((c) => c.field)).size === v.changes.length, { message: "duplicate field" });
export const CorrectionDecisionReq = z.object({ requestId: RequestId, decision: z.enum(["accept", "reject", "mark_applied"]), note: z.string().trim().max(1000).optional() }).strict();
export const FinalizeReq = z.object({ requestId: RequestId, summaryHash: z.string().length(64), sharing: SharingChoice, identityPermitted: z.boolean().default(false) }).strict()
  .refine((v) => !v.identityPermitted || v.sharing === "share_conversation", { message: "identity can only be shared with the conversation choice" });
export const SharingUpdateReq = z.object({ requestId: RequestId, sharing: SharingChoice, identityPermitted: z.boolean().default(false) }).strict()
  .refine((v) => !v.identityPermitted || v.sharing === "share_conversation", { message: "identity can only be shared with the conversation choice" });
export const FeedbackReq = z.object({ requestId: RequestId, helpful: z.enum(["yes", "partly", "no"]), comment: z.string().trim().max(500).optional() }).strict();
export const ReconfirmReq = z.object({ requestId: RequestId, summaryHash: z.string().length(64), accept: z.boolean() }).strict();
export const PeerQuery = z.object({ scope: z.enum(["organization", "other", "all"]).optional() }).strict();

export type CorrectionStatus = "pending" | "accepted_awaiting_source_update" | "applied" | "rejected";
export type PublicationStatus = "not_shared" | "awaiting_review" | "awaiting_reconfirmation" | "pending_publication" | "published" | "failed" | "withdrawn";

/** Source columns as prepared for the producer information view. Multi-valued fields are arrays. null = not provided. */
export interface OrganizationInfo {
  accountSk: string | null; accountCategoryName: string | null; productCategoryName: string[]; accountTypeName: string | null;
  certificationScopeName: string | null; certificationStatusName: string | null; countryName: string | null; rawSupplyChainRoleTxt: string[]; structureTxt: string | null;
}
export interface Organization { organizationId: string; name: string; info: OrganizationInfo }
export interface Publication {
  version: number; approvedBy: string; approvedAt: string;
  payload: { challenge: string; action: string | null; result: string | null; tags: string[]; standards: string[]; citations: { label: string; url?: string }[] };
}
export interface SummaryVersion { version: number; kind: "producer_confirmed" | "reviewer_revision"; summaryOriginal: string; summaryEn: string; hash: string; at: string; by: string }
export interface CorrectionRecord {
  correctionId: string; organizationId: string; requesterProducerId: string; requesterSub: string; createdAt: string; updatedAt: string;
  changes: { field: CorrectableField; original: string | null; proposed: string }[]; explanation?: string;
  status: CorrectionStatus; decidedBy?: string; decidedAt?: string; decisionNote?: string; appliedAt?: string;
}

export type Workflow = "intake" | "playback_pending" | "guidance_pending" | "consent_pending" | "closed";
export type Confirmation = "none" | "pending" | "confirmed";
export type Consent = "unanswered" | "granted" | "declined";
export type ConvStatus = "active" | "completed" | "declined" | "stopped";
/** UI stage of a message (spec CHAT-07): intake, playback, response, consent, feedback. */
export type Stage = "intake" | "playback" | "response" | "consent" | "feedback";

export interface ProducerProfile {
  producerId: string;
  displayName: string;
  entityType: string;
  location: string;
  crop: string;
  preferredLanguage: Language;
  // V2 identity: organization_id and application_user_id are distinct from producer_id and the Cognito sub. Resolved server-side only.
  organizationId?: string;
  applicationUserId?: string;
}

export interface Conversation {
  conversationId: string;
  ownerSub: string;
  producerId: string; // trusted profile reference
  language: Language;
  workflow: Workflow;
  confirmation: Confirmation;
  consent: Consent;
  status: ConvStatus;
  title?: string; // short challenge title for the history list; removed on decline
  playbackSummary?: string;
  confirmedAccount?: string;
  producerAssertions?: { location?: string; entityType?: string }; // asserted, not trusted scope
  summaryOriginal?: string; // in the conversation language
  summaryEn?: string;
  challengeTags?: ChallengeTag[];
  piiFlag: boolean;
  piiTypes: string[];
  messageCount: number;
  userTurns: number;
  version: number;
  lockToken?: string;
  lockExpires?: number;
  createdAt: string;
  updatedAt: string;
  organizationId?: string;
  referencedCase?: { caseId: string; version: number }; // validated peer case this conversation asks about
  sharingChoice?: SharingChoice;
  expiresAt: number; // epoch seconds (DynamoDB TTL); 0 = kept until the producer deletes it (saved conversations)
}

export interface Message { seq: number; role: "user" | "assistant"; text: string; at: string; stage?: Stage }

export type OutcomeKind = "record" | "declined";
export type ReviewStatus = "pending" | "approved" | "corrected";
export interface Outcome {
  outcomeId: string;
  kind: OutcomeKind;
  ownerSub: string;
  producerId: string;
  conversationId: string;
  language: Language;
  createdAt: string;
  // Narrative fields exist ONLY on kind === "record".
  source?: "agent conversation";
  entityType?: string;
  summaryOriginal?: string; // producer's language (spec: summary_original)
  summaryEn?: string;
  summaryEs?: string; // legacy records written before French support
  challengeTags?: string[];
  agentChallengeTags?: string[]; // what the agent proposed, so reviewer changes can be shown (REV-07)
  producerName?: string; crop?: string; location?: string; // trusted server-side snapshot of the producer profile
  reviewerNote?: string;
  reviewedByName?: string;
  piiFlag?: boolean;
  piiTypes?: string[];
  evidenceStatus?: "unavailable";
  reviewStatus?: ReviewStatus;
  reviewedBy?: string;
  reviewedAt?: string;
  declineReason?: "declined_storage" | "ended_early";
  // V2. review_status, sharing and publication_status are independent.
  organizationId?: string;
  sharingChoice?: SharingChoice;
  identityPermitted?: boolean;
  confirmationHash?: string; confirmedAt?: string; confirmedByProducerId?: string; confirmedByName?: string;
  summaryVersion?: number; versions?: SummaryVersion[];
  pendingRevision?: SummaryVersion; // reviewer change awaiting producer re-confirmation
  publicationStatus?: PublicationStatus; publication?: Publication; publishedVersion?: number; publishedAt?: string; publishError?: string;
  deletionRequestedAt?: string;
  feedback?: { helpful: "yes" | "partly" | "no"; comment?: string; at: string };
  caseCard?: { action?: string | null; result?: string | null; standards?: string[]; citations?: { label: string; url?: string }[] };
  ttl?: number; // DynamoDB TTL (epoch seconds): finalized records are retained 180 days in the sandbox, not indefinitely
}

export interface ErrorBody { error: { code: string; message: string; retryable: boolean; requestId: string } }

export const SYNTHETIC_LABEL = "synthetic demonstration data";
