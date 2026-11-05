// LOCAL tests: external environmental facts as evidence (fake facts port, in-memory store). No AWS.
import { describe, expect, it } from "vitest";
import type { AgentClient, AgentTurnRequest, AgentTurnResponse } from "../src/agent";
import type { Organization, ProducerProfile } from "../src/contracts";
import { countryKey, factEvidence, themesFor, type ExternalFact, type FactsPort } from "../src/externalFacts";
import type { Principal } from "../src/service";
import { MemoryStore } from "../src/store";
import { ServiceV2 } from "../src/serviceV2";

describe("country keys (parity with external_data/keys.py)", () => {
  it("every location shape resolves to one country partition", () => {
    for (const [raw, key] of [["Colombia", "colombia#COUNTRY"], ["Huila, Colombia", "colombia#COUNTRY"], ["Chiapas, Mexico", "mexico#COUNTRY"], ["Nawa (Soubré), Côte d'Ivoire", "côte d'ivoire#COUNTRY"],
      ["Cote d'Ivoire", "côte d'ivoire#COUNTRY"], ["Côte d’Ivoire", "côte d'ivoire#COUNTRY"], ["Ivory Coast", "côte d'ivoire#COUNTRY"], ["  Copán,  Honduras ", "honduras#COUNTRY"]] as const) expect(countryKey(raw), raw).toBe(key);
    for (const bad of [null, undefined, "", "   ", "x".repeat(200)]) expect(countryKey(bad as never)).toBeNull();
  });
  it("tags map to themes; unknown tags give none", () => {
    expect(themesFor(["climate_weather"])).toEqual(["climate"]); expect(themesFor(["biodiversity_conservation"])).toEqual(["biodiversity", "soil_land"]); expect(themesFor(["nonsense"])).toEqual([]);
  });
});

const fact = (over: Partial<ExternalFact> = {}): ExternalFact => ({ dataset: "open_meteo", theme: "climate", indicator: "ytd_rainfall_mm", value: 812.4, unit: "mm", period: "2026 YTD (01-01 to 10-28)", method: "ERA5 via Open-Meteo at the country centroid",
  baselineValue: 700, baselineDeltaPct: 16.1, baselinePeriod: "1991-2020 (same window)", isProjection: false, isStandIn: false, retrievedAt: "2026-11-04T03:17:00Z", ...over });
describe("projection", () => {
  it("states the figure, the baseline and that it is a reference point, labelled external and not curated", () => {
    const e = factEvidence(fact(), "Colombia");
    expect(e).toMatchObject({ kind: "external_fact", origin: "external_imported", curationStatus: "not_curated", illustrative: false, standards: [] });
    expect(e.finding).toContain("812.4 mm"); expect(e.finding).toContain("+16.1%"); expect(e.finding).toContain("1991-2020"); expect(e.finding).toContain("reference point");
    expect(e.finding).not.toMatch(/country average of/i); expect(e.source).toBe("ERA5 reanalysis via Open-Meteo"); expect(e.citation.dataVersion).toBe("2026-11-04T03:17:00Z");
  });
  it("a negative delta carries its sign", () => { expect(factEvidence(fact({ baselineDeltaPct: -9.5 }), "Peru").finding).toContain("-9.5%"); });
});

class Stub implements AgentClient {
  async turn(req: AgentTurnRequest): Promise<AgentTurnResponse> {
    const playback = req.context.mode === "intake" && req.context.allowPlayback;
    return { reply: "r", language: req.context.language, phase: req.context.mode === "guidance" ? "guidance" : playback ? "playback" : "intake", playbackSummary: playback ? "late rain" : null, title: null,
      summaryEn: req.context.mode === "guidance" ? "EN" : null, summaryOriginal: req.context.mode === "guidance" ? "EN" : null, challengeTags: req.context.mode === "guidance" ? ["climate_weather"] : [], piiFlag: false, piiTypes: [], evidence: { status: "unavailable" } };
  }
}
const org = (country: string): Organization => ({ organizationId: "ORG", name: "O", info: { accountSk: "A", accountCategoryName: "Cooperative", productCategoryName: ["Coffee"], accountTypeName: null, certificationScopeName: null, certificationStatusName: null, countryName: country, rawSupplyChainRoleTxt: [], structureTxt: null } });
const prof: ProducerProfile = { producerId: "PRD", displayName: "Ana", entityType: "cooperative", location: "Huila, Colombia", crop: "coffee", preferredLanguage: "en", organizationId: "ORG" };
const ana: Principal = { sub: "s", groups: ["producer"] };
async function world(country: string, facts: ExternalFact[]) {
  const store = new MemoryStore(); store.orgs.set("ORG", org(country)); store.profiles.set("s", prof);
  const calls: { country: string | null | undefined; themes: string[] }[] = [];
  const port: FactsPort = { forCountry: async (c, themes) => { calls.push({ country: c, themes }); return facts; } };
  const svc = new ServiceV2({ store, agent: new Stub(), facts: port });
  const id = (await svc.create(ana, undefined, "req-1-xxxxxxxx")).conversation.conversationId;
  await svc.message(ana, id, "req-2-xxxxxxxx", "a"); await svc.message(ana, id, "req-3-xxxxxxxx", "b");
  const h = (await svc.playback(ana, id, { requestId: "req-4-xxxxxxxx", decision: "confirm" })).confirmation!.summaryHash;
  await svc.finalize(ana, id, { requestId: "req-5-xxxxxxxx", summaryHash: h, sharing: "ftusa_only", identityPermitted: false });
  return { svc, id, calls };
}
describe("evidence endpoint with external facts", () => {
  it("uses the organization's country and the record's own tags, and returns the real fact as external evidence", async () => {
    const { svc, id, calls } = await world("Colombia", [fact()]);
    const r = await svc.evidence(ana, id);
    expect(calls.at(-1)).toEqual({ country: "Colombia", themes: ["climate"] }); expect(r.facts).toHaveLength(1); expect(r.facts[0].finding).toContain("812.4 mm"); expect(r.limitation).toBeNull();
  });
  it("drops a stand-in (failed fetch) and a missing value instead of showing a number", async () => {
    const { svc, id } = await world("Colombia", [fact({ isStandIn: true, value: null }), fact({ indicator: "x", value: null })]);
    const r = await svc.evidence(ana, id); expect(r.facts).toHaveLength(0);
  });
  it("a failing facts store degrades to no facts, not an error", async () => {
    const store = new MemoryStore(); store.orgs.set("ORG", org("Colombia")); store.profiles.set("s", prof);
    const svc = new ServiceV2({ store, agent: new Stub(), facts: { forCountry: async () => { throw new Error("ddb down"); } } });
    const id = (await svc.create(ana, undefined, "req-1-yyyyyyyy")).conversation.conversationId;
    await svc.message(ana, id, "req-2-yyyyyyyy", "a"); await svc.message(ana, id, "req-3-yyyyyyyy", "b");
    const h = (await svc.playback(ana, id, { requestId: "req-4-yyyyyyyy", decision: "confirm" })).confirmation!.summaryHash;
    await svc.finalize(ana, id, { requestId: "req-5-yyyyyyyy", summaryHash: h, sharing: "ftusa_only", identityPermitted: false });
    expect((await svc.evidence(ana, id)).facts).toEqual([]);
  });
});

describe("facts handed to the agent's closing turn", () => {
  it("only the producer's own country, only real values, never a stand-in", async () => {
    const seen: { externalFacts?: unknown[] }[] = [];
    const store = new MemoryStore(); store.orgs.set("ORG", org("Colombia")); store.profiles.set("s", prof);
    const agent = new Stub(); const orig = agent.turn.bind(agent); agent.turn = async (req) => { if (req.context.mode === "guidance") seen.push(req.context as never); return orig(req); };
    const calls: string[] = [];
    const svc = new ServiceV2({ store, agent, facts: { forCountry: async (c) => { calls.push(String(c)); return [fact(), fact({ indicator: "x", isStandIn: true, value: null }), fact({ indicator: "p", isProjection: true })]; } } });
    const id = (await svc.create(ana, undefined, "req-1-zzzzzzzz")).conversation.conversationId;
    await svc.message(ana, id, "req-2-zzzzzzzz", "a"); await svc.message(ana, id, "req-3-zzzzzzzz", "b");
    await svc.playback(ana, id, { requestId: "req-4-zzzzzzzz", decision: "confirm" });
    expect([...new Set(calls)]).toEqual(["Colombia"]); expect(seen[0].externalFacts).toHaveLength(1); // every turn looks up only the producer's own country
    expect(JSON.stringify(seen[0].externalFacts)).toContain("812.4");
  });
});
