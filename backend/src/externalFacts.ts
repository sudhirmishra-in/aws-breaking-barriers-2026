import { DynamoDBClient } from "@aws-sdk/client-dynamodb";
import { DynamoDBDocumentClient, QueryCommand } from "@aws-sdk/lib-dynamodb";

/** External environmental facts (Component 5): pre-aggregated, country-level, cached in DynamoDB by an offline ingest. Public data, not FTUSA-curated. */
export interface ExternalFact {
  dataset: string; theme: string; indicator: string; value: number | null; unit: string; period: string; method: string;
  baselineValue: number | null; baselineDeltaPct: number | null; baselinePeriod: string | null; isProjection: boolean; isStandIn: boolean; retrievedAt: string | null;
}
export interface FactsPort { forCountry(country: string | null | undefined, themes: string[]): Promise<ExternalFact[]> }

/** Same normalization as external_data/keys.py (kept in step by a test). */
const ALIASES: Record<string, string> = { "cote d'ivoire": "côte d'ivoire", "ivory coast": "côte d'ivoire", "cote divoire": "côte d'ivoire", "bolivia (plurinational state of)": "bolivia", usa: "united states" };
export function countryKey(location: string | null | undefined): string | null {
  if (!location) return null;
  let s = location.replace("’", "'").trim();
  if (s.includes(",")) s = s.slice(s.lastIndexOf(",") + 1);
  s = s.replace(/\s+/g, " ").trim().toLowerCase();
  if (!s || s.length > 80) return null;
  return `${ALIASES[s] ?? s}#COUNTRY`;
}
/** Challenge tag -> data theme (only "climate" has cached data today). */
export const TAG_THEMES: Record<string, string[]> = { climate_weather: ["climate"], water: ["water"], soil_land: ["soil_land"], market_price: ["market"], biodiversity_conservation: ["biodiversity", "soil_land"], social_community: ["tenure"], infrastructure: ["elevation"] };
export const themesFor = (tags: string[]) => [...new Set(tags.flatMap((t) => TAG_THEMES[t] ?? []))];

export class DdbFacts implements FactsPort {
  private d: DynamoDBDocumentClient;
  constructor(private table: string, client = new DynamoDBClient({})) { this.d = DynamoDBDocumentClient.from(client); }
  async forCountry(country: string | null | undefined, themes: string[]) {
    const key = countryKey(country);
    if (!key || !themes.length) return [];
    const r = await this.d.send(new QueryCommand({ TableName: this.table, KeyConditionExpression: "region_key = :k", ExpressionAttributeValues: { ":k": key } })); // one partition, never a scan
    return (r.Items ?? []).filter((i) => themes.includes(String(i.theme)) && String(i.fact_key).endsWith("#current")).map((i) => {
      const [dataset, indicator] = String(i.fact_key).split("#");
      const n = (x: unknown) => (x === undefined || x === null ? null : Number(x));
      return { dataset, theme: String(i.theme), indicator, value: n(i.value), unit: String(i.unit ?? ""), period: String(i.period ?? ""), method: String(i.method ?? ""), baselineValue: n(i.baseline_value),
        baselineDeltaPct: n(i.baseline_delta_pct), baselinePeriod: i.baseline_period ? String(i.baseline_period) : null, isProjection: !!i.is_projection, isStandIn: !!i.is_stand_in, retrievedAt: i.retrieved_at ? String(i.retrieved_at) : null };
    });
  }
}

const TITLES: Record<string, string> = { ytd_rainfall_mm: "Rainfall, year to date" };
/** Projection for the browser. A stand-in (failed fetch) is never shown as a figure. Real data, but a single reference point: labelled as such. */
export function factEvidence(f: ExternalFact, country: string) {
  const delta = f.baselineDeltaPct, sign = delta !== null && delta >= 0 ? "+" : "";
  return {
    evidenceId: `${f.dataset}#${f.indicator}`, kind: "external_fact" as const, title: TITLES[f.indicator] ?? f.indicator.replace(/_/g, " "),
    finding: `${f.value} ${f.unit} (${f.period})${delta !== null && f.baselineValue !== null ? `, ${sign}${delta}% against the ${f.baselinePeriod ?? "baseline"} average of ${f.baselineValue} ${f.unit}` : ""}. Measured at a reference point for ${country}, not a country average.`,
    geography: country, period: f.period, tag: f.theme, source: `${f.dataset === "open_meteo" ? "ERA5 reanalysis via Open-Meteo" : f.dataset}`, origin: "external_imported" as const, curationStatus: "not_curated" as const,
    illustrative: false, standards: [] as string[], method: f.method, citation: { label: `${f.dataset}, ${f.period}`, dataVersion: f.retrievedAt ?? "unknown" },
  };
}
