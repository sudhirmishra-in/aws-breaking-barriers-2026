// V2 interface labels. The spec keeps interface labels in English; conversation content follows the producer's language.
import type { CorrectionStatus, InfoKey, PublicationStatus, SharingChoice } from "../types";

export const INFO_LABEL: Record<InfoKey, string> = {
  account_sk: "Account reference", account_category_name: "Account category", product_category_name: "Products", account_type_name: "Account type",
  certification_scope_name: "Certification scope", certification_status_name: "Certification status", country_name: "Country",
  raw_supply_chain_role_txt: "Supply chain roles", structure_txt: "Organization structure",
};
export const NOT_PROVIDED = "Not provided";
export const show = (v: string | string[] | null | undefined): string => (Array.isArray(v) ? (v.length ? v.join(", ") : NOT_PROVIDED) : v || NOT_PROVIDED);
export const CORRECTION_STATUS: Record<CorrectionStatus, string> = {
  pending: "Pending review", accepted_awaiting_source_update: "Accepted, awaiting source update", applied: "Applied to the source record", rejected: "Not accepted",
};
export const PUBLICATION_STATUS: Record<PublicationStatus, string> = {
  not_shared: "Not shared with other producers", awaiting_review: "Waiting for FTUSA review before it can be shared", awaiting_reconfirmation: "Waiting for your confirmation of a reviewer edit",
  pending_publication: "Approved, publishing", published: "Published to producers you chose", failed: "Publishing failed, FTUSA will retry", withdrawn: "Withdrawn from other producers",
};
export const SHARING: { value: SharingChoice; title: string; exposes: string }[] = [
  { value: "share_conversation", title: "Share the conversation and the producer information I allow",
    exposes: "After FTUSA review, other producers can see this case's challenge, what was done and the result. Your name appears only if you tick the box below. FTUSA keeps the full conversation." },
  { value: "share_summary", title: "Share the summary only",
    exposes: "After FTUSA review, other producers can see the reviewed summary without your name. The conversation itself is not shown to them. FTUSA keeps the full conversation." },
  { value: "ftusa_only", title: "Do not share with other producers",
    exposes: "Other producers, including people in your organization, cannot see this case. FTUSA keeps and reviews the full conversation." },
];
export const RETENTION_TEXT = "Fair Trade USA can keep and review your conversation. In this sandbox, conversations are kept for 90 days and finalized records for 180 days, then expire. Stopping a conversation does not delete it; you can ask for deletion at any time.";
export const SANDBOX_BANNER = "Sandbox demo. All producer data is synthetic.";
