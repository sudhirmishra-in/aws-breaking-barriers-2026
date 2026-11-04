import { reactive } from "vue";
import { api } from "./lib/api";
import { completeSignIn, signIn, signOut } from "./lib/auth";
import type { Lang, Me } from "./types";

const saved = (() => { try { const v = localStorage.getItem("ui-lang"); return v === "en" || v === "es" || v === "fr" ? (v as Lang) : null; } catch { return null; } })();
/** Embedded in another Fairtrade application: the parent supplies the header, navigation and account controls. Set by ?embedded=1 (remembered for the tab). */
const embedded = (() => { try {
  if (typeof location !== "undefined" && new URLSearchParams(location.search).get("embedded") === "1") sessionStorage.setItem("embedded", "1");
  return typeof sessionStorage !== "undefined" && sessionStorage.getItem("embedded") === "1";
} catch { return false; } })();
export const state = reactive<{ me: Me | null; ui: Lang; expired: boolean; authError: boolean; embedded: boolean; infoOpen: boolean }>({ me: null, ui: saved ?? "en", expired: false, authError: false, embedded, infoOpen: false });
if (typeof document !== "undefined") document.documentElement.lang = state.ui; // screen readers use the saved UI language
export function setUi(l: Lang) { state.ui = l; try { localStorage.setItem("ui-lang", l); } catch { /* per-viewer convenience only */ } document.documentElement.lang = l; }
/** Starts the Cognito redirect. Only ever called from an explicit user action (the login screen's button). */
export async function startSignIn(returnTo: string): Promise<boolean> {
  try { await signIn(returnTo); return true; } catch { state.authError = true; return false; }
}
/** After login the UI language defaults to the producer's preferred language unless the viewer already chose one; the dropdown stays available. */
export async function loadMe() {
  state.me = await api.me();
  const pref = state.me.preferred_language ?? state.me.profile?.preferredLanguage;
  let chosen: string | null = null; try { chosen = localStorage.getItem("ui-lang"); } catch { /* none */ }
  if (!chosen && pref) { state.ui = pref; document.documentElement.lang = pref; }
  return state.me;
}
export function markExpired() { state.expired = true; }
export { completeSignIn, signIn, signOut };
