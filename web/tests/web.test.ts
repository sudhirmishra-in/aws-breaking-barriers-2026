// LOCAL MOCK tests (jsdom, stubbed fetch).
import { describe, expect, it, vi } from "vitest";
import { t } from "../src/lib/i18n";
import { api } from "../src/lib/api";
import { ApiFailure } from "../src/types";

describe("i18n", () => {
  it("English and Spanish define the same keys", () => {
    expect(Object.keys(t("es")).sort()).toEqual(Object.keys(t("en")).sort());
    expect(Object.keys(t("es").entity).sort()).toEqual(Object.keys(t("en").entity).sort());
  });
  it("producer screens avoid internal AWS terms", () => {
    const all = JSON.stringify([t("en"), t("es")]).toLowerCase();
    for (const w of ["bedrock", "agentcore", "cognito", "lambda", "dynamodb", "guardrail"]) expect(all).not.toContain(w);
  });
});

describe("api client", () => {
  it("fails with session_expired when no token is held (expired auth path)", async () => {
    const fetchSpy = vi.fn(); vi.stubGlobal("fetch", fetchSpy);
    await expect(api.me()).rejects.toMatchObject({ status: 401, code: "session_expired" } satisfies Partial<ApiFailure>);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

import { renderMarkdown } from "../src/lib/markdown";
describe("markdown", () => {
  it("escapes HTML and renders bold and lists", () => {
    expect(renderMarkdown("<img src=x onerror=alert(1)> **hi**")).toBe("<p>&lt;img src=x onerror=alert(1)&gt; <strong>hi</strong></p>");
    expect(renderMarkdown("- a\n- b")).toBe("<ul><li>a</li><li>b</li></ul>");
  });
});
