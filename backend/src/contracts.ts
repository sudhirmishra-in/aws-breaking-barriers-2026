import { z } from "zod";

export const Language = z.enum(["en", "es"]);
export type Language = z.infer<typeof Language>;

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
export const ConsentReq = z.object({ requestId: RequestId, storeSummary: z.boolean() }).strict();
export const EndReq = z.object({ requestId: RequestId }).strict();
export const ReviewUpdateReq = z
  .object({
    requestId: RequestId,
    decision: z.enum(["approve", "correct"]),
    correctedSummaryEn: z.string().trim().min(1).max(2000).optional(),
    correctedSummaryEs: z.string().trim().min(1).max(2000).optional(),
    piiHandled: z.boolean().optional(),
  })
  .strict()
  .refine((v) => v.decision === "approve" || !!v.correctedSummaryEn || !!v.correctedSummaryEs, { message: "corrected summary required" });

export type Workflow = "intake" | "playback_pending" | "guidance_pending" | "consent_pending" | "closed";
export type Confirmation = "none" | "pending" | "confirmed";
export type Consent = "unanswered" | "granted" | "declined";
export type ConvStatus = "active" | "completed" | "declined";

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
  playbackSummary?: string;
  confirmedAccount?: string;
  producerAssertions?: { location?: string; entityType?: string }; // asserted, not trusted scope
  summaryEn?: string;
  summaryEs?: string;
  piiFlag: boolean;
  piiTypes: string[];
  messageCount: number;
  userTurns: number;
  version: number;
  lockToken?: string;
  lockExpires?: number;
  createdAt: string;
  updatedAt: string;
  expiresAt: number; // epoch seconds (DynamoDB TTL)
}

export interface Message { seq: number; role: "user" | "assistant"; text: string; at: string }

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
  summaryEn?: string;
  summaryEs?: string;
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
