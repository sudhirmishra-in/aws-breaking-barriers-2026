<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { AlertTriangle, Bot, Check, CheckCircle2, Copy, EyeOff, Heart, MessageCircle, Plus, RotateCw, SendHorizontal, ShieldCheck, Sprout } from "lucide-vue-next";
import { api, newRequestId } from "../lib/api";
import { renderMarkdown } from "../lib/markdown";
import { markExpired, state } from "../session";
import { t } from "../lib/i18n";
import { ApiFailure, type ConversationDto, type Lang, type Message } from "../types";

const s = computed(() => t(state.ui));
const conv = ref<ConversationDto | null>(null);
const messages = ref<Message[]>([]);
const busy = ref(false);
const loading = ref(true);
const error = ref<{ text: string; retry?: () => Promise<void> } | null>(null);
const draft = ref("");
const startLang = ref<Lang>(state.ui);
const correcting = ref(false);
const corr = ref({ text: "", location: "", entity: "" });
const confirmEnd = ref(false);
const copiedSeq = ref<number | null>(null);
const log = ref<HTMLElement | null>(null);
const box = ref<HTMLTextAreaElement | null>(null);

const closed = computed(() => conv.value?.workflow === "closed");
const lang = computed(() => conv.value?.language ?? state.ui);
const stepNow = computed(() => ({ intake: 0, playback_pending: 1, guidance_pending: 2, consent_pending: 2, closed: 3 })[conv.value?.workflow ?? "intake"]);
const showChips = computed(() => conv.value?.workflow === "intake" && !busy.value && !draft.value && messages.value.filter((m) => m.role === "user").length === 0);

function scrollDown() { nextTick(() => log.value?.scrollTo({ top: log.value.scrollHeight })); }
function apply(v: { conversation: ConversationDto | null; messages?: Message[] }) { conv.value = v.conversation; messages.value = v.messages ?? []; scrollDown(); }
watch(busy, scrollDown);

/** Runs an API action; a retry re-sends the SAME requestId so the server de-duplicates it. */
async function run(action: (requestId: string) => Promise<{ conversation: ConversationDto; messages: Message[] }>, requestId = newRequestId()) {
  busy.value = true; error.value = null;
  try { apply(await action(requestId)); return true; }
  catch (e) {
    const f = e as ApiFailure;
    if (f.status === 401) { markExpired(); error.value = { text: s.value.expired }; }
    else error.value = { text: f.message, retry: f.retryable ? async () => { await run(action, requestId); } : undefined };
    scrollDown(); return false;
  } finally { busy.value = false; }
}
onMounted(async () => {
  try { apply(await api.current()); } // restores an active conversation after refresh
  catch (e) { if ((e as ApiFailure).status === 401) markExpired(); else error.value = { text: (e as ApiFailure).message }; }
  finally { loading.value = false; }
});
const start = () => run(async () => api.create(startLang.value));
async function send() {
  const text = draft.value.trim(); if (!text || !conv.value || busy.value) return;
  const id = conv.value.conversationId;
  // Show the producer's message immediately (optimistic); the server response replaces the list.
  messages.value = [...messages.value, { seq: -1, role: "user", text, at: "" }]; scrollDown();
  const before = draft.value; draft.value = "";
  if (!(await run((rid) => api.message(id, rid, text)))) { messages.value = messages.value.filter((m) => m.seq !== -1); draft.value = before; }
}
function pick(text: string) { draft.value = text; nextTick(() => box.value?.focus()); }
const confirm = () => run((rid) => api.playback(conv.value!.conversationId, rid, { decision: "confirm" }));
async function sendCorrection() {
  const body: Parameters<typeof api.playback>[2] = { decision: "correct" };
  if (corr.value.text.trim()) body.correction = corr.value.text.trim();
  const field = corr.value.entity ? ({ field: "entityType", value: corr.value.entity } as const) : corr.value.location.trim() ? ({ field: "location", value: corr.value.location.trim() } as const) : undefined;
  if (field) body.profileCorrection = field;
  if (!body.correction && !body.profileCorrection) return;
  if (await run((rid) => api.playback(conv.value!.conversationId, rid, body))) { correcting.value = false; corr.value = { text: "", location: "", entity: "" }; }
}
const decide = (store: boolean) => run((rid) => api.consent(conv.value!.conversationId, rid, store));
async function endNow() { confirmEnd.value = false; await run((rid) => api.end(conv.value!.conversationId, rid)); }
async function copy(m: Message) { try { await navigator.clipboard.writeText(m.text); copiedSeq.value = m.seq; setTimeout(() => (copiedSeq.value = null), 1800); } catch { /* clipboard unavailable */ } }
function reset() { conv.value = null; messages.value = []; error.value = null; }
</script>

<template>
  <section v-if="loading" role="status" class="hero"><span class="pill">…</span></section>

  <!-- Landing -->
  <section v-else-if="!conv" class="fade-up">
    <div class="hero">
      <div>
        <h1>{{ s.welcome }}</h1>
        <span class="bar" aria-hidden="true" />
        <p>{{ s.about }}</p>
        <div class="seg" role="group" :aria-label="s.language">
          <button :aria-pressed="startLang === 'en'" @click="startLang = 'en'">English</button>
          <button :aria-pressed="startLang === 'es'" @click="startLang = 'es'">Español</button>
        </div>
        <div><button class="btn primary" :disabled="busy" @click="start"><MessageCircle :size="16" aria-hidden="true" />{{ busy ? s.sending : s.start }}</button></div>
        <div v-if="error" class="banner error" role="alert">{{ error.text }} <button v-if="error.retry" class="btn sm" @click="error.retry()">{{ s.retry }}</button></div>
      </div>
      <div class="hero-art" aria-hidden="true"><div class="disc"><Sprout :size="110" :stroke-width="1.25" /></div></div>
    </div>
    <div class="grid3">
      <div class="card feat"><span class="ic brand-gradient"><MessageCircle :size="16" aria-hidden="true" /></span><div><h3>{{ s.feat1 }}</h3><p>{{ s.feat1d }}</p></div></div>
      <div class="card feat"><span class="ic brand-gradient"><CheckCircle2 :size="16" aria-hidden="true" /></span><div><h3>{{ s.feat2 }}</h3><p>{{ s.feat2d }}</p></div></div>
      <div class="card feat"><span class="ic brand-gradient"><EyeOff :size="16" aria-hidden="true" /></span><div><h3>{{ s.feat3 }}</h3><p>{{ s.feat3d }}</p></div></div>
    </div>
    <details class="card"><summary><ShieldCheck :size="14" aria-hidden="true" style="vertical-align:-2px" /> {{ s.privacyTitle }}</summary><p>{{ s.privacy }}</p></details>
  </section>

  <!-- Finished -->
  <section v-else-if="closed" class="card done pop" role="status" style="margin-top:2rem">
    <span class="big"><Heart v-if="conv.consent === 'granted'" :size="26" aria-hidden="true" /><Check v-else :size="26" aria-hidden="true" /></span>
    <h1 style="margin:0">{{ s.doneTitle }}</h1>
    <p style="max-width:32rem">{{ conv.consent === "granted" ? s.doneStored : s.doneDeclined }}</p>
    <button class="btn primary" @click="reset"><Plus :size="16" aria-hidden="true" />{{ s.newConv }}</button>
  </section>

  <!-- Conversation -->
  <section v-else class="shell fade-up">
    <div class="shell-hd">
      <h1>{{ s.title }}</h1><span class="pill ok">● {{ s.live }}</span><span class="grow" />
      <button v-if="!confirmEnd" class="btn sm" :disabled="busy" @click="confirmEnd = true"><Plus :size="12" aria-hidden="true" />{{ s.end }}</button>
      <span v-else role="alertdialog" aria-label="confirm end" class="row" style="align-items:center;font-size:.8rem">{{ s.endConfirm }}
        <button class="btn sm" @click="endNow">{{ s.end }}</button><button class="btn sm" @click="confirmEnd = false">{{ s.cancel }}</button></span>
    </div>
    <ol class="steps" aria-label="Progress" style="margin:0;list-style:none">
      <li v-for="(label, i) in s.steps" :key="label" class="step" :class="{ done: i < stepNow, now: i === stepNow }" :aria-current="i === stepNow ? 'step' : undefined">
        <span class="n"><Check v-if="i < stepNow" :size="12" aria-hidden="true" /><template v-else>{{ i + 1 }}</template></span>{{ label }}
      </li>
    </ol>

    <div ref="log" class="log" role="log" aria-live="polite" aria-label="Conversation">
      <p v-if="conv.piiFlag" class="banner info" role="note">{{ s.piiNote }}</p>
      <template v-for="m in messages" :key="m.seq">
        <div v-if="m.role === 'user'" class="bubble-u fade-up">{{ m.text }}</div>
        <div v-else class="row-a fade-up">
          <span class="av brand-gradient"><Bot :size="16" aria-hidden="true" /><span class="sr">{{ s.assistant }}</span></span>
          <div style="min-width:0;flex:1">
            <div class="md" v-html="renderMarkdown(m.text)" />
            <button class="btn sm copy" style="border:0;background:none" :aria-label="s.copy" @click="copy(m)"><Check v-if="copiedSeq === m.seq" :size="12" aria-hidden="true" /><Copy v-else :size="12" aria-hidden="true" />{{ copiedSeq === m.seq ? s.copied : s.copy }}</button>
          </div>
        </div>
      </template>
      <div v-if="busy" class="row-a fade-up" role="status" aria-live="polite">
        <span class="av brand-gradient"><span style="display:flex;gap:2px" aria-hidden="true"><i v-for="d in 3" :key="d" class="dot" :style="{ animationDelay: `${(d - 1) * 0.15}s` }" /></span></span>
        <span style="font-size:.875rem;color:var(--muted);align-self:center">{{ s.sending }}</span>
      </div>
      <div v-if="error" class="row-a fade-up" role="alert">
        <span class="av" style="background:color-mix(in srgb,var(--err) 18%,transparent);color:var(--err)"><AlertTriangle :size="16" aria-hidden="true" /></span>
        <div class="err-bubble"><b>{{ s.failed }}</b><div style="color:var(--muted);margin:.25rem 0">{{ error.text }}</div>
          <button v-if="error.retry" class="btn sm" @click="error.retry()"><RotateCw :size="12" aria-hidden="true" />{{ s.retry }}</button></div>
      </div>

      <div v-if="conv.workflow === 'playback_pending'" class="decision pop" role="group" :aria-label="s.playbackTitle">
        <h2>{{ s.playbackTitle }}</h2>
        <p style="margin:0;font-size:.8rem;color:var(--muted)">{{ s.youSaid }}</p>
        <blockquote class="quote">{{ conv.playbackSummary }}</blockquote>
        <div v-if="!correcting" class="row">
          <button class="btn primary" :disabled="busy" @click="confirm"><Check :size="16" aria-hidden="true" />{{ s.yes }}</button>
          <button class="btn" :disabled="busy" @click="correcting = true">{{ s.no }}</button>
        </div>
        <form v-else style="display:grid;gap:.6rem" @submit.prevent="sendCorrection">
          <label class="fld">{{ s.correctionLabel }}<textarea v-model="corr.text" rows="3" maxlength="2000" /></label>
          <label class="fld">{{ s.locationLabel }}<input v-model="corr.location" maxlength="120" /></label>
          <label class="fld">{{ s.entityLabel }}<select v-model="corr.entity"><option value="">—</option><option v-for="(label, k) in s.entity" :key="k" :value="k">{{ label }}</option></select></label>
          <div class="row"><button class="btn primary" type="submit" :disabled="busy">{{ s.submitCorrection }}</button><button class="btn" type="button" @click="correcting = false">{{ s.cancel }}</button></div>
        </form>
      </div>

      <div v-if="conv.workflow === 'guidance_pending'" class="decision pop"><button class="btn primary" :disabled="busy" @click="confirm">{{ s.continue }}</button></div>

      <div v-if="conv.workflow === 'consent_pending'" class="decision pop" role="group" :aria-label="s.consentTitle">
        <p class="banner info" style="margin:0">{{ s.noEvidence }}</p>
        <h2>{{ s.consentTitle }}</h2>
        <p style="margin:0;font-size:.875rem;color:var(--muted)">{{ s.consentText }}</p>
        <blockquote class="quote">{{ lang === "es" ? conv.summaryEs : conv.summaryEn }}</blockquote>
        <div class="row">
          <button class="btn primary" :disabled="busy" @click="decide(true)"><ShieldCheck :size="16" aria-hidden="true" />{{ s.storeYes }}</button>
          <button class="btn" :disabled="busy" @click="decide(false)">{{ s.storeNo }}</button>
        </div>
      </div>
    </div>

    <div v-if="conv.workflow === 'intake'" class="dock">
      <div v-if="showChips" class="fade-up"><p style="margin:0 0 .4rem;font-size:.8rem;color:var(--muted)">{{ s.chipsTitle }}</p>
        <div class="chips"><button v-for="c in s.chips" :key="c" class="chip" type="button" @click="pick(c)">{{ c }}</button></div></div>
      <form class="composer" @submit.prevent="send">
        <label for="msg" class="sr">{{ s.messageLabel }}</label>
        <textarea id="msg" ref="box" v-model="draft" rows="1" maxlength="2000" :placeholder="s.placeholder" :disabled="busy" @keydown.enter.exact.prevent="send" />
        <button class="send" type="submit" :disabled="busy || !draft.trim()" :aria-label="s.send"><SendHorizontal :size="18" aria-hidden="true" /></button>
      </form>
    </div>
  </section>
</template>
