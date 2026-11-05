import producersRaw from "./data/ftusa/ftusa_producers.json";
import projectsRaw from "./data/ftusa/ftusa_projects.json";
import surveysRaw from "./data/ftusa/ftusa_surveys.json";
import mapRaw from "./data/ftusa/ftusa_producer_map.json";

/**
 * FTUSA producer records (Component 3) read by the API Lambda: producer profile, Premium projects and aggregated survey summaries.
 * Joined on the producer's FTUSA account, which is resolved server-side from the app producerId (ftusa_producer_map.json) and is
 * never returned. Same output shapes as relatedData.ts (teamProducer / relatedFor), so the reviewer screen can use either source.
 * Raw household answers are not in these bundles: only per-year aggregates with their denominators.
 */
export interface FtusaProducer {
  accountSk: string; displayId: string; orgNameFictional: string; entityType: string; crops: string[]; primaryCrop: string | null;
  country: string | null; countryIso3: string | null; region: string | null; regionId: string | null; primaryLanguage: string | null;
  applicableStandard: "APS" | "FPS"; certificationStatus: string | null; certificationScope: string | null; projectCount: number; surveyYears: number[];
}
export interface FtusaProject {
  projectId: string; accountSk: string; name: string; description: string | null; primaryGoal: string | null; status: string | null;
  startDate: string | null; endDate: string | null; startYear: number | null; challengeTags: string[]; subcategory: string | null; crop: string | null;
  country: string | null; region: string | null; peerEligible: boolean; piiFlag: boolean; contentHash: string;
}
export interface Share { pct: number | null; n: number }
export interface FtusaSurvey {
  summaryId: string; accountSk: string; surveyYear: number; nResponses: number; metrics: Record<string, Share>;
  topChoices: Record<string, { label: string; pct: number }[]>;
}
type Bundle<K extends string, T> = { dataVersion: string; source: string; origin: string; curationStatus: string } & Record<K, T[]>;
const P = producersRaw as unknown as Bundle<"producers", FtusaProducer>;
const J = projectsRaw as unknown as Bundle<"projects", FtusaProject>;
const S = surveysRaw as unknown as Bundle<"surveys", FtusaSurvey> & { labels: string };
const MAP = (mapRaw as { map: Record<string, string> }).map;

export const FTUSA_SOURCE = `${P.source} (origin: ${P.origin}, ${P.curationStatus})`;
export const FTUSA_DATA_VERSION = { producers: P.dataVersion, projects: J.dataVersion, surveys: S.dataVersion };
const BY_SK = new Map(P.producers.map((p) => [p.accountSk, p]));
const BY_DISPLAY = new Map(P.producers.map((p) => [p.displayId, p]));

/** Server-side resolution only: the app producerId through the reviewed map, or an FTUSA display id used directly as a producerId. */
export function ftusaAccountFor(producerId: string): FtusaProducer | undefined {
  const sk = MAP[producerId];
  return sk ? BY_SK.get(sk) : BY_DISPLAY.get(producerId);
}

/** Same shape as relatedData.teamProducer. */
export function ftusaProducer(producerId: string) {
  const p = ftusaAccountFor(producerId);
  return p ? { name: p.orgNameFictional, entityType: p.entityType, crop: p.primaryCrop ?? "", location: [p.region, p.country].filter(Boolean).join(", ") } : undefined;
}

const projectsOf = (sk: string) => J.projects.filter((x) => x.accountSk === sk);
const surveysOf = (sk: string) => S.surveys.filter((x) => x.accountSk === sk);
const pct = (s?: Share) => (s && s.pct !== null && s.n > 0 ? s.pct : null);

/**
 * Same shape as relatedData.relatedFor, from FTUSA data; undefined when the producer has no FTUSA account (callers keep the team dataset).
 * Fields the FTUSA export does not hold are null, never estimated: amountUsd (no Premium amounts), incomeChangePct (no income question),
 * survey topConcern / concerns (survey answers carry no challenge tags), certification version and last audit.
 */
export function ftusaRelatedFor(producerId: string) {
  const p = ftusaAccountFor(producerId);
  if (!p) return undefined;
  return {
    producerId,
    source: FTUSA_SOURCE,
    query: null as null,
    premiumProjects: projectsOf(p.accountSk).sort((a, b) => (b.startYear ?? 0) - (a.startYear ?? 0) || a.projectId.localeCompare(b.projectId))
      .map((x) => ({ year: x.startYear, title: x.name, tags: x.challengeTags, amountUsd: null as number | null, status: x.status, outcome: null as string | null,
        projectId: x.projectId, citation: { label: `${P.source}, ${x.projectId}`, projectId: x.projectId, dataVersion: J.dataVersion, contentHash: x.contentHash } })),
    surveys: surveysOf(p.accountSk).sort((a, b) => b.surveyYear - a.surveyYear)
      .map((x) => ({ year: x.surveyYear, topConcern: null as string | null, concerns: [] as string[], respondents: x.nResponses, incomeChangePct: null as number | null,
        lowerYieldPct: pct(x.metrics.harvest_decreased), metrics: x.metrics, topChoices: x.topChoices, labels: S.labels,
        citation: { label: `${S.source}, survey ${x.surveyYear}`, summaryId: x.summaryId, dataVersion: S.dataVersion } })),
    certification: [{ standard: p.applicableStandard, version: null as string | null, status: p.certificationStatus, lastAudit: null as string | null, scope: p.certificationScope }],
  };
}

/**
 * Dated history lines for one producer (for trusted agent context or the reviewer). Each line has a citation. Projects are what was
 * planned or recorded; "Outcome not reported" is the only outcome the source supports.
 */
export function ftusaHistory(producerId: string) {
  const p = ftusaAccountFor(producerId);
  if (!p) return [];
  const lines = [
    ...projectsOf(p.accountSk).map((x) => ({ period: x.startYear ? String(x.startYear) : "undated",
      note: `Premium project "${x.name}" (${x.status ?? "status not recorded"}). Outcome not reported.`, citation: { label: `${P.source}, ${x.projectId}`, projectId: x.projectId } })),
    ...surveysOf(p.accountSk).map((x) => ({ period: String(x.surveyYear), note: `Household survey summary, ${x.nResponses} responses (aggregated).`,
      citation: { label: `${S.source}, survey ${x.surveyYear}`, summaryId: x.summaryId } })),
  ];
  return lines.sort((a, b) => a.period.localeCompare(b.period));
}
