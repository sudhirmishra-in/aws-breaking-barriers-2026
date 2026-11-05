<script setup lang="ts">
// The organization's issue history for this conversation: dated facts, a question when a match is uncertain, and producer-entered updates.
import { onMounted, ref } from "vue";
import { api } from "../lib/api";
import { useL } from "../lib/labels";
import type { ApiFailure, IssueContext } from "../types";

const props = defineProps<{ conversationId: string }>();
const l = useL();
const ctx = ref<IssueContext | null>(null); const err = ref(""); const busy = ref(false);
const form = ref<{ type: "action_planned" | "action" | "outcome"; text: string }>({ type: "action", text: "" });
async function load() { try { ctx.value = await api.issueContext(props.conversationId); } catch (e) { err.value = (e as ApiFailure).message; } }
onMounted(load);
async function act(fn: () => Promise<unknown>) { busy.value = true; err.value = ""; try { await fn(); await load(); form.value.text = ""; } catch (e) { err.value = (e as ApiFailure).message; } finally { busy.value = false; } }
const link = (same: boolean, id?: string) => act(() => api.linkIssue(props.conversationId, same, id));
const add = (type: "action_planned" | "action" | "outcome" | "resolution_confirmed" | "recurrence", text?: string) => act(() => api.addIssueEvent(ctx.value!.issue!.issueId, type, text));
const day = (iso: string) => iso.slice(0, 10);
</script>

<template>
  <section v-if="ctx" class="card" :aria-label="l.hist.title">
    <h3>{{ l.hist.title }}</h3>
    <p v-if="err" class="banner error" role="alert">{{ err }}</p>

    <template v-if="ctx.decision === 'pending'">
      <p>{{ l.hist.pending }}</p>
      <div v-for="c in ctx.candidates" :key="c.issueId" class="hist-cand">
        <span class="pill">{{ l.hist.status[c.status] }}</span> <span class="hint">{{ day(c.lastReportedAt) }}</span>
        <p style="margin:.25rem 0">{{ c.description }}</p>
        <button class="btn sm primary" :disabled="busy" @click="link(true, c.issueId)">{{ l.hist.same }}</button>
      </div>
      <button class="btn sm" :disabled="busy" @click="link(false)">{{ l.hist.separate }}</button>
    </template>

    <template v-else-if="ctx.issue">
      <div class="row"><span class="pill" :class="ctx.issue.status === 'resolved' ? 'ok' : ctx.issue.status === 'recurring' ? 'warn' : ''">{{ l.hist.status[ctx.issue.status] }}</span>
        <span class="hint">{{ ctx.issue.reporterCount }} {{ l.hist.reporters }}</span><span v-if="ctx.issue.synthetic" class="pill warn">{{ l.hist.synthetic }}</span></div>
      <ol class="hist-tl">
        <li v-for="e in ctx.issue.events" :key="e.eventId" :class="{ sup: e.superseded }"><b>{{ day(e.at) }}</b> · {{ l.hist.ev[e.type as keyof typeof l.hist.ev] ?? e.type }}<span v-if="e.text">: {{ e.text }}</span></li>
      </ol>
      <details><summary>{{ l.hist.record }}</summary>
        <form class="pinfo-form" @submit.prevent="form.text.trim() && add(form.type, form.text.trim())">
          <label class="fld">{{ l.hist.what }}
            <select v-model="form.type"><option value="action_planned">{{ l.hist.planned }}</option><option value="action">{{ l.hist.tried }}</option><option value="outcome">{{ l.hist.result }}</option></select>
            <textarea v-model="form.text" rows="2" maxlength="500" /></label>
          <div class="row"><button class="btn sm primary" type="submit" :disabled="busy || !form.text.trim()">{{ l.hist.save }}</button>
            <button class="btn sm" type="button" :disabled="busy" @click="add('resolution_confirmed')">{{ l.hist.confirmRes }}</button>
            <button class="btn sm" type="button" :disabled="busy" @click="add('recurrence', l.hist.again)">{{ l.hist.again }}</button></div>
        </form></details>
      <p class="hint">{{ l.hist.noteFact }}</p>
    </template>

    <div v-if="ctx.recall.length" class="hist-mem"><h4 class="ev-sub">{{ l.hist.memory }}</h4>
      <ul class="list"><li v-for="(r, i) in ctx.recall" :key="i" class="hint" style="padding:.35rem 0">{{ r }}</li></ul><p class="hint">{{ l.hist.memoryNote }}</p></div>
    <p class="hint">{{ l.hist.mem[ctx.memoryStatus] }}</p>
  </section>
</template>
