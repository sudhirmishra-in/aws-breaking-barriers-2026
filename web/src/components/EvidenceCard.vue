<script setup lang="ts">
// One evidence finding. Origin (External / FTUSA) and curation (Certified) are independent labels and can both apply.
import { useL } from "../lib/labels";
import type { EvidenceItem } from "../types";
defineProps<{ item: EvidenceItem }>();
const l = useL();
</script>
<template>
  <article class="card ev">
    <div class="row">
      <span class="pill">{{ item.origin === "external_imported" ? l.ev.external : l.ev.ftusa }}</span>
      <span v-if="item.curationStatus === 'ftusa_curated'" class="pill ok">{{ l.ev.certified }}</span>
      <span v-if="item.illustrative" class="pill warn" :title="l.ev.illTip">{{ l.ev.illustrative }}</span>
      <span v-if="item.stale" class="pill warn">{{ l.ev.older }}</span>
    </div>
    <h4 v-if="item.title" class="ev-title">{{ item.title }}</h4>
    <p>{{ item.finding }}</p>
    <dl v-if="item.kind === 'project_record'" class="kv"><dt>{{ l.ev.status }}</dt><dd>{{ item.recordedStatus }}</dd><dt>{{ l.ev.result }}</dt><dd class="hint">{{ l.ev.outcomeNot }}</dd>
      <dt>{{ l.ev.topic }}</dt><dd>{{ item.taxonomy }}</dd></dl>
    <div class="chips"><span class="chip">{{ item.source }}</span><span class="chip">{{ item.geography }}</span><span class="chip">{{ item.period }}</span>
      <span v-if="item.citation" class="chip" :title="`Data version ${item.citation.dataVersion}`">{{ item.citation.label }}</span><span v-for="s in item.standards" :key="s" class="chip">{{ s }}</span></div>
  </article>
</template>
