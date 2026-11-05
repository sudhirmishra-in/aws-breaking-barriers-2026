// LOCAL tests over the bundled FTUSA producer records (Component 3). No AWS call.
import { describe, expect, it } from "vitest";
import producersRaw from "../src/data/ftusa/ftusa_producers.json";
import { FTUSA_SOURCE, ftusaAccountFor, ftusaHistory, ftusaProducer, ftusaRelatedFor } from "../src/ftusaRecords";
import { relatedFor, teamProducer } from "../src/relatedData";

const producers = (producersRaw as unknown as { producers: { displayId: string; accountSk: string; projectCount: number; surveyYears: number[] }[] }).producers;
const withBoth = producers.find((p) => p.projectCount > 0 && p.surveyYears.length > 0)!;

describe("FTUSA records: resolution is server-side and scoped", () => {
  it("unmapped app producers and team-dataset ids get nothing (callers keep relatedData)", () => {
    for (const id of ["SYN-P-001", "P-CO-001", "", "PRD-XXX-9999"]) {
      expect(ftusaAccountFor(id)).toBeUndefined();
      expect(ftusaRelatedFor(id)).toBeUndefined();
      expect(ftusaHistory(id)).toEqual([]);
    }
  });
  it("an account key is never accepted as a producerId and never returned", () => {
    expect(ftusaRelatedFor(withBoth.accountSk)).toBeUndefined();
    const r = ftusaRelatedFor(withBoth.displayId)!;
    expect(JSON.stringify(r).includes(withBoth.accountSk)).toBe(false);
    expect(JSON.stringify(ftusaHistory(withBoth.displayId)).includes(withBoth.accountSk)).toBe(false);
  });
});

describe("FTUSA records: same shapes as relatedData", () => {
  it("relatedFor shape: every key the reviewer screen reads is present", () => {
    const team = relatedFor("P-CO-001");
    const ours = ftusaRelatedFor(withBoth.displayId)!;
    for (const k of Object.keys(team)) expect(k in ours).toBe(true);
    for (const k of Object.keys(team.premiumProjects[0])) expect(k in ours.premiumProjects[0]).toBe(true);
    for (const k of Object.keys(team.surveys[0])) expect(k in ours.surveys[0]).toBe(true);
    for (const k of Object.keys(team.certification[0])) expect(k in ours.certification[0]).toBe(true);
    expect(ours.source).toBe(FTUSA_SOURCE);
  });
  it("teamProducer shape", () => {
    expect(Object.keys(ftusaProducer(withBoth.displayId)!).sort()).toEqual(Object.keys(teamProducer("P-CO-001")!).sort());
  });
  it("fields the source does not hold are null, never estimated", () => {
    const r = ftusaRelatedFor(withBoth.displayId)!;
    expect(r.premiumProjects.length).toBe(withBoth.projectCount);
    for (const x of r.premiumProjects) { expect(x.amountUsd).toBeNull(); expect(x.outcome).toBeNull(); expect(x.citation.projectId).toBe(x.projectId); }
    for (const s of r.surveys) { expect(s.incomeChangePct).toBeNull(); expect(s.topConcern).toBeNull(); expect(s.respondents).toBeGreaterThan(0); }
  });
});

describe("FTUSA records: history", () => {
  it("dated, cited, sorted, and never claims an outcome", () => {
    const h = ftusaHistory(withBoth.displayId);
    expect(h.length).toBe(withBoth.projectCount + withBoth.surveyYears.length);
    expect([...h].sort((a, b) => a.period.localeCompare(b.period))).toEqual(h);
    for (const x of h) expect(x.citation.label.length).toBeGreaterThan(0);
    for (const x of h.filter((y) => "projectId" in y.citation)) expect(x.note).toContain("Outcome not reported");
  });
});
