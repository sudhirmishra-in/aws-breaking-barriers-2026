import raw from "./data/public_projects.json";

/** Public project records as evidence. Origin is the supplied public source data; it is NOT FTUSA-curated and NOT an agent conversation. Outcomes are never derived. */
export interface PublicProject {
  projectId: string; title: string; description: string; country: string | null; countryRaw: string; countryIso2: string | null; region: string; products: string[];
  startDate: string; endDate: string; recordedStatus: string; category: string; subCategory: string; contentHash: string; sourceRow: number; dateFlags: string[];
}
export interface ProjectQuery { text: string; countryIso2?: string | null; crop?: string | null; limit: number }
export interface ProjectRetriever { search(q: ProjectQuery): Promise<{ project: PublicProject; score: number }[]> }

const DATA = raw as { ingestionVersion: string; source: string; projects: PublicProject[] };
export const PROJECT_DATA_VERSION = DATA.ingestionVersion;
export const PROJECT_SOURCE = DATA.source;
export const projectById = (id: string) => DATA.projects.find((p) => p.projectId === id);

const ISO: Record<string, string> = { colombia: "CO", peru: "PE", mexico: "MX", guatemala: "GT", indonesia: "ID", honduras: "HN", ecuador: "EC", philippines: "PH", brazil: "BR",
  "côte d'ivoire": "CI", "cote d'ivoire": "CI", "sri lanka": "LK", rwanda: "RW", india: "IN", vietnam: "VN", nicaragua: "NI", paraguay: "PY", china: "CN", belize: "BZ", "costa rica": "CR", bolivia: "BO", ghana: "GH", ethiopia: "ET" };
export const isoOf = (country?: string | null) => (country ? ISO[country.toLowerCase().replace("’", "'")] ?? null : null);

// Small reviewed concept dictionary so English, Spanish and French queries reach the same English/Spanish source text. A managed Knowledge Base replaces this with semantic retrieval.
const CONCEPTS: Record<string, string[]> = {
  water: ["water", "agua", "eau", "rain", "lluvia", "pluie", "irrigation", "riego", "irrigación", "drought", "sequía", "sequia", "sécheresse", "secheresse", "tank", "tanque", "citerne"],
  soil: ["soil", "suelo", "sol", "fertilizer", "fertilizante", "engrais", "compost", "erosion", "erosión", "degradation", "degradación"],
  trees: ["tree", "trees", "árbol", "árboles", "arbol", "arboles", "arbre", "arbres", "shade", "sombra", "ombrage", "reforestation", "reforestación", "reforestation", "nursery", "vivero", "pépinière", "forest", "bosque", "forêt"],
  pests: ["pest", "pests", "plaga", "plagas", "ravageur", "ravageurs", "disease", "enfermedad", "maladie", "pesticide", "pesticida", "rust", "roya"],
  climate: ["climate", "clima", "climat", "adaptation", "adaptación", "adaptation", "weather", "heat", "calor", "chaleur"],
  waste: ["waste", "residuos", "déchets", "dechets", "garbage", "basura", "pit", "fosa", "recycling", "reciclaje"],
  training: ["training", "capacitación", "capacitacion", "formation", "technical assistance", "asistencia técnica", "assistance technique"],
};
const norm = (s: string) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
const WORD = (s: string) => norm(s).split(/[^a-z0-9]+/).filter((w) => w.length > 2);
const conceptsOf = (text: string) => {
  const n = ` ${norm(text)} `; const words = new Set(WORD(text));
  return Object.entries(CONCEPTS).filter(([, ws]) => ws.some((w) => (w.includes(" ") ? n.includes(norm(w)) : words.has(norm(w))))).map(([c]) => c);
};

/** Deterministic fallback retriever: hard scope filters (country, crop) then concept overlap + word overlap. Returns nothing rather than weak matches. */
export class LocalProjectRetriever implements ProjectRetriever {
  async search(q: ProjectQuery) {
    const want = new Set(conceptsOf(q.text)); const qw = new Set(WORD(q.text));
    const out: { project: PublicProject; score: number }[] = [];
    for (const p of DATA.projects) {
      if (q.countryIso2 && p.countryIso2 !== q.countryIso2) continue;
      if (q.crop && !p.products.some((x) => norm(x).includes(norm(q.crop!)))) continue;
      const text = `${p.title} ${p.description} ${p.subCategory}`; const have = new Set(conceptsOf(text));
      const shared = [...want].filter((c) => have.has(c)).length;
      const overlap = WORD(text).filter((w) => qw.has(w)).length;
      if (!shared) continue; // no shared concept: not relevant, however many stop words overlap
      out.push({ project: p, score: shared * 3 + Math.min(overlap, 5) });
    }
    return out.sort((a, b) => b.score - a.score || a.project.projectId.localeCompare(b.project.projectId)).slice(0, q.limit);
  }
}

/** Projection sent to the browser or the model. Never includes the internal source account reference; outcome is never derived from status. */
export function projectEvidence(p: PublicProject) {
  return {
    evidenceId: p.projectId, kind: "project_record" as const, title: p.title, finding: p.description, geography: [p.region, p.country ?? p.countryRaw].filter(Boolean).join(", "),
    period: [p.startDate, p.endDate].filter(Boolean).join(" to "), tag: p.category, source: `Public project record (${PROJECT_SOURCE})`, origin: "external_imported" as const,
    curationStatus: "not_curated" as const, illustrative: false, recordedStatus: p.recordedStatus, taxonomy: [p.category, p.subCategory].filter(Boolean).join(" / "),
    outcome: "Outcome not reported" as const, standards: [] as string[],
    citation: { label: `${PROJECT_SOURCE}, row ${p.sourceRow}`, projectId: p.projectId, dataVersion: PROJECT_DATA_VERSION, contentHash: p.contentHash },
  };
}
export type ProjectEvidence = ReturnType<typeof projectEvidence>;

/**
 * Managed Bedrock Knowledge Base adapter. The KB only nominates project ids; everything returned to callers comes from the validated, bundled project rows, never from chunk
 * text, and scope (country, crop) is re-applied here so a mis-filtered KB result cannot widen visibility. Falls back to nothing (the caller then uses the local retriever).
 */
export class KnowledgeBaseRetriever implements ProjectRetriever {
  constructor(private kbId: string, private client: { send(cmd: unknown): Promise<{ retrievalResults?: { score?: number; metadata?: Record<string, unknown> }[] }> }, private mkCommand: (input: unknown) => unknown) {}
  async search(q: ProjectQuery) {
    const r = await this.client.send(this.mkCommand({ knowledgeBaseId: this.kbId, retrievalQuery: { text: q.text.slice(0, 1000) },
      retrievalConfiguration: { vectorSearchConfiguration: { numberOfResults: Math.min(30, q.limit * 6),
        ...(q.countryIso2 ? { filter: { equals: { key: "countryIso2", value: q.countryIso2 } } } : {}) } } }));
    const seen = new Set<string>(); const out: { project: PublicProject; score: number }[] = [];
    for (const x of r.retrievalResults ?? []) {
      const id = String(x.metadata?.projectId ?? ""); const project = projectById(id);
      if (!project || seen.has(id)) continue;
      if (q.countryIso2 && project.countryIso2 !== q.countryIso2) continue;
      if (q.crop && !project.products.some((p) => norm(p).includes(norm(q.crop!)))) continue;
      seen.add(id); out.push({ project, score: x.score ?? 0 });
    }
    return out.sort((a, b) => b.score - a.score).slice(0, q.limit);
  }
}
