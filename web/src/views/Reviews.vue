<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import { ChevronRight, ClipboardCheck } from "lucide-vue-next";
import { api } from "../lib/api";
import { state } from "../session";
import { t } from "../lib/i18n";
import type { ReviewItem } from "../types";
const s = computed(() => t(state.ui));
const items = ref<ReviewItem[]>([]); const err = ref(""); const loading = ref(true);
const cls = (r: ReviewItem["reviewStatus"]) => (r === "pending" ? "warn" : "ok");
onMounted(async () => { try { items.value = (await api.reviews()).items; } catch (e) { err.value = (e as Error).message; } finally { loading.value = false; } });
</script>
<template>
  <h1 class="page-title"><ClipboardCheck :size="22" aria-hidden="true" style="vertical-align:-3px" /> {{ s.reviewList }}</h1>
  <p v-if="err" role="alert" class="banner error">{{ err }}</p>
  <p v-else-if="!loading && !items.length" class="card" style="color:var(--muted)">{{ s.none }}</p>
  <ul class="list">
    <li v-for="i in items" :key="i.outcomeId" class="fade-up">
      <RouterLink class="item" :to="`/review/${i.outcomeId}`">
        <span><strong>{{ i.createdAt.slice(0, 10) }}</strong> · {{ i.producerId }} · {{ i.language.toUpperCase() }}</span>
        <span class="row" style="align-items:center">
          <span v-if="i.piiFlag" class="pill err">{{ s.piiFlag }}</span>
          <span class="pill" :class="cls(i.reviewStatus)">{{ s[i.reviewStatus] }}</span><ChevronRight :size="16" aria-hidden="true" />
        </span>
      </RouterLink>
    </li>
  </ul>
</template>
