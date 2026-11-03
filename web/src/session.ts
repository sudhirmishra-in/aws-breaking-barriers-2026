import { reactive } from "vue";
import { api } from "./lib/api";
import { completeSignIn, isSignedIn, signIn, signOut } from "./lib/auth";
import type { Lang, Me } from "./types";

const saved = (() => { try { return localStorage.getItem("ui-lang") as Lang | null; } catch { return null; } })();
export const state = reactive<{ me: Me | null; ui: Lang; expired: boolean; authError: boolean }>({ me: null, ui: saved ?? "en", expired: false, authError: false });
export function setUi(l: Lang) { state.ui = l; try { localStorage.setItem("ui-lang", l); } catch { /* per-viewer convenience only */ } document.documentElement.lang = l; }
export async function ensureSignedIn(returnTo: string): Promise<boolean> {
  if (isSignedIn()) return true;
  try { await signIn(returnTo); } catch { state.authError = true; }
  return false;
}
export async function loadMe() { state.me = await api.me(); return state.me; }
export function markExpired() { state.expired = true; }
export { completeSignIn, signIn, signOut };
