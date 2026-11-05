// LOCAL tests over the bundled standards clauses (Component 4). No AWS call. Expected clause ids are the results of the
// Python retriever in ftusa-data/c4 for the same inputs, so both implementations rank identically.
import { describe, expect, it } from "vitest";
import { LocalStandardsRetriever, MAX_LIMIT, STANDARDS_DATA_VERSION, applicableStandard, applies, amendmentsFor, clauseById, knownClauseIds, standardsFor, type StandardsRetriever } from "../src/standards";

const coop = { entityType: "cooperative", crop: "coffee" };
const cacao = { entityType: "smallholder", crop: "cacao" };
const factory = { entityType: "processing_operation", crop: "coffee" };
const ids = (r: { items: { evidenceId: string }[] }) => r.items.map((x) => x.evidenceId);

describe("standards: same ranking as the Python retriever", () => {
  const cases: [typeof coop, string, string, string[], string[]][] = [
    [coop, "how should the premium committee be elected", "en", ["APS-1.1.2.b", "APS-1.1.2.c", "APS-1.1.2.e"], ["en", "en", "en"]],
    [coop, "pesticide storage", "en", ["APS-4.4.1.c", "APS-4.4.2.c", "APS-4.5.3.a"], ["en", "en", "en"]],
    [cacao, "trabajo infantil en la cosecha", "es", ["APS-2.2.3.b", "APS-2.2.1.a", "APS-3.4.1.c"], ["es", "es", "es"]],
    [coop, "drought and water for irrigation", "en", ["APS-4.1.2.b", "APS-4.1.2.a", "APS-4.1.1.b"], ["en", "en", "en"]],
    [factory, "overtime hours for workers", "en", ["FPS-3.3.2.c", "FPS-3.3.2.a", "FPS-3.3.2.b"], ["en", "en", "en"]],
    [cacao, "deforestation", "en", ["APS-4.2.2.b_vEUDR", "APS-6.1.4.b_vEUDR", "APS-6.1.4.a_vEUDR"], ["en", "en", "en"]],
    [factory, "salud y seguridad de los trabajadores", "es", ["FPS-4.2.1.a", "FPS-4.1.1.e", "FPS-4.1.1.d"], ["en", "en", "en"]],
    [{ entityType: "unknown", crop: "" }, "grievance mechanism", "en", ["APS-2.4.2.b", "APS-3.7.2.b", "APS-3.7.2.d"], ["en", "en", "en"]],
  ];
  for (const [scope, topic, lang, want, langs] of cases) {
    it(`${scope.entityType}/${scope.crop || "-"}: ${topic}`, async () => {
      const r = await standardsFor(scope, topic, lang);
      expect(r.status).toBe("ok");
      expect(ids(r)).toEqual(want);
      expect(r.items.map((x) => x.textLanguage)).toEqual(langs);
    });
  }
});

describe("standards: scope comes from trusted context", () => {
  const topics = ["premium committee", "pesticide", "child labor", "water", "wages", "deforestation", "grievance", "training", "waste", "uso de pesticidas", "travail des enfants"];
  it("farms get APS, processing operations get FPS, and every clause applies to the caller", async () => {
    for (const t of topics) for (const s of [coop, cacao, factory]) {
      const r = await standardsFor(s, t);
      expect(r.standard).toBe(applicableStandard(s.entityType));
      for (const x of r.items) expect(applies(clauseById(x.evidenceId)!, s.entityType, amendmentsFor(s.crop))).toBe(true);
    }
  });
  it("amendment variants appear only for their amendment, and replace the base clause", async () => {
    for (const t of topics) for (const x of (await standardsFor(coop, t)).items) expect(clauseById(x.evidenceId)!.isVariant).toBe(false);
    const c = (await standardsFor(cacao, "deforestation")).items.map((x) => x.evidenceId);
    expect(c).toContain("APS-4.2.2.b_vEUDR");
    expect(c.includes("APS-4.2.2.b")).toBe(false);
  });
  it("a retriever can only nominate ids: unknown and out-of-scope ids are dropped", async () => {
    const fake: StandardsRetriever = { search: async () => [{ clauseId: "APS-9.9.9.z", score: 1 }, { clauseId: "FPS-3.3.2.a", score: 0.9 }, { clauseId: "APS-1.1.2.b", score: 0.8 }] };
    const r = await standardsFor(coop, "anything", "en", 3, fake);
    expect(ids(r)).toEqual(["APS-1.1.2.b"]);
  });
});

describe("standards: output shape and fallbacks", () => {
  it("evidence items carry a citation, the clause in `standards`, and no compliance claim", async () => {
    const r = await standardsFor(coop, "pesticide storage", "en");
    for (const x of r.items) {
      expect(x.kind).toBe("standard_clause");
      expect(x.origin).toBe("ftusa_authored");
      expect(x.standards).toEqual([x.evidenceId]);
      expect(x.citation.clauseId).toBe(x.evidenceId);
      expect(x.citation.dataVersion).toBe(STANDARDS_DATA_VERSION);
      expect(x.intent.length).toBeLessThanOrEqual(600);
    }
  });
  it("no match, empty topic and retriever failure never invent a clause", async () => {
    expect((await standardsFor(coop, "zxqv blorf")).status).toBe("no_match");
    const empty = await standardsFor(coop, "   ");
    expect(empty.status).toBe("unavailable");
    expect(empty.items).toHaveLength(0);
    const down = await standardsFor(coop, "pesticides", "en", 3, { search: async () => { throw new Error("down"); } });
    expect(down.status).toBe("unavailable");
    expect(down.items).toHaveLength(0);
  });
  it("is bounded", async () => {
    const r = await standardsFor(coop, "x ".repeat(500) + "pesticide", "en", 99);
    expect(r.topic.length).toBeLessThanOrEqual(200);
    expect(r.items.length).toBeLessThanOrEqual(MAX_LIMIT);
  });
  it("reviewer-entered clause ids are validated", () => {
    expect(knownClauseIds(["APS-1.1.2.b", "APS-9.9.9.z", "APS-1.1.2.b"])).toEqual(["APS-1.1.2.b"]);
  });
  it("the local retriever filters by standard before scoring", async () => {
    const r = await new LocalStandardsRetriever().search({ text: "workers overtime", standard: "APS", limit: 30 });
    expect(r.every((x) => x.clauseId.startsWith("APS-"))).toBe(true);
    expect(r[0].score).toBe(1);
  });
});
