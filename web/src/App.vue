<script setup lang="ts">
import { computed } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";
import { Sprout, Sun, Moon, LogOut, UserRound, X, Globe, MessageCircle } from "lucide-vue-next";
import ProducerInfo from "./components/ProducerInfo.vue";
import { setUi, signOut, state } from "./session";
import { LANGS, type Lang } from "./types";
import { dark, toggleTheme } from "./lib/theme";
import { SANDBOX_BANNER } from "./lib/labels";
import { t } from "./lib/i18n";
const s = computed(() => t(state.ui));
const router = useRouter();
const route = useRoute();
const isProducer = computed(() => !!state.me?.roles.includes("producer"));
const isReviewer = computed(() => !!state.me?.roles.includes("reviewer"));
function goLogin() { state.expired = false; state.authError = false; router.push({ path: "/login", query: { next: window.location.pathname } }); }
</script>
<template>
  <a class="skip" href="#main">Skip to content</a>
  <!-- Embedded in another Fairtrade application: the parent provides the product header, navigation and account controls (no duplicate header here). -->
  <header v-if="!state.embedded" class="hdr">
    <div class="hdr-in">
      <RouterLink :to="state.me ? '/' : '/login'" class="logo" style="text-decoration:none;color:inherit">
        <span class="logo-mark brand-gradient"><Sprout :size="16" aria-hidden="true" /></span>{{ s.title }}
      </RouterLink>
      <nav v-if="state.me" class="nav" aria-label="Main">
        <RouterLink v-if="isProducer" to="/home">Home</RouterLink>
        <RouterLink v-if="isReviewer" to="/review">{{ s.navReview }}</RouterLink>
        <RouterLink v-if="isReviewer && !isProducer" to="/home">Corrections</RouterLink>
      </nav>
      <span class="grow" />
      <RouterLink v-if="isProducer" to="/chat?new=1" class="btn primary sm"><MessageCircle :size="14" aria-hidden="true" /> Ask AI</RouterLink>
      <label class="icon-btn" style="cursor:pointer">
        <Globe :size="16" aria-hidden="true" /><span class="sr">{{ s.language }}</span>
        <select class="sel" :value="state.ui" @change="setUi(($event.target as HTMLSelectElement).value as Lang)">
          <option v-for="l in LANGS" :key="l.code" :value="l.code">{{ l.name }}</option>
        </select>
      </label>
      <button class="icon-btn" :aria-label="dark ? 'Switch to light theme' : 'Switch to dark theme'" @click="toggleTheme"><Sun v-if="dark" :size="18" aria-hidden="true" /><Moon v-else :size="18" aria-hidden="true" /></button>
      <button v-if="isProducer" class="icon-btn" aria-label="Your producer information" title="Your producer information" aria-haspopup="dialog" @click="state.infoOpen = true"><UserRound :size="18" aria-hidden="true" /></button>
      <button v-if="state.me" class="btn sm" @click="signOut()"><LogOut :size="14" aria-hidden="true" /> Logout</button>
    </div>
  </header>
  <div v-else-if="state.me" class="emb-bar">
    <button v-if="isProducer" class="icon-btn" aria-label="Your producer information" aria-haspopup="dialog" @click="state.infoOpen = true"><UserRound :size="18" aria-hidden="true" /></button>
  </div>
  <div class="sandbox-banner" role="note">{{ SANDBOX_BANNER }}</div>
  <div v-if="state.expired" class="banner error" role="alert" style="max-width:72rem;margin:.5rem auto">
    {{ s.expired }} <button class="btn sm" @click="goLogin()">{{ s.signIn }}</button>
  </div>
  <div v-if="state.authError && route.path !== '/login'" class="banner error" role="alert" style="max-width:72rem;margin:.5rem auto">
    {{ s.signInPrompt }} <button class="btn sm" @click="goLogin()">{{ s.signIn }}</button>
  </div>
  <main id="main"><RouterView /></main>
  <div v-if="state.infoOpen" class="modal" role="dialog" aria-modal="true" aria-label="Your producer information" @keydown.esc="state.infoOpen = false">
    <div class="modal-in"><button class="icon-btn modal-x" aria-label="Close" @click="state.infoOpen = false"><X :size="18" aria-hidden="true" /></button><ProducerInfo open /></div>
  </div>
  <footer v-if="!state.embedded" class="foot">{{ s.protoNote }}</footer>
</template>
