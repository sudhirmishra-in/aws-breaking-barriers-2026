<script setup lang="ts">
// One evidence finding. Origin (External / FTUSA) and curation (Curated) are independent labels and can both apply.
import type { EvidenceItem } from "../types";
defineProps<{ item: EvidenceItem }>();
</script>
<template>
  <article class="card ev">
    <div class="row">
      <span class="pill">{{ item.origin === "external_imported" ? "EXTERNAL" : "FAIR TRADE USA" }}</span>
      <span v-if="item.curationStatus === 'ftusa_curated'" class="pill ok">FAIR TRADE CERTIFIED DATA</span>
      <span v-if="item.illustrative" class="pill warn" title="This value is a placeholder for testing. It is not real data.">Illustrative data</span>
      <span v-if="item.stale" class="pill warn">Older data</span>
    </div>
    <h4 v-if="item.title" class="ev-title">{{ item.title }}</h4>
    <p>{{ item.finding }}</p>
    <dl v-if="item.kind === 'project_record'" class="kv"><dt>Recorded status</dt><dd>{{ item.recordedStatus }}</dd><dt>Result</dt><dd class="hint">{{ item.outcome }}</dd>
      <dt>Topic</dt><dd>{{ item.taxonomy }}</dd></dl>
    <div class="chips"><span class="chip">{{ item.source }}</span><span class="chip">{{ item.geography }}</span><span class="chip">{{ item.period }}</span>
      <span v-if="item.citation" class="chip" :title="`Data version ${item.citation.dataVersion}`">{{ item.citation.label }}</span><span v-for="s in item.standards" :key="s" class="chip">{{ s }}</span></div>
  </article>
</template>
