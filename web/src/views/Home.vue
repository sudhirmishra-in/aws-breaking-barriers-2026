<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";
import { ClipboardCheck, MessageCircle } from "lucide-vue-next";
import PeerCases from "../components/PeerCases.vue";
import ProducerInfo from "../components/ProducerInfo.vue";
import { api } from "../lib/api";
import { CORRECTION_STATUS, INFO_LABEL, show } from "../lib/labels";
import { state } from "../session";
import { t } from "../lib/i18n";
import type { ConversationSummary, CorrectionDto, Overview } from "../types";
const s = computed(() => t(state.ui));
const route = useRoute(); const router = useRouter();
const denied = computed(() => route.query.denied);
const ov = ref<Overview | null>(null); const err = ref("");
const recent = ref<ConversationSummary[]>([]);
const corrections = ref<CorrectionDto[]>([]); const corrErr = ref("");
const isProducer = computed(() => state.me?.roles.includes("producer"));
const isReviewer = computed(() => state.me?.roles.includes("reviewer"));
const GROUPS = [["today", "Today"], ["previous_7_days", "Previous 7 days"], ["older", "Older"]] as const;
const grouped = computed(() => GROUPS.map(([k, label]) => ({ k, label, list: recent.value.filter((c) => (c.group ?? "older") === k) })).filter((g) => g.list.length));
async function loadCorrections() { try { corrections.value = (await api.reviewCorrections("all")).items.filter((c) => c.status === "pending" || c.status === "accepted_awaiting_source_update"); corrErr.value = ""; } catch (e) { corrErr.value = (e as Error).message; } }
async function decide(c: CorrectionDto, d: "accept" | "reject" | "mark_applied") { try { await api.decideCorrection(c.correctionId, d); await loadCorrections(); } catch (e) { corrErr.value = (e as Error).message; } }
onMounted(async () => {
  try { ov.value = await api.overview(); } catch (e) { err.value = (e as Error).message; }
  if (isProducer.value && !state.me?.configurationError) { try { recent.value = (await api.list()).items.slice(0, 8); } catch { /* shown empty */ } }
  if (isReviewer.value) await loadCorrections();
});
const askAbout = (caseId: string) => router.push({ path: "/chat", query: { new: "1", case: caseId } });
const fmt = (iso: string) => new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
</script>
<template>
  <section class="hero hero-compact fade-up">
    <div>
      <h1>Welcome<template v-if="state.me?.profile">, {{ state.me.profile.displayName }}</template></h1>
      <span class="bar" aria-hidden="true" />
      <p v-if="isProducer">Ask a question, look something up, or tell us about a challenge. The AI Agent can help with all three.</p>
      <RouterLink v-if="isProducer && !state.me?.configurationError" to="/chat?new=1" class="btn primary"><MessageCircle :size="16" aria-hidden="true" /> Ask the AI Agent</RouterLink>
    </div>
  </section>
  <p v-if="err" class="banner error" role="alert">{{ err }}</p>
  <p v-if="denied" class="banner error" role="alert">{{ denied === "reviewer" ? s.deniedRole : s.deniedProducer }}</p>

  <template v-if="isProducer">
    <ProducerInfo />
    <section class="grp" aria-label="Recent conversations">
      <h2 class="page-title" style="font-size:1.05rem">Recent conversations</h2>
      <p v-if="!recent.length" class="hint">No conversations yet.</p>
      <div v-for="g in grouped" :key="g.k"><h3>{{ g.label }}</h3>
        <ul class="list"><li v-for="c in g.list" :key="c.conversationId"><RouterLink class="item" :to="`/chat/${c.conversationId}`">
          <span>{{ c.title || "Untitled conversation" }} <span class="hint">· {{ fmt(c.createdAt) }}</span></span>
          <span class="pill" :class="c.status === 'in_progress' ? 'warn' : 'ok'">{{ c.status === "in_progress" ? "In progress" : c.stopped ? "Stopped" : "Completed" }}</span></RouterLink></li></ul></div>
    </section>
    <PeerCases scope="organization" title="Conversations from my peers" @ask="askAbout" />
  </template>

  <template v-if="isReviewer && ov?.reviewer">
    <h2 class="page-title" style="font-size:1.1rem">{{ s.reviewerHome }}</h2>
    <div class="tiles">
      <div class="tile"><b>{{ ov.reviewer.pending }}</b><span>{{ s.statPending }}</span></div>
      <div class="tile"><b>{{ ov.reviewer.approved }}</b><span>{{ s.statApproved }}</span></div>
      <div class="tile"><b>{{ ov.reviewer.corrected }}</b><span>{{ s.statCorrected }}</span></div>
      <div class="tile"><b>{{ ov.reviewer.piiFlagged }}</b><span>{{ s.statPii }}</span></div>
    </div>
    <RouterLink to="/review" class="btn primary"><ClipboardCheck :size="16" aria-hidden="true" />{{ s.openQueue }}</RouterLink>
    <section class="card" aria-label="Producer information correction requests" style="margin-top:1rem">
      <h2 class="page-title" style="font-size:1.05rem">Producer information corrections</h2>
      <p v-if="corrErr" class="banner error" role="alert">{{ corrErr }}</p>
      <p v-else-if="!corrections.length" class="hint">No open correction requests.</p>
      <ul v-else class="list"><li v-for="c in corrections" :key="c.correctionId" class="pinfo-corr">
        <span><b>{{ c.requesterProducerId }}</b> · {{ c.organizationId }} <span class="pill warn">{{ CORRECTION_STATUS[c.status] }}</span></span>
        <span v-for="ch in c.changes" :key="ch.field">{{ INFO_LABEL[ch.field] }}: {{ show(ch.original) }} → {{ ch.proposed }}</span>
        <span v-if="c.explanation" class="hint">{{ c.explanation }}</span>
        <span class="row"><template v-if="c.status === 'pending'"><button class="btn sm primary" @click="decide(c, 'accept')">Accept</button><button class="btn sm" @click="decide(c, 'reject')">Reject</button></template>
          <button v-else class="btn sm" @click="decide(c, 'mark_applied')">Mark applied to source</button></span>
      </li></ul>
    </section>
  </template>
</template>
