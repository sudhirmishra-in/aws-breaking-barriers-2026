<script setup lang="ts">
import { computed } from "vue";
import { RouterLink, RouterView } from "vue-router";
import { Sprout, Sun, Moon, LogOut, Globe } from "lucide-vue-next";
import { useRoute, useRouter } from "vue-router";
import { setUi, signOut, state } from "./session";
import { dark, toggleTheme } from "./lib/theme";
import { t } from "./lib/i18n";
const s = computed(() => t(state.ui));
const router = useRouter();
const route = useRoute();
function goLogin() { state.expired = false; state.authError = false; router.push({ path: "/login", query: { next: window.location.pathname } }); }
</script>
<template>
  <a class="skip" href="#main">Skip to content</a>
  <header class="hdr">
    <div class="hdr-in">
      <RouterLink :to="state.me ? '/' : '/login'" class="logo" style="text-decoration:none;color:inherit">
        <span class="logo-mark brand-gradient"><Sprout :size="16" aria-hidden="true" /></span>{{ s.title }}
      </RouterLink>
      <nav v-if="state.me" class="nav" aria-label="Main">
        <RouterLink to="/">{{ s.navHome }}</RouterLink>
        <template v-if="state.me?.roles.includes('producer')">
          <RouterLink to="/chat" :class="{ 'router-link-exact-active': $route.path.startsWith('/chat') }">{{ s.navShare }}</RouterLink>
          <RouterLink to="/ask">{{ s.navAsk }}</RouterLink>
        </template>
        <RouterLink v-if="state.me?.roles.includes('reviewer')" to="/review">{{ s.navReview }}</RouterLink>
      </nav>
      <span class="grow" />
      <span class="pill warn" role="note">{{ s.demo }}</span>
      <label class="icon-btn" style="cursor:pointer">
        <Globe :size="16" aria-hidden="true" /><span class="sr">{{ s.language }}</span>
        <select class="sel" :value="state.ui" @change="setUi(($event.target as HTMLSelectElement).value as 'en' | 'es')">
          <option value="en">English</option><option value="es">Español</option>
        </select>
      </label>
      <button class="icon-btn" :aria-label="s.theme" :title="s.theme" @click="toggleTheme">
        <Sun v-if="dark" :size="18" aria-hidden="true" /><Moon v-else :size="18" aria-hidden="true" />
      </button>
      <button v-if="state.me" class="icon-btn" :aria-label="s.signOut" :title="s.signOut" @click="signOut()"><LogOut :size="18" aria-hidden="true" /></button>
    </div>
  </header>
  <div v-if="state.expired" class="banner error" role="alert" style="max-width:72rem;margin:.5rem auto">
    {{ s.expired }} <button class="btn sm" @click="goLogin()">{{ s.signIn }}</button>
  </div>
  <div v-if="state.authError && route.path !== '/login'" class="banner error" role="alert" style="max-width:72rem;margin:.5rem auto">
    {{ s.signInPrompt }} <button class="btn sm" @click="goLogin()">{{ s.signIn }}</button>
  </div>
  <main id="main"><RouterView /></main>
  <footer class="foot">{{ s.protoNote }}</footer>
</template>
