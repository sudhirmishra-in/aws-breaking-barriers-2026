<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink, useRoute } from "vue-router";
import { ArrowRight, ClipboardCheck, HelpCircle, MessageCircle, ShieldCheck } from "lucide-vue-next";
import { api } from "../lib/api";
import { state } from "../session";
import { t } from "../lib/i18n";
import type { Overview } from "../types";
const s = computed(() => t(state.ui));
const route = useRoute();
const denied = computed(() => route.query.denied);
const ov = ref<Overview | null>(null); const err = ref("");
const isProducer = computed(() => state.me?.roles.includes("producer"));
const isReviewer = computed(() => state.me?.roles.includes("reviewer"));
const entityLabel = computed(() => (state.me?.profile ? (s.value.entity as Record<string, string>)[state.me.profile.entityType] ?? state.me.profile.entityType : ""));
onMounted(async () => { try { ov.value = await api.overview(); } catch (e) { err.value = (e as Error).message; } });
</script>
<template>
  <section class="hero hero-compact fade-up">
    <div>
      <span class="pill">{{ s.rolesLabel }}: {{ [isProducer ? s.roleProducer : "", isReviewer ? s.roleReviewer : ""].filter(Boolean).join(" · ") }}</span>
      <h1>{{ s.hello }}<template v-if="state.me?.profile">, {{ state.me.profile.displayName }}</template></h1>
      <span class="bar" aria-hidden="true" />
      <p v-if="isProducer">{{ s.about }}</p>
    </div>
  </section>
  <p v-if="err" class="banner error" role="alert">{{ err }}</p>
  <p v-if="denied" class="banner error" role="alert">{{ denied === "reviewer" ? s.deniedRole : s.deniedProducer }}</p>

  <template v-if="isProducer">
    <div class="grid3">
      <RouterLink to="/chat" class="card action"><span class="ic brand-gradient"><MessageCircle :size="18" aria-hidden="true" /></span><div><h3>{{ s.shareCard }} <ArrowRight :size="14" aria-hidden="true" /></h3><p>{{ s.shareCardD }}</p></div></RouterLink>
      <RouterLink to="/ask" class="card action"><span class="ic brand-gradient"><HelpCircle :size="18" aria-hidden="true" /></span><div><h3>{{ s.askCard }} <ArrowRight :size="14" aria-hidden="true" /></h3><p>{{ s.askCardD }}</p></div></RouterLink>
      <div class="card"><h3>{{ ov?.producer?.activeConversation ? s.resume : s.noActive }}</h3>
        <p v-if="ov?.producer?.activeConversation">{{ s.resumeD }} <RouterLink to="/chat">{{ s.continue }} →</RouterLink></p></div>
    </div>
    <div class="grid3">
      <div v-if="state.me?.profile" class="card"><h3>{{ s.yourProfile }}</h3>
        <dl class="kv"><dt>{{ s.location }}</dt><dd>{{ state.me.profile.location }}</dd><dt>{{ s.crop }}</dt><dd>{{ state.me.profile.crop }}</dd><dt>{{ s.entityType }}</dt><dd>{{ entityLabel }}</dd></dl></div>
      <div class="card"><h3><ShieldCheck :size="14" aria-hidden="true" style="vertical-align:-2px" /> {{ s.whatPrivate }}</h3><p>{{ s.privateText }}</p></div>
    </div>
  </template>

  <template v-if="isReviewer && ov?.reviewer">
    <h2 class="page-title" style="font-size:1.1rem">{{ s.reviewerHome }}</h2>
    <div class="tiles">
      <div class="tile"><b>{{ ov.reviewer.pending }}</b><span>{{ s.statPending }}</span></div>
      <div class="tile"><b>{{ ov.reviewer.approved }}</b><span>{{ s.statApproved }}</span></div>
      <div class="tile"><b>{{ ov.reviewer.corrected }}</b><span>{{ s.statCorrected }}</span></div>
      <div class="tile"><b>{{ ov.reviewer.piiFlagged }}</b><span>{{ s.statPii }}</span></div>
    </div>
    <ul class="list">
      <li v-for="i in ov.reviewer.recent" :key="i.outcomeId"><RouterLink class="item" :to="`/review/${i.outcomeId}`"><span>{{ i.createdAt.slice(0, 10) }} · {{ i.producerId }}</span><span class="pill" :class="i.reviewStatus === 'pending' ? 'warn' : 'ok'">{{ s[i.reviewStatus] }}</span></RouterLink></li>
    </ul>
    <RouterLink to="/review" class="btn primary"><ClipboardCheck :size="16" aria-hidden="true" />{{ s.openQueue }}</RouterLink>
  </template>
</template>
