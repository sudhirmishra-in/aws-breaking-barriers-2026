import { createRouter, createWebHistory } from "vue-router";
import Callback from "./views/Callback.vue";
import Home from "./views/Home.vue";
import Ask from "./views/Ask.vue";
import Chat from "./views/Chat.vue";
import Reviews from "./views/Reviews.vue";
import ReviewDetail from "./views/ReviewDetail.vue";
import { ensureSignedIn, loadMe, state } from "./session";

// Route guards are UX only. Every API call is authorised server-side from the access token.
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/auth/callback", component: Callback },
    { path: "/", component: Home },
    { path: "/share", component: Chat, meta: { role: "producer" } },
    { path: "/ask", component: Ask, meta: { role: "producer" } },
    { path: "/review", component: Reviews, meta: { role: "reviewer" } },
    { path: "/review/:id", component: ReviewDetail, meta: { role: "reviewer" } },
  ],
});
router.beforeEach(async (to) => {
  if (to.path === "/auth/callback") return true;
  if (!(await ensureSignedIn(to.fullPath))) return false;
  if (!state.me) await loadMe();
  const need = to.meta.role as "producer" | "reviewer" | undefined;
  if (need && !state.me!.roles.includes(need)) return "/";
  return true;
});
