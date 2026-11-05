import { z } from "zod";

export const Language = z.enum(["en", "es", "fr"]);
export type Language = z.infer<typeof Language>;

export const CHALLENGE_TAGS = ["climate_weather", "water", "soil_land", "market_price", "labor_migration", "financial_capital",
  "education", "health", "infrastructure", "biodiversity_conservation", "social_community"] as const;
export const ChallengeTag = z.enum(CHALLENGE_TAGS);
export type ChallengeTag = z.infer<typeof ChallengeTag>;
export const ENTITY_TYPES = ["smallholder", "cooperative", "estate", "processing_operation"] as const; // spec enumeration

export const RequestId = z.string().min(8).max(64).regex(/^[A-Za-z0-9_-]+$/);

export const CreateConversationReq = z.object({ requestId: RequestId, language: Language }).strict();
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
// Review (spec REV-01..24). Approve changes nothing but the status (and an optional note); correct must change something.
export const ReviewPatchReq = z.object({
  requestId: RequestId.optional(),
  review_status: z.enum(["approved", "corrected"]),
  summary_original: z.string().trim().min(1).max(2000).optional(),
  summary_en: z.string().trim().min(1).max(2000).optional(),
  challenge_tags: z.array(ChallengeTag).max(11).optional(),
  reviewer_note: z.string().trim().max(1000).optional(),
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

export type Workflow = "intake" | "playback_pending" | "guidance_pending" | "consent_pending" | "closed";
export type Confirmation = "none" | "pending" | "confirmed";
export type Consent = "unanswered" | "granted" | "declined";
export type ConvStatus = "active" | "completed" | "declined";
/** UI stage of a message (spec CHAT-07): intake, playback, response, consent, feedback. */
export type Stage = "intake" | "playback" | "response" | "consent" | "feedback";

export interface ProducerProfile {
  producerId: string;
  displayName: string;
  entityType: string;
  location: string;
  crop: string;
  preferredLanguage: Language;
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
}

export interface ErrorBody { error: { code: string; message: string; retryable: boolean; requestId: string } }

export const SYNTHETIC_LABEL = "synthetic demonstration data";
