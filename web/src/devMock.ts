// DEV-ONLY LOCAL MOCK (loaded only by `vite dev` with ?mock=producer|reviewer). Never part of the production bundle's behaviour.
import { _setUserForTests } from "./lib/auth";

export function installDevMock(role: "producer" | "reviewer") {
  _setUserForTests({ access_token: "mock", expired: false, state: { returnTo: "/" } } as never);
  const profile = { displayName: "Synthetic Producer One", entityType: "cooperative", location: "Synthetic Highlands (fictional region)", crop: "coffee", preferredLanguage: "en" };
  const item = (id: string, st: string, pii = false) => ({ outcomeId: id, source: "agent conversation", producerId: "SYN-P-001", language: "es", summaryEn: "Late rains reduced yield.", summaryOriginal: "Las lluvias tardías redujeron la producción.", piiFlag: pii, piiTypes: pii ? ["PHONE"] : [], reviewStatus: st, createdAt: "2026-11-03T14:00:00Z" });
  const iso = (daysAgo: number) => new Date(Date.now() - daysAgo * 86_400_000).toISOString();
  const sample = {
    conversation: { conversationId: "c-1", language: "es", workflow: "playback_pending", confirmation: "pending", consent: "unanswered", status: "active", title: "Lluvias irregulares y menor cosecha",
      playbackSummary: "Lluvias irregulares desde finales de 2023; cosecha cerca de 25 % menor; tanques de agua de lluvia desde 2021 ya no alcanzan.", createdAt: iso(0), updatedAt: iso(0), expiresAt: iso(-7) },
    messages: [
      { seq: 1, role: "assistant", text: "Hola, gracias por escribirnos. ¿Qué ha sido lo más difícil para su organización últimamente?", at: iso(0), stage: "intake" },
      { seq: 2, role: "user", text: "La lluvia ha estado muy irregular desde hace dos temporadas y la última cosecha bajó bastante.", at: iso(0), stage: "intake" },
      { seq: 3, role: "assistant", text: "Lamento escuchar eso. ¿Desde cuándo lo notan, qué tanto bajó la cosecha y qué han intentado hasta ahora?", at: iso(0), stage: "intake" },
      { seq: 4, role: "user", text: "Desde finales de 2023. Perdimos más o menos una cuarta parte. Tenemos tanques desde 2021, pero ya no alcanzan.", at: iso(0), stage: "intake" },
      { seq: 5, role: "assistant", text: "Gracias. Esto es lo que entendí. ¿Es correcto?", at: iso(0), stage: "playback" },
    ],
    retention: { activeDays: 7, savedDays: 30, text: "" }, syntheticDemo: true,
  };
  const history = { items: [
    { conversationId: "c-1", title: "Lluvias irregulares y menor cosecha", language: "es", createdAt: iso(0), updatedAt: iso(0), status: "in_progress", summary: "Lluvias irregulares desde finales de 2023; cosecha cerca de 25 % menor." },
    { conversationId: "c-2", title: "Planning next year's Premium projects", language: "en", createdAt: iso(5), updatedAt: iso(5), status: "saved", summary: "The cooperative wants to choose next year's Premium projects and is weighing water storage against a drying patio." },
    { conversationId: "c-3", title: "Precios más bajos después de la cosecha", language: "es", createdAt: iso(50), updatedAt: iso(50), status: "saved", summary: null },
  ] };
  const routes: Record<string, unknown> = {
    "GET /conversations": history,
    "GET /conversations/c-1": sample,
    "POST /conversations": { ...sample, conversation: { ...sample.conversation, conversationId: "c-9", workflow: "intake", title: null }, messages: [sample.messages[0]] },
    "POST /conversations/c-1/messages": { ...sample, conversation: { ...sample.conversation, workflow: "intake" }, messages: [...sample.messages,
      { seq: 6, role: "user", text: "Sí, y también subieron los costos.", at: iso(0), stage: "intake" },
      { seq: 7, role: "assistant", text: "Entiendo. ¿Qué tanto subieron los costos y desde cuándo?", at: iso(0), stage: "intake" }] },
    "DELETE /conversations/c-2": { deleted: true, conversationId: "c-2" },
    "GET /conversations/c-2": { ...sample, conversation: { ...sample.conversation, conversationId: "c-2", language: "en", workflow: "closed", status: "completed", consent: "granted", title: "Planning next year's Premium projects" },
      messages: [{ seq: 1, role: "assistant", text: "What has been difficult recently?", at: iso(5), stage: "intake" }, { seq: 2, role: "user", text: "We need to decide next year's Premium projects.", at: iso(5), stage: "intake" }] },
    "GET /me": role === "producer" ? { roles: ["producer"], profile, syntheticDemo: true } : { roles: ["reviewer"], syntheticDemo: true },
    "GET /overview": role === "producer" ? { producer: { activeConversation: null } } : { reviewer: { pending: 2, approved: 1, corrected: 1, piiFlagged: 1, recent: [item("rec-1", "pending", true), item("rec-2", "approved")] } },
    "GET /conversations/current": sample,
    "GET /reviews": { items: [item("rec-1", "pending", true), item("rec-2", "approved")] },
    "POST /transcribe": { text: "The rains came late this year and our harvest was smaller than usual.", language: "en" },
    "POST /ask": { answer: "I'm sorry, **peer examples** are not available yet.\n\n- I can help you think it through.", evidence: { status: "unavailable" }, piiFlag: false, language: "en", syntheticDemo: true },
  };
  window.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), location.href);
    if (url.pathname === "/config.json") return new Response(JSON.stringify({ apiBaseUrl: "http://mock.local", clientId: "x", authority: "x", issuer: "x", cognitoDomain: "x", redirectUri: "x", logoutUri: "x", region: "x" }));
    if (url.pathname.endsWith("/speech")) { await new Promise((r) => setTimeout(r, 400)); return new Response(JSON.stringify({ contentType: "audio/wav", audio: toneWav(), voice: "mock" })); }
    const hit = routes[`${init?.method ?? "GET"} ${url.pathname}`];
    await new Promise((r) => setTimeout(r, 400));
    return hit ? new Response(JSON.stringify(hit)) : new Response(JSON.stringify({ error: { code: "not_found", message: "Mock has no such route.", retryable: false } }), { status: 404 });
  }) as typeof fetch;
}

/** Dev-only: a short 440 Hz tone as base64 WAV, standing in for synthesized speech. */
function toneWav(seconds = 0.6, rate = 16000): string {
  const n = Math.floor(seconds * rate), buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf);
  const w = (o: number, t: string) => [...t].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  w(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); w(8, "WAVE"); w(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, "data"); v.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) v.setInt16(44 + i * 2, Math.sin((2 * Math.PI * 440 * i) / rate) * 6000, true);
  let bin = ""; new Uint8Array(buf).forEach((b) => (bin += String.fromCharCode(b))); return btoa(bin);
}
