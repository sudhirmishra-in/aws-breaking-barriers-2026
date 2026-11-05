<script setup lang="ts">
// Peer case cards. Everything shown here is a server-side projection of reviewed, shared cases (never transcripts).
import { onMounted, ref } from "vue";
import { Users } from "lucide-vue-next";
import { api } from "../lib/api";
import { useL } from "../lib/labels";
import type { ApiFailure, PeerCase } from "../types";

const props = defineProps<{ scope: "organization" | "other" | "all"; title: string; only?: string[]; relatedTo?: string }>();
const emit = defineEmits<{ ask: [caseId: string] }>();
const l = useL();
const items = ref<PeerCase[]>([]); const limited = ref(false); const err = ref(""); const loading = ref(true);
async function load() {
  loading.value = true; err.value = ""; limited.value = false;
  try {
    if (props.relatedTo) { const r = await api.comparable(props.relatedTo); items.value = r.items; limited.value = !!r.limitation; return; } // comparable cases only (server-side)
    const r = await api.peers(props.scope); items.value = props.only?.length ? r.items.filter((c) => c.tags.some((t) => props.only!.includes(t))) : r.items; }
  catch (e) { err.value = (e as ApiFailure).message; } finally { loading.value = false; }
}
onMounted(load);
/** The server sends the reason chips as English phrases; show them in the interface language. */
function chip(r: string): string {
  const m = /^(Same crop|Same challenge|Same country): (.*)$/.exec(r);
  if (m) return `${{ "Same crop": l.value.peer.sameCrop, "Same challenge": l.value.peer.sameChallenge, "Same country": l.value.peer.sameCountry }[m[1]]}: ${m[2]}`;
  return r === "Your organization" ? l.value.peer.yourOrgChip : r;
}
const who = (c: PeerCase) => c.producer?.name ?? (c.sameOrganization ? l.value.peer.anonOrg : l.value.peer.anonOther);
</script>

<template>
  <section class="peer-sec" :aria-label="title">
    <h2 class="page-title" style="font-size:1.05rem"><Users :size="16" aria-hidden="true" /> {{ title }}</h2>
    <p v-if="err" class="banner error" role="alert">{{ err }} <button type="button" class="btn sm" @click="load">{{ l.tryAgain }}</button></p>
    <p v-else-if="loading" class="hint" role="status">{{ l.loading }}</p>
    <template v-else>
      <p v-if="!items.length" class="hint">{{ limited ? l.ins.noClose : l.noShared }}</p>
      <article v-for="c in items" :key="c.caseId" class="card peer">
        <div class="row"><b>{{ who(c) }}</b>
          <span class="pill" :class="c.sameOrganization ? 'ok' : ''">{{ c.sameOrganization ? l.peer.yourOrg : l.peer.otherOrg }}</span>
          <span v-if="c.visibility === 'organization_only'" class="pill" :title="l.peer.orgOnlyTip">{{ l.peer.orgOnly }}</span>
          <span v-if="c.illustrative" class="pill warn">{{ l.peer.illustrative }}</span></div>
        <p v-if="c.reason" class="match-why"><span class="pill" :class="c.fit === 'strong' ? 'ok' : 'warn'">{{ c.fit === "strong" ? l.peer.close : l.peer.partial }}</span> {{ c.reason }}</p>
        <div v-if="c.relevance?.length" class="chips"><span v-for="r in c.relevance" :key="r" class="pill">{{ chip(r) }}</span></div>
        <dl class="kv"><dt>{{ l.peer.challenge }}</dt><dd>{{ c.challenge }}<span v-if="c.summaryOriginal && c.language !== 'en'" class="hint" :lang="c.language" style="display:block">{{ c.summaryOriginal }}</span></dd><dt>{{ l.peer.did }}</dt><dd>{{ c.action ?? l.peer.notReported }}</dd>
          <dt>{{ l.peer.result }}</dt><dd :class="{ hint: !c.resultReported }">{{ c.resultReported ? c.result : l.peer.outcomeNot }}</dd></dl>
        <div class="chips"><span v-for="r in c.citations" :key="r.label" class="chip">{{ r.label }}</span><span v-for="s in c.standards" :key="s" class="chip">{{ s }}</span></div>
        <button type="button" class="btn sm" @click="emit('ask', c.caseId)">{{ l.peer.ask }}</button>
      </article>
      <p class="hint">{{ l.peer.visibility }}</p>
    </template>
  </section>
</template>
