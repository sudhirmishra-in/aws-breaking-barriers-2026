import { createRouter, createWebHistory } from "vue-router";
import Callback from "./views/Callback.vue";
import Login from "./views/Login.vue";
import Home from "./views/Home.vue";
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
    // Role-based root: producers land on Home, reviewers on the review queue.
    { path: "/", redirect: () => (state.me?.roles.includes("reviewer") && !state.me.roles.includes("producer") ? "/review" : "/home") },
    { path: "/home", component: Home }, // producers: welcome + producer information; reviewers: correction requests
    { path: "/chat", component: Chat, meta: { role: "producer" } },
    { path: "/chat/:conversationId", component: Chat, meta: { role: "producer" } },
    { path: "/share", redirect: "/chat" },
    { path: "/ask", redirect: "/chat" }, // one entry point: questions, search and issue reporting all start in Chat
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
  if (to.path === "/login") return state.me?.roles.includes("reviewer") && !state.me.roles.includes("producer") ? "/review" : "/home";
  try { if (!state.me) await loadMe(); }
  catch (e) { return { path: "/login", query: { error: (e as ApiFailure).status === 401 ? "expired" : "api" } }; }
  const need = to.meta.role as "producer" | "reviewer" | undefined;
  if (to.path === "/" && !state.me) return true;
  if (need && !state.me!.roles.includes(need)) return state.me!.roles.includes("reviewer") ? { path: "/review", query: { denied: need } } : { path: "/home", query: { denied: need } };
  return true;
});
