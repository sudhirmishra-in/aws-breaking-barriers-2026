// DEV-ONLY LOCAL MOCK (loaded only by `vite dev` with ?mock=producer|reviewer). Never part of the production bundle's behaviour.
import { _setUserForTests } from "./lib/auth";

export function installDevMock(role: "producer" | "reviewer") {
  _setUserForTests({ access_token: "mock", expired: false, state: { returnTo: "/" } } as never);
  const profile = { displayName: "Synthetic Producer One", entityType: "cooperative", location: "Synthetic Highlands (fictional region)", crop: "coffee", preferredLanguage: "en" };
  const item = (id: string, st: string, pii = false) => ({ outcomeId: id, source: "agent conversation", producerId: "SYN-P-001", language: "en", summaryEn: "Late rains reduced yield.", summaryEs: "Las lluvias tardías redujeron la producción.", piiFlag: pii, piiTypes: pii ? ["PHONE"] : [], reviewStatus: st, createdAt: "2026-11-03T14:00:00Z" });
  const routes: Record<string, unknown> = {
    "GET /me": role === "producer" ? { roles: ["producer"], profile, syntheticDemo: true } : { roles: ["reviewer"], syntheticDemo: true },
    "GET /overview": role === "producer" ? { producer: { activeConversation: null } } : { reviewer: { pending: 2, approved: 1, corrected: 1, piiFlagged: 1, recent: [item("rec-1", "pending", true), item("rec-2", "approved")] } },
    "GET /conversations/current": { conversation: null },
    "GET /reviews": { items: [item("rec-1", "pending", true), item("rec-2", "approved")] },
    "POST /transcribe": { text: "The rains came late this year and our harvest was smaller than usual.", language: "en" },
    "POST /ask": { answer: "I'm sorry, **peer examples** are not available yet.\n\n- I can help you think it through.", evidence: { status: "unavailable" }, piiFlag: false, language: "en", syntheticDemo: true },
  };
  window.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), location.href);
    if (url.pathname === "/config.json") return new Response(JSON.stringify({ apiBaseUrl: "http://mock.local", clientId: "x", authority: "x", issuer: "x", cognitoDomain: "x", redirectUri: "x", logoutUri: "x", region: "x" }));
    const hit = routes[`${init?.method ?? "GET"} ${url.pathname}`];
    await new Promise((r) => setTimeout(r, 400));
    return hit ? new Response(JSON.stringify(hit)) : new Response(JSON.stringify({ error: { code: "not_found", message: "Mock has no such route.", retryable: false } }), { status: 404 });
  }) as typeof fetch;
}
