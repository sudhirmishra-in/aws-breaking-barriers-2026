<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { AlertTriangle, Bot, Check, CheckCircle2, Copy, EyeOff, Heart, Keyboard, Loader2, MessageCircle, Square, Volume2, Plus, RotateCw, SendHorizontal, ShieldCheck, X } from "lucide-vue-next";
import DictateButton from "../components/DictateButton.vue";
import HistoryPanel from "../components/HistoryPanel.vue";
import ProgressPanel from "../components/ProgressPanel.vue";
import { api, newRequestId } from "../lib/api";
import { renderMarkdown } from "../lib/markdown";
import { audioSupported, playMp3, stopAudio, unlockAudio } from "../lib/speech";
import { markExpired, state } from "../session";
import { t } from "../lib/i18n";
import { ApiFailure, LANGS, type ConversationDto, type ConversationView, type Lang, type Message, type Stage } from "../types";

const s = computed(() => t(state.ui));
const route = useRoute();
const router = useRouter();
const conv = ref<ConversationDto | null>(null);
const messages = ref<Message[]>([]);
const busy = ref(false);
const loading = ref(true);
const missing = ref(false);
const error = ref<{ text: string; retry?: () => Promise<void> } | null>(null);
const draft = ref("");
const startLang = ref<Lang>(state.ui);
const correcting = ref(false);
const corr = ref({ text: "", location: "", entity: "" });
const confirmEnd = ref(false);
const copiedSeq = ref<number | null>(null);
const log = ref<HTMLElement | null>(null);
// Text vs voice conversation: in voice mode each new agent reply is read aloud automatically.
const savedMode = (() => { try { return localStorage.getItem("conv-mode") === "voice" ? "voice" : "text"; } catch { return "text"; } })();
const mode = ref<"text" | "voice">(savedMode);
const speakingSeq = ref<number | null>(null);
const loadingSeq = ref<number | null>(null);
const audioErrSeq = ref<number | null>(null);
let lastSeenSeq = 0;
const box = ref<HTMLTextAreaElement | null>(null);

const STAGE_OF: Record<ConversationDto["workflow"], Stage> = { intake: "intake", playback_pending: "playback", guidance_pending: "response", consent_pending: "consent", closed: "consent" };
const closed = computed(() => conv.value?.workflow === "closed");
const lang = computed(() => conv.value?.language ?? state.ui);
const stage = computed<Stage>(() => STAGE_OF[conv.value?.workflow ?? "intake"]);
const outcome = computed(() => (!closed.value ? null : conv.value?.consent === "granted" ? "saved" : "declined") as "saved" | "declined" | null);
const reached = computed(() => [...new Set(messages.value.map((m) => m.stage).filter(Boolean))] as Stage[]);
const showChips = computed(() => conv.value?.workflow === "intake" && !busy.value && !draft.value && messages.value.filter((m) => m.role === "user").length === 0);
const heading = computed(() => (conv.value ? conv.value.title || s.value.untitled : s.value.newConversation));

function scrollDown() { nextTick(() => log.value?.scrollTo({ top: log.value.scrollHeight })); }
function apply(v: { conversation: ConversationDto | null; messages?: Message[] }) { conv.value = v.conversation; messages.value = v.messages ?? []; scrollDown(); }
const maxAgentSeq = () => Math.max(0, ...messages.value.filter((m) => m.role === "assistant").map((m) => m.seq));

function setMode(m: "text" | "voice") {
  mode.value = m;
  try { localStorage.setItem("conv-mode", m); } catch { /* per-viewer convenience only */ }
  if (m === "voice") unlockAudio(); else { stopAudio(); speakingSeq.value = null; }
}
async function listen(m: Message) {
  if (!conv.value) return;
  if (speakingSeq.value === m.seq) { stopAudio(); speakingSeq.value = null; return; }
  unlockAudio(); stopAudio();
  loadingSeq.value = m.seq; audioErrSeq.value = null; speakingSeq.value = null;
  try {
    const r = await api.speech(conv.value.conversationId, m.seq);
    loadingSeq.value = null; speakingSeq.value = m.seq;
    await playMp3(r.audio);
  } catch (e) {
    if ((e as ApiFailure).status === 401) markExpired();
    audioErrSeq.value = m.seq;
  } finally {
    if (loadingSeq.value === m.seq) loadingSeq.value = null;
    if (speakingSeq.value === m.seq) speakingSeq.value = null;
  }
}
/** After an action, read the newest agent reply aloud in voice mode (never replays history on load). */
function speakNewReply() {
  const newest = messages.value.filter((m) => m.role === "assistant" && m.seq > lastSeenSeq).at(-1);
  lastSeenSeq = maxAgentSeq();
  if (newest && mode.value === "voice") void listen(newest);
}
watch(busy, scrollDown);

// The open conversation lives in the URL (/chat/:conversationId) so a refresh returns to it (spec CONV-05).
async function load() {
  const id = route.params.conversationId as string | undefined;
  if (id && conv.value?.conversationId === id) { loading.value = false; return; } // already showing it
  loading.value = true; missing.value = false; error.value = null; correcting.value = false; confirmEnd.value = false;
  try {
    if (id) apply(await api.get(id));
    else if (route.query.new) apply({ conversation: null });
    else {
      const cur = await api.current();
      if (cur.conversation) { apply(cur as ConversationView); await router.replace(`/chat/${cur.conversation.conversationId}`); }
      else apply({ conversation: null });
    }
  } catch (e) {
    const f = e as ApiFailure;
    if (f.status === 401) markExpired();
    else if (f.status === 404) { missing.value = true; apply({ conversation: null }); }
    else error.value = { text: f.message, retry: load };
  } finally { loading.value = false; lastSeenSeq = maxAgentSeq(); }
}
watch(() => [route.params.conversationId, route.query.new], () => { stopAudio(); speakingSeq.value = null; void load(); }, { immediate: true });

/** Runs an API action; a retry re-sends the SAME requestId so the server de-duplicates it. */
async function run(action: (requestId: string) => Promise<ConversationView>, requestId: string = newRequestId()) {
  busy.value = true; error.value = null;
  if (mode.value === "voice") unlockAudio(); // still inside the user's tap, so sound is allowed later
  try {
    const v = await action(requestId); apply(v); speakNewReply();
    if (route.params.conversationId !== v.conversation.conversationId) await router.push(`/chat/${v.conversation.conversationId}`);
    return true;
  } catch (e) {
    const f = e as ApiFailure;
    if (f.status === 401) { markExpired(); error.value = { text: s.value.expired }; }
    else error.value = { text: f.message, retry: f.retryable ? async () => { await run(action, requestId); } : undefined };
    scrollDown(); return false;
  } finally { busy.value = false; }
}
const start = () => run((rid) => api.create(startLang.value, rid));
async function send() {
  const text = draft.value.trim(); if (!text || !conv.value || busy.value) return;
  const id = conv.value.conversationId;
  // Show the producer's message immediately (optimistic); the server response replaces the list.
  messages.value = [...messages.value, { seq: -1, role: "user", text, at: "", stage: stage.value }]; scrollDown();
  const before = draft.value; draft.value = "";
  if (!(await run((rid) => api.message(id, rid, text)))) { messages.value = messages.value.filter((m) => m.seq !== -1); draft.value = before; }
}
// Enter sends, Shift+Enter adds a line; Enter while composing accented or non-Latin text must not send (spec CHAT-20).
function onEnter(e: KeyboardEvent) { if (e.isComposing || e.keyCode === 229) return; e.preventDefault(); void send(); }
function addDictation(text: string) { draft.value = (draft.value.trim() + " " + text).trim(); nextTick(() => box.value?.focus()); }
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

function openConversation(id: string) { void router.push(`/chat/${id}`); }
function onDeleted(id: string) { if (conv.value?.conversationId === id) newConversation(); }
function newConversation() { conv.value = null; messages.value = []; error.value = null; void router.push({ path: "/chat", query: { new: "1" } }); }
function jump(st: Stage) { log.value?.querySelector<HTMLElement>(`[data-stage="${st}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" }); }
</script>

<template>
  <div class="chat-page" :class="{ 'no-panel': !conv }">
    <section class="chat-main" aria-label="Conversation">
      <header class="chat-hd">
        <div class="chat-actions">
          <button type="button" class="btn primary sm" @click="newConversation"><Plus :size="14" aria-hidden="true" />{{ s.newConversation }}</button>
          <HistoryPanel :current-id="conv?.conversationId" @open="openConversation" @deleted="onDeleted" />
        </div>
        <div class="chat-titlebar">
          <h1 class="chat-title">{{ heading }}</h1>
          <span v-if="conv" class="pill" :class="closed ? (outcome === 'saved' ? 'ok' : '') : 'warn'">{{ closed ? (outcome === "saved" ? s.outcomeSaved : s.outcomeDeclined) : s.inProgress }}</span>
        </div>
        <span class="grow" />
        <div v-if="audioSupported && conv && !closed" class="mode-seg" role="group" :aria-label="s.modeLabel" :title="mode === 'voice' ? s.modeVoiceHint : s.modeLabel">
          <button type="button" :aria-pressed="mode === 'text'" @click="setMode('text')"><Keyboard :size="14" aria-hidden="true" />{{ s.modeText }}</button>
          <button type="button" :aria-pressed="mode === 'voice'" @click="setMode('voice')"><Volume2 :size="14" aria-hidden="true" />{{ s.modeVoice }}</button>
        </div>
        <template v-if="conv && !closed">
          <button v-if="!confirmEnd" type="button" class="btn sm end-btn" :disabled="busy" :aria-label="s.end" :title="s.end" @click="confirmEnd = true"><X :size="12" aria-hidden="true" /><span class="end-label">{{ s.end }}</span></button>
          <span v-else role="alertdialog" aria-label="confirm end" class="row end-confirm">{{ s.endConfirm }}
            <button type="button" class="btn sm" @click="endNow">{{ s.end }}</button><button type="button" class="btn sm" @click="confirmEnd = false">{{ s.cancel }}</button></span>
        </template>
      </header>
      <ProgressPanel v-if="conv" class="only-narrow" variant="inline" :stage="stage" :outcome="outcome" :reached="reached" @jump="jump" />

      <div v-if="loading" class="chat-body" role="status"><span class="pill">…</span></div>

      <!-- No conversation selected: start one -->
      <div v-else-if="!conv" class="chat-body landing fade-up">
        <p v-if="missing" class="banner error" role="alert">{{ s.convMissing }}</p>
        <div class="hero hero-compact">
          <div>
            <h1>{{ s.welcome }}</h1>
            <span class="bar" aria-hidden="true" />
            <p>{{ s.about }}</p>
            <div class="seg" role="group" :aria-label="s.language">
              <button v-for="l in LANGS" :key="l.code" :aria-pressed="startLang === l.code" :lang="l.code" @click="startLang = l.code">{{ l.name }}</button>
            </div>
            <div><button class="btn primary" :disabled="busy" @click="start"><MessageCircle :size="16" aria-hidden="true" />{{ busy ? s.sending : s.start }}</button></div>
            <div v-if="error" class="banner error" role="alert">{{ error.text }} <button v-if="error.retry" class="btn sm" @click="error.retry()">{{ s.retry }}</button></div>
          </div>
        </div>
        <div class="grid3">
          <div class="card feat"><span class="ic brand-gradient"><MessageCircle :size="16" aria-hidden="true" /></span><div><h3>{{ s.feat1 }}</h3><p>{{ s.feat1d }}</p></div></div>
          <div class="card feat"><span class="ic brand-gradient"><CheckCircle2 :size="16" aria-hidden="true" /></span><div><h3>{{ s.feat2 }}</h3><p>{{ s.feat2d }}</p></div></div>
          <div class="card feat"><span class="ic brand-gradient"><EyeOff :size="16" aria-hidden="true" /></span><div><h3>{{ s.feat3 }}</h3><p>{{ s.feat3d }}</p></div></div>
        </div>
        <details class="card"><summary><ShieldCheck :size="14" aria-hidden="true" style="vertical-align:-2px" /> {{ s.privacyTitle }}</summary><p>{{ s.privacy }}</p></details>
      </div>

      <!-- A conversation: active or closed -->
      <template v-else>
        <div ref="log" class="log chat-body" role="log" aria-live="polite" aria-label="Messages">
          <template v-for="(m, i) in messages" :key="m.seq">
            <div v-if="m.role === 'user'" class="bubble-u fade-up" :data-stage="m.stage !== messages[i - 1]?.stage ? m.stage : undefined">{{ m.text }}</div>
            <div v-else class="row-a fade-up" :data-stage="m.stage !== messages[i - 1]?.stage ? m.stage : undefined">
              <span class="av brand-gradient"><Bot :size="16" aria-hidden="true" /><span class="sr">{{ s.assistant }}</span></span>
              <div style="min-width:0;flex:1">
                <div class="md" v-html="renderMarkdown(m.text)" />
                <div class="msg-actions">
                  <button type="button" class="act-btn" :aria-label="s.copy" :title="s.copy" @click="copy(m)"><Check v-if="copiedSeq === m.seq" :size="16" aria-hidden="true" /><Copy v-else :size="16" aria-hidden="true" /></button>
                  <button v-if="audioSupported" type="button" class="act-btn" :class="{ on: speakingSeq === m.seq }" :aria-label="speakingSeq === m.seq ? s.stopAudio : s.listen" :title="speakingSeq === m.seq ? s.stopAudio : s.listen" :aria-pressed="speakingSeq === m.seq" @click="listen(m)">
                    <Loader2 v-if="loadingSeq === m.seq" :size="16" class="spin" aria-hidden="true" /><Square v-else-if="speakingSeq === m.seq" :size="14" aria-hidden="true" /><Volume2 v-else :size="16" aria-hidden="true" />
                  </button>
                  <span v-if="loadingSeq === m.seq" class="act-note" role="status">{{ s.audioLoading }}</span>
                  <span v-else-if="audioErrSeq === m.seq" class="act-note err" role="alert">{{ s.audioError }}</span>
                  <span v-if="copiedSeq === m.seq" class="act-note" role="status">{{ s.copied }}</span>
                </div>
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

          <div v-if="conv.workflow === 'consent_pending'" class="decision pop" role="group" :aria-label="s.consentTitle" data-stage="consent">
            <p class="banner info" style="margin:0">{{ s.noEvidence }}</p>
            <h2>{{ s.consentTitle }}</h2>
            <p style="margin:0;font-size:.875rem;color:var(--muted)">{{ s.consentText }}</p>
            <blockquote class="quote" :lang="lang">{{ conv.summaryOriginal ?? conv.summaryEn }}</blockquote>
            <div class="row">
              <button class="btn primary" :disabled="busy" @click="decide(true)"><ShieldCheck :size="16" aria-hidden="true" />{{ s.storeYes }}</button>
              <button class="btn" :disabled="busy" @click="decide(false)">{{ s.storeNo }}</button>
            </div>
          </div>

          <div v-if="closed" class="decision closed-note" role="status">
            <span class="done-ic"><Heart v-if="outcome === 'saved'" :size="18" aria-hidden="true" /><Check v-else :size="18" aria-hidden="true" /></span>
            <p style="margin:0">{{ outcome === "saved" ? s.doneStored : s.doneDeclined }}</p>
            <p v-if="outcome === 'saved'" class="hint" style="margin:0">{{ messages.length ? s.readOnly : s.transcriptGone }}</p>
            <div><button type="button" class="btn primary" @click="newConversation"><Plus :size="16" aria-hidden="true" />{{ s.newConversation }}</button></div>
          </div>
        </div>

        <div v-if="conv.workflow === 'intake'" class="dock">
          <div v-if="showChips" class="fade-up"><p style="margin:0 0 .4rem;font-size:.8rem;color:var(--muted)">{{ s.chipsTitle }}</p>
            <div class="chips"><button v-for="c in s.chips" :key="c" class="chip" type="button" @click="pick(c)">{{ c }}</button></div></div>
          <form class="composer" @submit.prevent="send">
            <label for="msg" class="sr">{{ s.messageLabel }}</label>
            <textarea id="msg" ref="box" v-model="draft" rows="1" maxlength="2000" :placeholder="s.placeholder" :disabled="busy" @keydown.enter.exact="onEnter" />
            <DictateButton :language="conv.language" :disabled="busy" @text="addDictation" />
            <button class="send" type="submit" :disabled="busy || !draft.trim()" :aria-label="s.send"><SendHorizontal :size="18" aria-hidden="true" /></button>
          </form>
        </div>
      </template>
    </section>

    <aside v-if="conv" class="chat-progress only-wide" :aria-label="s.progressTitle">
      <ProgressPanel variant="panel" :stage="stage" :outcome="outcome" :reached="reached" @jump="jump" />
    </aside>
  </div>
</template>
