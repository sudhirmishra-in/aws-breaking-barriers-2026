import { reactive } from "vue";
import { api } from "./lib/api";
import { completeSignIn, signIn, signOut } from "./lib/auth";
import type { Lang, Me } from "./types";

const saved = (() => { try { const v = localStorage.getItem("ui-lang"); return v === "en" || v === "es" || v === "fr" ? (v as Lang) : null; } catch { return null; } })();
export const state = reactive<{ me: Me | null; ui: Lang; expired: boolean; authError: boolean }>({ me: null, ui: saved ?? "en", expired: false, authError: false });
if (typeof document !== "undefined") document.documentElement.lang = state.ui; // screen readers use the saved UI language
export function setUi(l: Lang) { state.ui = l; try { localStorage.setItem("ui-lang", l); } catch { /* per-viewer convenience only */ } document.documentElement.lang = l; }
/** Starts the Cognito redirect. Only ever called from an explicit user action (the login screen's button). */
export async function startSignIn(returnTo: string): Promise<boolean> {
  try { await signIn(returnTo); return true; } catch { state.authError = true; return false; }
}
export async function loadMe() { state.me = await api.me(); return state.me; }
export function markExpired() { state.expired = true; }
export { completeSignIn, signIn, signOut };
