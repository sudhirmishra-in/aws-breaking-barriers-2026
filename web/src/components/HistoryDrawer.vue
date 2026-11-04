<script setup lang="ts">
// Conversation history (spec CONV-01/02), kept out of the main layout: a slide-out panel opened from an icon.
import { computed, nextTick, ref, watch } from "vue";
import { Plus, RotateCw, X } from "lucide-vue-next";
import { api } from "../lib/api";
import { state } from "../session";
import { t } from "../lib/i18n";
import type { ConversationSummary } from "../types";

const props = defineProps<{ open: boolean; currentId?: string | null }>();
const emit = defineEmits<{ close: []; select: [id: string]; new: [] }>();
const s = computed(() => t(state.ui));
const items = ref<ConversationSummary[]>([]);
const loading = ref(false);
const failed = ref(false);
const closeBtn = ref<HTMLButtonElement | null>(null);

async function load() {
  loading.value = true; failed.value = false;
  try { items.value = (await api.list()).items; } catch { failed.value = true; } finally { loading.value = false; }
}
watch(() => props.open, (o) => { if (o) { void load(); nextTick(() => closeBtn.value?.focus()); } });

const DAY = 86_400_000;
const groups = computed(() => {
  const start = new Date(); start.setHours(0, 0, 0, 0);
  const today: ConversationSummary[] = [], week: ConversationSummary[] = [], older: ConversationSummary[] = [];
  for (const c of items.value) {
    const at = new Date(c.createdAt).getTime();
    (at >= start.getTime() ? today : at >= start.getTime() - 7 * DAY ? week : older).push(c);
  }
  return [{ key: "today", label: s.value.today, list: today }, { key: "prev7", label: s.value.prev7, list: week }, { key: "older", label: s.value.older, list: older }].filter((g) => g.list.length);
});
const fmt = (iso: string) => new Date(iso).toLocaleDateString(state.ui === "es" ? "es" : "en", { month: "short", day: "numeric" });
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="drawer-backdrop" aria-hidden="true" @click="emit('close')" />
    <aside v-if="open" class="drawer" role="dialog" aria-modal="true" :aria-label="s.history" @keydown.esc="emit('close')">
      <div class="drawer-hd">
        <h2>{{ s.history }}</h2>
        <button ref="closeBtn" type="button" class="icon-btn" :aria-label="s.closeHistory" @click="emit('close')"><X :size="18" aria-hidden="true" /></button>
      </div>
      <button type="button" class="btn primary" @click="emit('new')"><Plus :size="16" aria-hidden="true" />{{ s.newConversation }}</button>
      <p v-if="loading && !items.length" role="status" class="hint">…</p>
      <p v-else-if="failed" class="banner error" role="alert">{{ s.historyError }} <button type="button" class="btn sm" @click="load"><RotateCw :size="12" aria-hidden="true" />{{ s.retry }}</button></p>
      <p v-else-if="!items.length" class="hint">{{ s.historyEmpty }}</p>
      <nav v-else :aria-label="s.history">
        <section v-for="g in groups" :key="g.key" class="hist-group">
          <h3>{{ g.label }}</h3>
          <ul>
            <li v-for="c in g.list" :key="c.conversationId">
              <button type="button" class="hist-item" :aria-current="c.conversationId === currentId ? 'page' : undefined" @click="emit('select', c.conversationId)">
                <span class="hist-title">{{ c.title || s.untitled }}</span>
                <span class="hist-meta">
                  <span v-if="c.status === 'in_progress'" class="hist-dot" aria-hidden="true" />
                  {{ c.status === "in_progress" ? s.inProgress : s.savedStatus }} · {{ fmt(c.createdAt) }} · {{ c.language.toUpperCase() }}
                </span>
              </button>
            </li>
          </ul>
        </section>
      </nav>
    </aside>
  </Teleport>
</template>
