// "This producer's existing data" (spec REV-19), joined on producer_id. Source: the team's synthetic dataset
// (data/team-synthetic, every row "synthetic": true). There is no Athena query path yet, so no SQL is returned.
import producers from "../../data/team-synthetic/producers.json";
import projects from "../../data/team-synthetic/projects.json";
import surveys from "../../data/team-synthetic/surveys.json";
import certifications from "../../data/team-synthetic/certifications.json";

export const RELATED_SOURCE = "Team synthetic dataset (fictional, not FTUSA data)";

export function teamProducer(id: string) {
  const p = producers.find((x) => x.producer_id === id);
  return p ? { name: p.org_name, entityType: p.entity_type, crop: p.crop, location: `${p.region}, ${p.country}` } : undefined;
}

export function relatedFor(id: string) {
  return {
    producerId: id,
    source: RELATED_SOURCE,
    query: null as null, // shown only when a real warehouse query exists (REV-20)
    premiumProjects: projects.filter((x) => x.producer_id === id).sort((a, b) => b.year - a.year)
      .map((x) => ({ year: x.year, title: x.title, tags: x.tags, amountUsd: x.amount_usd, status: x.status, outcome: x.outcome_note ?? null })),
    surveys: surveys.filter((x) => x.producer_id === id).sort((a, b) => b.year - a.year)
      .map((x) => ({ year: x.year, topConcern: x.top_reported_challenges?.[0] ?? null, concerns: x.top_reported_challenges ?? [], respondents: x.respondents,
        incomeChangePct: x.avg_income_change_pct, lowerYieldPct: x.share_reporting_lower_yield_pct })),
    certification: certifications.filter((x) => x.producer_id === id)
      .map((x) => ({ standard: x.standard, version: x.standard_version, status: x.status, lastAudit: x.last_audit })),
  };
}
