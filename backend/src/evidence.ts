import raw from "./data/regional_evidence.json";

/** Prepared regional evidence (synthetic, illustrative). Scope (tags, country) is derived server-side from the producer's own record and organization. */
export interface EvidenceItem {
  evidenceId: string; geography: string; period: string; tag: string; finding: string; source: string;
  origin: "external_imported" | "ftusa_authored"; curationStatus: "ftusa_curated" | "not_curated"; illustrative: boolean; stale?: boolean; standards: string[];
}
const ALL = (raw as { evidence: EvidenceItem[] }).evidence;
export function evidenceFor(country: string | null, tags: string[]): EvidenceItem[] {
  return ALL.filter((e) => tags.includes(e.tag) && !!country && e.geography.toLowerCase().includes(country.toLowerCase()));
}
