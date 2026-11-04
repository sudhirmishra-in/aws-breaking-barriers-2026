<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute } from "vue-router";
import { LogIn, Sprout } from "lucide-vue-next";
import { startSignIn, state } from "../session";
import { t } from "../lib/i18n";

type Role = "producer" | "reviewer";
const s = computed(() => t(state.ui));
const route = useRoute();
const saved = (() => { try { const r = localStorage.getItem("login-role"); return r === "reviewer" ? "reviewer" : "producer"; } catch { return "producer"; } })();
const role = ref<Role>(saved as Role);
const busy = ref(false);
const failed = computed(() => state.authError || route.query.error === "api");
const expired = computed(() => route.query.error === "expired");

async function go() {
  busy.value = true;
  try { localStorage.setItem("login-role", role.value); } catch { /* per-viewer convenience only */ }
  // The chosen role only sets the landing page; access is decided by the account's groups on the server.
  const next = typeof route.query.next === "string" && route.query.next.startsWith("/") ? route.query.next : role.value === "reviewer" ? "/review" : "/";
  state.authError = false;
  if (!(await startSignIn(next))) busy.value = false;
}
</script>
<template>
  <section class="hero fade-up">
    <div>
      <h1>{{ s.title }}</h1>
      <span class="bar" aria-hidden="true" />
      <p>{{ s.about }}</p>
    </div>
    <form class="card login" aria-labelledby="login-h" @submit.prevent="go">
      <h2 id="login-h">{{ s.loginTitle }}</h2>
      <p>{{ s.loginIntro }}</p>
      <label class="fld">{{ s.roleLabel }}
        <select v-model="role" name="role">
          <option value="producer">{{ s.roleProducer }}</option>
          <option value="reviewer">{{ s.roleReviewer }}</option>
        </select>
      </label>
      <p class="hint">{{ s.roleNote }}</p>
      <p v-if="expired" class="banner error" role="alert">{{ s.expired }}</p>
      <p v-if="failed" class="banner error" role="alert">{{ s.loginError }}</p>
      <button class="btn primary" type="submit" :disabled="busy"><LogIn :size="16" aria-hidden="true" />{{ busy ? s.sending : s.signInBtn }}</button>
      <p class="hint" style="display:flex;gap:.4rem;align-items:center"><Sprout :size="14" aria-hidden="true" />{{ s.demo }}</p>
    </form>
  </section>
</template>
