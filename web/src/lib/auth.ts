import { InMemoryWebStorage, UserManager, WebStorageStateStore, type User } from "oidc-client-ts";
import { loadConfig } from "./config";

/**
 * Authorization code + PKCE with a public client. Tokens live in memory only (never localStorage):
 * a page refresh drops them and the app silently re-runs the redirect; the Cognito session cookie
 * makes that seamless. Trade-off: no long-lived token in script-readable storage, one extra redirect on refresh.
 */
let mgr: UserManager | undefined;
let user: User | null = null;

async function manager(): Promise<UserManager> {
  if (mgr) return mgr;
  const c = await loadConfig();
  mgr = new UserManager({
    authority: c.authority, client_id: c.clientId, redirect_uri: c.redirectUri, response_type: "code", scope: "openid email",
    userStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
    stateStore: new WebStorageStateStore({ store: window.sessionStorage }), // short-lived PKCE state only
    automaticSilentRenew: false,
  });
  return mgr;
}

export async function signIn(returnTo = "/") {
  const m = await manager();
  await m.signinRedirect({ state: { returnTo } });
}
export async function completeSignIn(): Promise<string> {
  const m = await manager();
  user = await m.signinCallback() ?? null;
  return ((user?.state as { returnTo?: string } | undefined)?.returnTo) ?? "/";
}
export function accessToken(): string | null {
  return user && !user.expired ? user.access_token : null;
}
export const isSignedIn = () => !!accessToken();
export async function signOut() {
  const c = await loadConfig();
  user = null;
  const m = await manager();
  await m.removeUser();
  window.location.assign(`${c.cognitoDomain}/logout?client_id=${encodeURIComponent(c.clientId)}&logout_uri=${encodeURIComponent(c.logoutUri)}`);
}
export function _setUserForTests(u: User | null) { user = u; }
