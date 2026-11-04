// LOCAL tests of public-project evidence retrieval over the bundled, validated project subset (no AWS).
import { describe, expect, it } from "vitest";
import { isoOf, LocalProjectRetriever, projectById, projectEvidence, PROJECT_DATA_VERSION } from "../src/projectEvidence";
import raw from "../src/data/public_projects.json";

const r = new LocalProjectRetriever();
const ids = async (text: string, extra: object = {}) => (await r.search({ text, limit: 5, ...extra })).map((h) => h.project);

describe("public project retrieval", () => {
  it("finds relevant projects for English, Spanish and French queries about the same concept", async () => {
    for (const q of ["we need shade trees for our coffee farm", "necesitamos árboles de sombra para el café", "nous avons besoin d'arbres d'ombrage"]) {
      const hits = await ids(q);
      expect(hits.length, q).toBeGreaterThan(0);
      expect(hits.every((p) => /tree|árbol|arbol|shade|sombra|reforest|forest|bosque|vivero|nursery|arbre|ombrage/i.test(`${p.title} ${p.description} ${p.subCategory}`)), q).toBe(true);
    }
  });
  it("scope: country and crop are hard filters, never ranking hints", async () => {
    const hits = await ids("water storage tanks for the dry season", { countryIso2: "CO", crop: "coffee" });
    expect(hits.length).toBeGreaterThan(0);
    expect(hits.every((p) => p.countryIso2 === "CO" && p.products.some((x) => /coffee/i.test(x)))).toBe(true);
    expect(await ids("water storage tanks", { countryIso2: "ZZ" })).toHaveLength(0);
  });
  it("returns nothing for an unrelated query instead of weak matches", async () => {
    expect(await ids("quantum chromodynamics lattice")).toHaveLength(0);
  });
  it("projection: public provenance, not curated, no source account, outcome never derived from status, no standards", async () => {
    const [p] = await ids("shade trees", { crop: "cocoa" }).then((x) => (x.length ? x : ids("shade trees")));
    const e = projectEvidence(p);
    expect(e).toMatchObject({ kind: "project_record", origin: "external_imported", curationStatus: "not_curated", outcome: "Outcome not reported", illustrative: false, standards: [] });
    expect(JSON.stringify(e)).not.toMatch(/account_sk|accountSk|sourceAccount/i);
    expect(["Completed", "In Progress", "Planned", "Cancelled"].some((s) => e.recordedStatus === s) || e.recordedStatus.length > 0).toBe(true);
    expect(e.outcome).not.toMatch(/success|improv|increase/i);
  });
  it("citations resolve to the exact source row and data version", async () => {
    const [p] = await ids("soil fertilizer");
    const e = projectEvidence(p);
    expect(projectById(e.citation.projectId)).toEqual(p);
    expect(e.citation).toMatchObject({ dataVersion: PROJECT_DATA_VERSION, contentHash: p.contentHash });
    expect(e.citation.label).toBe(`Premium Projects Environmental.csv, row ${p.sourceRow}`);
  });
  it("the bundled subset excludes rows the pipeline flagged and never carries the internal account key", () => {
    const d = raw as { projects: { dateFlags: string[]; startDate: string }[] };
    expect(d.projects.length).toBeGreaterThan(300);
    expect(d.projects.some((p) => p.dateFlags.includes("start_epoch_placeholder") || p.startDate === "1970-01-01")).toBe(false);
    expect(JSON.stringify(raw)).not.toMatch(/account_sk|accountSk/);
  });
  it("iso mapping handles the Côte d'Ivoire aliases", () => { expect(isoOf("Côte d’Ivoire")).toBe("CI"); expect(isoOf("Cote d'Ivoire")).toBe("CI"); expect(isoOf(null)).toBeNull(); });
});

import { KnowledgeBaseRetriever, projectById as byId } from "../src/projectEvidence";
describe("knowledge base adapter", () => {
  const any = (raw as { projects: { projectId: string; countryIso2: string; products: string[] }[] }).projects.find((p) => p.countryIso2 === "CO" && p.products.some((x) => /coffee/i.test(x)))!;
  const other = (raw as { projects: { projectId: string; countryIso2: string }[] }).projects.find((p) => p.countryIso2 === "PE")!;
  const mk = (results: unknown[]) => new KnowledgeBaseRetriever("KB1", { send: async () => ({ retrievalResults: results as never }) }, (i) => i);
  it("uses only project ids, re-applies scope, drops unknown ids and duplicates, and takes content from the validated rows", async () => {
    const hits = await mk([{ score: 0.9, metadata: { projectId: other.projectId } }, { score: 0.8, metadata: { projectId: any.projectId } }, { score: 0.7, metadata: { projectId: any.projectId } },
      { score: 0.6, metadata: { projectId: "PRJ-FORGED" } }, { score: 0.5, content: { text: "ignored" } }]).search({ text: "x", countryIso2: "CO", crop: "coffee", limit: 3 });
    expect(hits.map((h) => h.project.projectId)).toEqual([any.projectId]);
    expect(hits[0].project).toEqual(byId(any.projectId));
  });
  it("sends the country filter and a bounded result count", async () => {
    let seen: unknown; const r = new KnowledgeBaseRetriever("KB1", { send: async (c) => { seen = c; return {}; } }, (i) => i);
    await r.search({ text: "x".repeat(5000), countryIso2: "CO", limit: 3 });
    const s = seen as { retrievalQuery: { text: string }; retrievalConfiguration: { vectorSearchConfiguration: { numberOfResults: number; filter: unknown } } };
    expect(s.retrievalQuery.text).toHaveLength(1000); expect(s.retrievalConfiguration.vectorSearchConfiguration.numberOfResults).toBeLessThanOrEqual(30);
    expect(s.retrievalConfiguration.vectorSearchConfiguration.filter).toEqual({ equals: { key: "countryIso2", value: "CO" } });
  });
});
