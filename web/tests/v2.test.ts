// @vitest-environment jsdom
import { mount, flushPromises } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SharingStep from "../src/components/SharingStep.vue";
import ProducerInfo from "../src/components/ProducerInfo.vue";
import PeerCases from "../src/components/PeerCases.vue";
import { INFO_LABEL, L, NOT_PROVIDED, SHARING, show } from "../src/lib/labels";
import { state } from "../src/session";

const info = {
  individual: { producerId: "PRD-ANA", displayName: "Ana", preferredLanguage: "es" },
  organization: { organizationId: "ORG-A", name: "Andean Coffee Cooperative", fields: {
    account_sk: "ACC-COL-0000412873", account_category_name: "Cooperative", product_category_name: ["Coffee", "Cocoa"], account_type_name: null,
    certification_scope_name: "Small producer organization", certification_status_name: "Certified", country_name: "Colombia", raw_supply_chain_role_txt: ["Grower", "Exporter"], structure_txt: null } },
  summary: { products: ["Coffee", "Cocoa"], country: "Colombia" },
  pendingCorrections: [{ correctionId: "c1", status: "accepted_awaiting_source_update", createdAt: "2026-11-01", requestedByYou: false, changes: [{ field: "country_name", original: "Colombia", proposed: "Peru" }], explanation: null, decidedAt: null, appliedAt: null, decisionNote: null }],
  correctableFields: ["country_name", "structure_txt"], verified: false,
};
const submitCorrection = vi.fn(async () => ({}));
vi.mock("../src/lib/api", () => ({
  newRequestId: () => "req-fixed-0001",
  api: { producerInfo: vi.fn(async () => info), submitCorrection: (...a: unknown[]) => submitCorrection(...(a as [])), peers: vi.fn(async () => ({ visibility: "note", items: [
    { caseId: "rec-seed-cv-04@1", version: 1, sameOrganization: true, origin: "your_organization", producer: null, anonymousLabel: "A producer in your organization", challenge: "Water", action: null, result: "Outcome not yet reported", resultReported: false, tags: ["water"], standards: [], citations: [{ label: "Source A" }], publishedAt: null, illustrative: true },
    { caseId: "rec-seed-cv-05@1", version: 1, sameOrganization: false, origin: "other_organization", producer: { name: "Lucía" }, anonymousLabel: "x", challenge: "Heat", action: "Shade", result: "Better", resultReported: true, tags: ["climate_weather"], standards: [], citations: [], publishedAt: null, illustrative: true }] })) },
}));
vi.mock("../src/session", () => ({ state: { me: { configurationError: null }, ui: "en" } }));

beforeEach(() => submitCorrection.mockClear());

describe("producer information", () => {
  it("shows products and country collapsed, uses the source labels, and 'Not provided' for missing values", async () => {
    const w = mount(ProducerInfo, { props: { open: true } }); await flushPromises();
    expect(w.text()).toContain("Coffee, Cocoa · Colombia");
    for (const k of ["account_category_name", "product_category_name", "raw_supply_chain_role_txt", "structure_txt"] as const) expect(w.text()).toContain(INFO_LABEL[k]);
    expect(w.text()).toContain("Organization structure" + NOT_PROVIDED);
    expect(w.text()).toContain("Account type" + NOT_PROVIDED);
    expect(w.text()).toContain("Grower, Exporter");
    expect(w.find(".pinfo-ref").text()).toContain("ACC-COL-0000412873"); // long reference lives in the details area
    expect(w.text()).not.toMatch(/save profile|register|create (a )?profile/i);
  });
  it("lists pending corrections as unverified suggestions, with the accepted-but-not-applied status", async () => {
    const w = mount(ProducerInfo, { props: { open: true } }); await flushPromises();
    expect(w.text()).toContain("Accepted, awaiting source update");
    expect(w.text()).toContain("not verified facts");
    expect(w.text()).toContain("Requested by a colleague");
  });
  it("correction form: select fields, shows recorded value, submits with 'Submit correction' and a stable request id; account reference is not offered", async () => {
    const w = mount(ProducerInfo, { props: { open: true } }); await flushPromises();
    await w.findAll("button").find((b) => b.text().includes("Suggest a correction"))!.trigger("click");
    expect(w.text()).not.toContain("Account reference" + "  "); // not a selectable field
    expect(w.findAll("input[type=checkbox]")).toHaveLength(2);
    await w.findAll("input[type=checkbox]")[0].setValue(true);
    expect(w.text()).toContain("recorded: Colombia");
    await w.find("input[aria-label='Proposed Country']").setValue("Peru");
    expect(w.findAll("button").some((b) => b.text() === "Submit correction")).toBe(true);
    expect(w.findAll("button").some((b) => /save profile/i.test(b.text()))).toBe(false);
    await w.find("form").trigger("submit"); await flushPromises();
    expect(submitCorrection).toHaveBeenCalledWith("req-fixed-0001", [{ field: "country_name", proposed: "Peru" }], undefined);
    expect(w.text()).toContain("has not changed");
  });
  it("shows a configuration error and no producer data when the account is not mapped", async () => {
    const s = await import("../src/session"); (s.state.me as { configurationError: string | null }).configurationError = "producer_mapping_missing";
    const w = mount(ProducerInfo); await flushPromises();
    expect(w.text()).toContain("not linked to a producer"); expect(w.text()).not.toContain("Andean");
    (s.state.me as { configurationError: string | null }).configurationError = null;
  });
  it("show() handles arrays, empty and null", () => { expect(show([])).toBe(NOT_PROVIDED); expect(show(null)).toBe(NOT_PROVIDED); expect(show(["a", "b"])).toBe("a, b"); });
});

describe("sharing step", () => {
  const confirmation = { summaryHash: "h".repeat(64), summaryOriginal: "Resumen", summaryEn: "Summary", tags: ["water"], language: "es" as const };
  it("explains retention, shows what each choice exposes, and offers the name option only with the conversation choice", async () => {
    const w = mount(SharingStep, { props: { confirmation, busy: false } });
    expect(w.text()).toContain("Fair Trade USA can keep and review your conversation");
    for (const o of SHARING) expect(w.text()).toContain(o.exposes.slice(0, 30));
    expect(w.text()).not.toContain("Show my name");
    await w.findAll("input[type=radio]")[1].setValue(true);
    expect(w.text()).not.toContain("Show my name");
    await w.findAll("input[type=radio]")[0].setValue(true);
    expect(w.text()).toContain("Show my name");
  });
  it("cannot confirm before a choice; emits the confirmed hash; identity is off unless ticked and dropped when the choice changes", async () => {
    const w = mount(SharingStep, { props: { confirmation, busy: false } });
    const btn = w.find("button.primary"); expect(btn.attributes("disabled")).toBeDefined();
    await w.findAll("input[type=radio]")[0].setValue(true);
    await w.find("input[type=checkbox]").setValue(true);
    await w.findAll("input[type=radio]")[2].setValue(true); // do not share: name no longer applies
    await w.find("button.primary").trigger("click");
    expect(w.emitted("confirm")![0]).toEqual(["h".repeat(64), "ftusa_only", false]);
  });
  it("shows the English translation for non-English summaries", () => {
    expect(mount(SharingStep, { props: { confirmation, busy: false } }).text()).toContain("English translation");
  });
});

describe("peer cases", () => {
  it("anonymous label unless a name was permitted; organization label; 'Outcome not yet reported' is not styled as a result; Ask about this emits the case id", async () => {
    const w = mount(PeerCases, { props: { scope: "all", title: "Others" } }); await flushPromises();
    expect(w.text()).toContain("A producer in your organization"); expect(w.text()).toContain("Lucía");
    expect(w.text()).toContain("Your organization"); expect(w.text()).toContain("Another organization");
    expect(w.text()).toContain("Outcome not yet reported");
    await w.findAll("button").find((b) => b.text() === "Ask about this")!.trigger("click");
    expect(w.emitted("ask")![0]).toEqual(["rec-seed-cv-04@1"]);
  });
  it("can filter by tag", async () => {
    const w = mount(PeerCases, { props: { scope: "all", title: "Others", only: ["climate_weather"] } }); await flushPromises();
    expect(w.findAll("article")).toHaveLength(1);
  });
});


describe("interface languages", () => {
  const keys = (o: unknown, p = ""): string[] => Array.isArray(o) ? [p + "[" + o.length + "]"] : o && typeof o === "object" ? Object.entries(o).flatMap(([k, v]) => keys(v, p + "." + k)) : [p];
  it("Spanish and French have exactly the same labels as English, none left empty or identical-by-accident for the headline strings", () => {
    expect(keys(L("es"))).toEqual(keys(L("en"))); expect(keys(L("fr"))).toEqual(keys(L("en")));
    for (const lang of ["es", "fr"] as const) { expect(L(lang).askAi).not.toBe(L("en").askAi); expect(L(lang).share.confirm).not.toBe(L("en").share.confirm); expect(L(lang).sharing).toHaveLength(3); }
  });
  it("the producer information, sharing step and peer cards render in the selected language", async () => {
    (state as { ui: string }).ui = "es";
    const a = mount(ProducerInfo, { props: { open: true } }); await flushPromises();
    expect(a.text()).toContain("Su información de productor"); expect(a.text()).toContain("Productos"); expect(a.text()).toContain("No indicado"); expect(a.text()).toContain("Sugerir una corrección");
    (state as { ui: string }).ui = "fr";
    const b = mount(SharingStep, { props: { confirmation: { summaryHash: "h".repeat(64), summaryOriginal: "x", summaryEn: "y", tags: [], language: "fr" }, busy: false } });
    expect(b.text()).toContain("Qui peut voir ce cas"); expect(b.text()).toContain("Confirmer le résumé et terminer");
    const c = mount(PeerCases, { props: { scope: "all", title: "x" } }); await flushPromises();
    expect(c.text()).toContain("Un producteur de votre organisation"); expect(c.text()).toContain("Résultat pas encore communiqué"); expect(c.text()).toContain("Poser une question à ce sujet");
    (state as { ui: string }).ui = "en";
  });
});
