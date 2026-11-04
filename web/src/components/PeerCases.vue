<script setup lang="ts">
// Peer case cards. Everything shown here is a server-side projection of reviewed, shared cases (never transcripts).
import { onMounted, ref } from "vue";
import { Users } from "lucide-vue-next";
import { api } from "../lib/api";
import type { ApiFailure, PeerCase } from "../types";

const props = defineProps<{ scope: "organization" | "other" | "all"; title: string; only?: string[]; relatedTo?: string }>();
const emit = defineEmits<{ ask: [caseId: string] }>();
const items = ref<PeerCase[]>([]); const note = ref(""); const empty = ref("No shared cases yet."); const err = ref(""); const loading = ref(true);
async function load() {
  loading.value = true; err.value = "";
  try {
    if (props.relatedTo) { const r = await api.comparable(props.relatedTo); items.value = r.items; empty.value = r.limitation ?? empty.value; note.value = ""; return; } // comparable cases only (server-side)
    const r = await api.peers(props.scope); note.value = r.visibility; items.value = props.only?.length ? r.items.filter((c) => c.tags.some((t) => props.only!.includes(t))) : r.items; }
  catch (e) { err.value = (e as ApiFailure).message; } finally { loading.value = false; }
}
onMounted(load);
</script>

<template>
  <section class="peer-sec" :aria-label="title">
    <h2 class="page-title" style="font-size:1.05rem"><Users :size="16" aria-hidden="true" /> {{ title }}</h2>
    <p v-if="err" class="banner error" role="alert">{{ err }} <button type="button" class="btn sm" @click="load">Try again</button></p>
    <p v-else-if="loading" class="hint" role="status">Loading…</p>
    <template v-else>
      <p v-if="!items.length" class="hint">{{ empty }}</p>
      <article v-for="c in items" :key="c.caseId" class="card peer">
        <div class="row"><b>{{ c.producer?.name ?? c.anonymousLabel }}</b>
          <span class="pill" :class="c.sameOrganization ? 'ok' : ''">{{ c.sameOrganization ? "Your organization" : "Another organization" }}</span>
          <span v-if="c.visibility === 'organization_only'" class="pill" title="Only people in your organization can see this summary">Organization only</span>
          <span v-if="c.illustrative" class="pill warn">Illustrative</span></div>
        <div v-if="c.relevance?.length" class="chips"><span v-for="r in c.relevance" :key="r" class="pill">{{ r }}</span></div>
        <dl class="kv"><dt>Challenge they faced</dt><dd>{{ c.challenge }}<span v-if="c.summaryOriginal && c.language !== 'en'" class="hint" :lang="c.language" style="display:block">{{ c.summaryOriginal }}</span></dd><dt>What they did</dt><dd>{{ c.action ?? "Not reported" }}</dd>
          <dt>Result</dt><dd :class="{ hint: !c.resultReported }">{{ c.result }}</dd></dl>
        <div class="chips"><span v-for="r in c.citations" :key="r.label" class="chip">{{ r.label }}</span><span v-for="s in c.standards" :key="s" class="chip">{{ s }}</span></div>
        <button type="button" class="btn sm" @click="emit('ask', c.caseId)">Ask about this</button>
      </article>
      <p class="hint">{{ note }}</p>
    </template>
  </section>
</template>
