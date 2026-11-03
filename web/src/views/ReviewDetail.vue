<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink, useRoute } from "vue-router";
import { api } from "../lib/api";
import { state } from "../session";
import { t } from "../lib/i18n";
import type { ReviewItem } from "../types";
const s = computed(() => t(state.ui));
const id = useRoute().params.id as string;
const item = ref<ReviewItem | null>(null); const err = ref(""); const busy = ref(false);
const en = ref(""); const es = ref(""); const handled = ref(false);
onMounted(async () => { try { item.value = await api.review(id); en.value = item.value.summaryEn ?? ""; es.value = item.value.summaryEs ?? ""; } catch (e) { err.value = (e as Error).message; } });
async function submit(decision: "approve" | "correct") {
  busy.value = true; err.value = "";
  try {
    item.value = await api.updateReview(id, decision === "approve" ? { decision, piiHandled: handled.value || undefined } : { decision, correctedSummaryEn: en.value, correctedSummaryEs: es.value, piiHandled: handled.value || undefined });
  } catch (e) { err.value = (e as Error).message; } finally { busy.value = false; }
}
</script>
<template>
  <RouterLink to="/review" style="display:inline-block;margin-top:1rem">← {{ s.back }}</RouterLink>
  <p v-if="err" role="alert" class="banner error">{{ err }}</p>
  <section v-if="item" class="card fade-up" style="display:grid;gap:.75rem;margin-top:1rem">
    <p class="row"><span class="pill">{{ item.source }}</span> <span class="pill" :class="item.reviewStatus === 'pending' ? 'warn' : 'ok'">{{ s[item.reviewStatus] }}</span> <span class="pill warn">{{ s.demo }}</span></p>
    <p v-if="item.piiFlag" class="banner info">{{ s.piiFlag }}: {{ item.piiTypes?.join(", ") }}</p>
    <label class="fld">{{ s.summaryEn }}<textarea v-model="en" rows="4" :disabled="item.reviewStatus !== 'pending'" /></label>
    <label class="fld">{{ s.summaryEs }}<textarea v-model="es" rows="4" :disabled="item.reviewStatus !== 'pending'" /></label>
    <label v-if="item.piiFlag && item.reviewStatus === 'pending'" class="row" style="align-items:center"><input v-model="handled" type="checkbox" /> {{ s.markHandled }}</label>
    <div v-if="item.reviewStatus === 'pending'" class="row">
      <button class="btn primary" :disabled="busy" @click="submit('approve')">{{ s.approve }}</button>
      <button class="btn" :disabled="busy" @click="submit('correct')">{{ s.correct }}</button>
    </div>
  </section>
</template>
