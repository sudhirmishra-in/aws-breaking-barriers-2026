<script setup lang="ts">
import { computed, nextTick, reactive, ref } from "vue";
import { AlertTriangle, Bot, RotateCw, SendHorizontal, Trash2 } from "lucide-vue-next";
import { api, newRequestId } from "../lib/api";
import { renderMarkdown } from "../lib/markdown";
import { markExpired, state } from "../session";
import { t } from "../lib/i18n";
import { ApiFailure } from "../types";

interface QA { q: string; a?: string; err?: string; retryable?: boolean; rid: string }
const s = computed(() => t(state.ui));
const items = ref<QA[]>([]); const draft = ref(""); const busy = ref(false); const log = ref<HTMLElement | null>(null);
const down = () => nextTick(() => log.value?.scrollTo({ top: log.value.scrollHeight }));
async function ask(item: QA) {
  busy.value = true; item.err = undefined; down();
  try { item.a = (await api.ask(item.rid, item.q, state.ui)).answer; }
  catch (e) { const f = e as ApiFailure; if (f.status === 401) { markExpired(); item.err = s.value.expired; } else { item.err = f.message; item.retryable = f.retryable; } }
  finally { busy.value = false; down(); }
}
function submit() { const q = draft.value.trim(); if (!q || busy.value) return; const item = reactive({ q, rid: newRequestId() } as QA); items.value.push(item); draft.value = ""; ask(items.value[items.value.length - 1]); }
</script>
<template>
  <section class="shell fade-up">
    <div class="shell-hd"><h1>{{ s.askTitle }}</h1><span class="pill warn">{{ s.evidenceBadge }}</span><span class="grow" />
      <button v-if="items.length" class="btn sm" :disabled="busy" @click="items = []"><Trash2 :size="12" aria-hidden="true" />{{ s.clear }}</button></div>
    <div ref="log" class="log" role="log" aria-live="polite" aria-label="Questions and answers">
      <div v-if="!items.length" class="fade-up"><p style="color:var(--muted);font-size:.9rem;margin-top:0">{{ s.askIntro }}</p>
        <div class="chips"><button v-for="c in s.askChips" :key="c" class="chip" @click="draft = c">{{ c }}</button></div></div>
      <template v-for="(it, idx) in items" :key="idx">
        <div class="bubble-u fade-up">{{ it.q }}</div>
        <div v-if="it.a" class="row-a fade-up"><span class="av brand-gradient"><Bot :size="16" aria-hidden="true" /></span><div class="md" v-html="renderMarkdown(it.a)" /></div>
        <div v-else-if="it.err" class="row-a fade-up" role="alert"><span class="av" style="background:color-mix(in srgb,var(--err) 18%,transparent);color:var(--err)"><AlertTriangle :size="16" aria-hidden="true" /></span>
          <div class="err-bubble"><b>{{ s.failed }}</b><div style="color:var(--muted);margin:.25rem 0">{{ it.err }}</div><button v-if="it.retryable" class="btn sm" @click="ask(it)"><RotateCw :size="12" aria-hidden="true" />{{ s.retry }}</button></div></div>
        <div v-else class="row-a fade-up" role="status"><span class="av brand-gradient"><span style="display:flex;gap:2px" aria-hidden="true"><i v-for="d in 3" :key="d" class="dot" :style="{ animationDelay: `${(d - 1) * 0.15}s` }" /></span></span><span style="font-size:.875rem;color:var(--muted);align-self:center">{{ s.asking }}</span></div>
      </template>
    </div>
    <div class="dock"><p style="margin:0;font-size:.75rem;color:var(--muted)">{{ s.askNote }}</p>
      <form class="composer" @submit.prevent="submit"><label for="q" class="sr">{{ s.askPlaceholder }}</label>
        <textarea id="q" v-model="draft" rows="1" maxlength="1000" :placeholder="s.askPlaceholder" :disabled="busy" @keydown.enter.exact.prevent="submit" />
        <button class="send" type="submit" :disabled="busy || !draft.trim()" :aria-label="s.askSend"><SendHorizontal :size="18" aria-hidden="true" /></button></form></div>
  </section>
</template>
