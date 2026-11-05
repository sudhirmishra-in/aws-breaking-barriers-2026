import { createRouter, createWebHistory } from "vue-router";
import Callback from "./views/Callback.vue";
import Login from "./views/Login.vue";
import Home from "./views/Home.vue";
import Ask from "./views/Ask.vue";
import Chat from "./views/Chat.vue";
import Review from "./views/Review.vue";
import { isSignedIn } from "./lib/auth";
import { ApiFailure } from "./types";
import { loadMe, state } from "./session";

// Route guards are UX only. Every API call is authorised server-side from the access token and its groups.
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/login", component: Login },
    { path: "/auth/callback", component: Callback },
    { path: "/", component: Home },
    { path: "/chat", component: Chat, meta: { role: "producer" } },
    { path: "/chat/:conversationId", component: Chat, meta: { role: "producer" } },
    { path: "/share", redirect: "/chat" },
    { path: "/ask", component: Ask, meta: { role: "producer" } },
    { path: "/review", component: Review, meta: { role: "reviewer" } },
    { path: "/review/:producerId", component: Review, meta: { role: "reviewer" } },
  ],
});
router.beforeEach(async (to) => {
  if (to.path === "/auth/callback") return true;
  if (!isSignedIn()) {
    state.me = null;
    // No automatic redirect to the identity provider: the user starts sign-in from the login screen.
    return to.path === "/login" ? true : { path: "/login", query: to.fullPath !== "/" ? { next: to.fullPath } : {} };
  }
  if (to.path === "/login") return "/";
  try { if (!state.me) await loadMe(); }
  catch (e) { return { path: "/login", query: { error: (e as ApiFailure).status === 401 ? "expired" : "api" } }; }
  const need = to.meta.role as "producer" | "reviewer" | undefined;
  if (need && !state.me!.roles.includes(need)) return { path: "/", query: { denied: need } };
  return true;
});
