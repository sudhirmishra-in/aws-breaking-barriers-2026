import raw from "./data/ftusa/standard_clauses.json";

/**
 * Fair Trade USA standards clauses (Component 4) as evidence. The API Lambda reads them; the agent never does.
 * Scope comes from the caller's server-side record: the standard (APS for farms, FPS for processing operations) and the amendment
 * variants that apply. A clause that does not apply to the caller is never returned, whatever the query says.
 * The clause text states what the standard requires; it never says whether this producer complies.
 */
export interface StandardClause {
  clauseId: string; standard: "APS" | "FPS"; code: string; module: string; subModule: string; objective: string;
  question: Partial<Record<Lang, string>> & { en: string }; intent: Partial<Record<Lang, string>>;
  appliesTo: string[]; isVariant: boolean; showFor: string[]; hideFor: string[]; timeline: string | null; priority: boolean; tags: string[]; contentHash: string;
}
type Lang = "en" | "es" | "fr";
const DATA = raw as unknown as { dataVersion: string; source: string; origin: string; curationStatus: string; clauses: StandardClause[] };
export const STANDARDS_DATA_VERSION = DATA.dataVersion;
export const STANDARDS_SOURCE = DATA.source;
const BY_ID = new Map(DATA.clauses.map((c) => [c.clauseId, c]));
export const clauseById = (id: string) => BY_ID.get(id);
/** For reviewer-entered `standards` lists: keeps only clause ids that exist, so an invented id never reaches a producer. */
export const knownClauseIds = (ids: string[]) => [...new Set(ids)].filter((id) => BY_ID.has(id));

export const MAX_LIMIT = 5;
const TOPIC_CHARS = 200;
const INTENT_CHARS = 600;

// ---------------------------------------------------------------- scope (trusted context only)
const CROP_AMENDMENTS: Record<string, string> = { cocoa: "Cocoa or Palm producer", cacao: "Cocoa or Palm producer", palm: "Cocoa or Palm producer", "palm oil": "Cocoa or Palm producer" };
export const applicableStandard = (entityType?: string | null): "APS" | "FPS" => ((entityType ?? "").trim().toLowerCase() === "processing_operation" ? "FPS" : "APS");
/** Only the cocoa / palm amendment can be derived from data we hold; others (Coffee GCP, US, PMT Adaptation) need facts we do not have. */
export function amendmentsFor(crop?: string | null, extra: string[] = []): Set<string> {
  const out = new Set(extra); const a = CROP_AMENDMENTS[(crop ?? "").trim().toLowerCase()];
  if (a) out.add(a);
  return out;
}
export function applies(c: StandardClause, entityType: string | null | undefined, amendments: Set<string>): boolean {
  const et = (entityType ?? "unknown").trim().toLowerCase() || "unknown";
  if (c.standard !== applicableStandard(et)) return false;
  if (c.appliesTo.length && !c.appliesTo.includes(et)) return false;
  if (c.isVariant && !c.showFor.some((a) => amendments.has(a))) return false;
  return !c.hideFor.some((a) => amendments.has(a));
}

// ---------------------------------------------------------------- local retriever (BM25, same rules as ftusa-data/c4/retriever.py)
const STOP = new Set(`a an and are as at be by for from has have in is it its of on or shall that the their this to with which who
whom will be been can may must not all any each other such than these those into per
el la los las de del y o en un una que por para con se su sus al es lo como mas
le les des du et ou un une que qui pour par avec sur dans au aux ce ces son sa ses est`.split(/\s+/));
/** Topic words a producer is likely to use (ES/FR), mapped to the English the standards use. FPS has English text only. */
const GLOSSARY: Record<string, string> = {
  agua: "water", eau: "water", riego: "irrigation", irrigation: "irrigation", sequia: "drought", secheresse: "drought", lluvia: "rain", pluie: "rain", clima: "climate", climat: "climate",
  suelo: "soil", sol: "soil", erosion: "erosion", fertilizante: "fertilizer", engrais: "fertilizer", plaga: "pest", plagas: "pests", ravageur: "pest", plaguicida: "pesticide", pesticida: "pesticide",
  pesticide: "pesticide", agroquimico: "agrochemical", quimicos: "chemicals", chimiques: "chemicals", bosque: "forest", foret: "forest", deforestacion: "deforestation", deforestation: "deforestation",
  arboles: "trees", arbres: "trees", biodiversidad: "biodiversity", biodiversite: "biodiversity", residuos: "waste", basura: "waste", dechets: "waste", trabajadores: "workers", trabajador: "worker",
  travailleurs: "workers", salario: "wage", salarios: "wages", salaire: "wage", trabajo: "work", travail: "work", infantil: "child", ninos: "children", enfants: "children", mujeres: "women",
  femmes: "women", genero: "gender", jovenes: "youth", jeunes: "youth", salud: "health", sante: "health", seguridad: "safety", securite: "safety", accidente: "accident", capacitacion: "training",
  formacion: "training", formation: "training", educacion: "education", education: "education", credito: "credit", prestamo: "loan", pret: "loan", ahorro: "savings", epargne: "savings",
  prima: "premium", prime: "premium", comite: "committee", asamblea: "assembly", assemblee: "assembly", precio: "price", prix: "price", mercado: "market", marche: "market", contrato: "contract",
  contrat: "contract", discriminacion: "discrimination", acoso: "harassment", harcelement: "harassment", queja: "grievance", quejas: "grievances", plainte: "grievance", vivienda: "housing", logement: "housing",
  cooperativa: "cooperative", socios: "members", membres: "members", trazabilidad: "traceability", tracabilite: "traceability", cosecha: "harvest", recolte: "harvest",
};
const fold = (s: string) => s.toLowerCase().normalize("NFKD").replace(/\p{M}/gu, "");
const words = (s: string) => fold(s).match(/[a-z0-9]+/g) ?? [];
export const tokens = (s: string) => words(s).filter((w) => w.length >= 3 && !STOP.has(w)).map((w) => w.slice(0, 7));
const queryTokens = (q: string) => new Set([...tokens(q), ...words(q).flatMap((w) => (GLOSSARY[w] ? tokens(GLOSSARY[w]) : []))]);
const clauseText = (c: StandardClause, lang: Lang) => `${c.module}. ${c.subModule}. ${c.objective}. ${c.question[lang] || c.question.en} ${c.intent[lang] || c.intent.en || ""}`;

export interface StandardsQuery { text: string; standard: "APS" | "FPS"; limit: number }
export interface StandardsRetriever { search(q: StandardsQuery): Promise<{ clauseId: string; score: number }[]> }

export class LocalStandardsRetriever implements StandardsRetriever {
  private docs: { id: string; std: string; tf: Map<string, number>; len: number }[];
  private idf = new Map<string, number>(); private avg: number;
  constructor(clauses: StandardClause[] = DATA.clauses, private k1 = 1.4, private b = 0.75) {
    this.docs = clauses.map((c) => {
      const text = (["en", "es", "fr"] as Lang[]).filter((l) => l === "en" || c.question[l]).map((l) => clauseText(c, l)).join(" ");
      const tf = new Map<string, number>(); const t = tokens(text);
      for (const w of t) tf.set(w, (tf.get(w) ?? 0) + 1);
      return { id: c.clauseId, std: c.standard, tf, len: t.length };
    });
    this.avg = this.docs.reduce((s, d) => s + d.len, 0) / Math.max(this.docs.length, 1);
    const df = new Map<string, number>();
    for (const d of this.docs) for (const w of d.tf.keys()) df.set(w, (df.get(w) ?? 0) + 1);
    const n = this.docs.length;
    for (const [w, f] of df) this.idf.set(w, Math.log(1 + (n - f + 0.5) / (f + 0.5)));
  }
  async search(q: StandardsQuery) {
    const qt = queryTokens(q.text); const out: { clauseId: string; score: number }[] = [];
    for (const d of this.docs) {
      if (d.std !== q.standard) continue;
      let s = 0;
      for (const w of qt) { const f = d.tf.get(w); if (f) s += this.idf.get(w)! * f * (this.k1 + 1) / (f + this.k1 * (1 - this.b + this.b * d.len / this.avg)); }
      if (s > 0) out.push({ clauseId: d.id, score: s });
    }
    out.sort((a, b) => b.score - a.score); // stable: ties keep source order
    const top = out[0]?.score ?? 1;
    return out.slice(0, q.limit).map((x) => ({ clauseId: x.clauseId, score: Math.round((x.score / top) * 1e4) / 1e4 }));
  }
}

// ---------------------------------------------------------------- projection and flow
const excerpt = (s: string, n = INTENT_CHARS) => { const t = (s ?? "").split(/\s+/).filter(Boolean).join(" "); return t.length <= n ? t : t.slice(0, n - 1).replace(/\s+\S*$/, "") + "…"; };

/** Projection sent to the browser or the model, in the same evidence shape as public project records and external facts. */
export function standardEvidence(c: StandardClause, score: number, language: string) {
  const lang: Lang = language === "es" || language === "fr" ? language : "en";
  const textLanguage: Lang = c.question[lang] ? lang : "en";
  return {
    evidenceId: c.clauseId, kind: "standard_clause" as const, title: `Fair Trade USA ${c.standard} ${c.code}`, finding: c.question[textLanguage]!,
    intent: excerpt(c.intent[textLanguage] ?? c.intent.en ?? ""), textLanguage, geography: "", period: c.timeline ?? "", tag: c.tags[0] ?? "",
    source: `Fair Trade USA ${c.standard === "FPS" ? "Factory Production Standard" : "Agricultural Production Standard"}`, origin: "ftusa_authored" as const,
    curationStatus: "ftusa_curated" as const, illustrative: false, taxonomy: [c.module, c.subModule].filter(Boolean).join(" / "), objective: c.objective,
    priority: c.priority, challengeTags: c.tags, score, standards: [c.clauseId],
    citation: { label: `Fair Trade USA ${c.standard} ${c.code}`, clauseId: c.clauseId, dataVersion: STANDARDS_DATA_VERSION, contentHash: c.contentHash },
  };
}
export type StandardEvidence = ReturnType<typeof standardEvidence>;

/** Trusted inputs only: built server-side from the caller's own record and profile, never from a request body. */
export interface StandardsScope { entityType?: string | null; crop?: string | null; extraAmendments?: string[] }

/**
 * Standards evidence for one topic (e.g. a confirmed summary plus its challenge tags). Bounded, scoped, cited.
 * Missing evidence is reported as a limitation, never invented. A retriever failure degrades to "unavailable".
 */
export async function standardsFor(scope: StandardsScope, topic: string, language = "en", limit = 3, retriever: StandardsRetriever = defaultRetriever()) {
  const text = topic.split(/\s+/).filter(Boolean).join(" ").slice(0, TOPIC_CHARS);
  const standard = applicableStandard(scope.entityType);
  const amendments = amendmentsFor(scope.crop, scope.extraAmendments);
  const k = Math.max(1, Math.min(Math.trunc(limit) || 3, MAX_LIMIT));
  const base = { kind: "standards" as const, topic: text, standard, dataVersion: STANDARDS_DATA_VERSION };
  if (!text) return { ...base, status: "unavailable" as const, items: [] as StandardEvidence[], limitation: "No topic to look up." };
  let hits: { clauseId: string; score: number }[];
  try { hits = await retriever.search({ text, standard, limit: Math.min(k * 6, 30) }); }
  catch { return { ...base, status: "unavailable" as const, items: [] as StandardEvidence[], limitation: "Standards search is not available right now." }; }
  const items: StandardEvidence[] = [];
  for (const h of hits) {
    const c = BY_ID.get(h.clauseId); // a retriever can only nominate ids; content always comes from the bundled clause
    if (!c || !applies(c, scope.entityType, amendments)) continue;
    items.push(standardEvidence(c, h.score, language));
    if (items.length === k) break;
  }
  return items.length
    ? { ...base, status: "ok" as const, items, limitation: null }
    : { ...base, status: "no_match" as const, items, limitation: `No ${standard} clause matched this topic.` };
}

let _default: LocalStandardsRetriever | undefined;
const defaultRetriever = () => (_default ??= new LocalStandardsRetriever());
