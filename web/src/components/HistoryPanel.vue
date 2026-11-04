<script setup lang="ts">
// Conversation history (spec CONV-01/02): a small history icon that opens a compact dropdown.
// Picking a conversation shows its summary first; "See full conversation" opens the whole transcript.
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { ArrowLeft, History, MessageSquareText, RotateCw, Trash2 } from "lucide-vue-next";
import { api } from "../lib/api";
import { state } from "../session";
import { t } from "../lib/i18n";
import type { ConversationSummary } from "../types";

const props = defineProps<{ currentId?: string | null }>();
const emit = defineEmits<{ open: [id: string]; deleted: [id: string] }>();
const s = computed(() => t(state.ui));
const open = ref(false);
const items = ref<ConversationSummary[]>([]);
const loading = ref(false);
const failed = ref(false);
const selected = ref<ConversationSummary | null>(null);
const root = ref<HTMLElement | null>(null);
const toggleBtn = ref<HTMLButtonElement | null>(null);
const panel = ref<HTMLElement | null>(null);
const confirming = ref(false);
const deleting = ref(false);
const deleteError = ref(false);

async function load() {
  loading.value = true; failed.value = false;
  try { items.value = (await api.list()).items; } catch { failed.value = true; } finally { loading.value = false; }
}
function onOutside(e: MouseEvent) { if (root.value && !root.value.contains(e.target as Node)) close(false); }
function close(returnFocus = true) {
  open.value = false; selected.value = null;
  if (returnFocus) nextTick(() => toggleBtn.value?.focus());
}
function toggle() { if (open.value) close(); else { open.value = true; void load(); nextTick(() => panel.value?.focus()); } }
watch(open, (o) => { if (o) document.addEventListener("mousedown", onOutside); else document.removeEventListener("mousedown", onOutside); });
onBeforeUnmount(() => document.removeEventListener("mousedown", onOutside));

function pick(c: ConversationSummary) { selected.value = c; confirming.value = false; deleteError.value = false; nextTick(() => panel.value?.querySelector<HTMLElement>(".hist-back")?.focus()); }
function seeFull(id: string) { close(false); emit("open", id); }
async function remove(id: string) {
  deleting.value = true; deleteError.value = false;
  try {
    await api.remove(id);
    items.value = items.value.filter((c) => c.conversationId !== id);
    selected.value = null; confirming.value = false;
    emit("deleted", id);
  } catch { deleteError.value = true; } finally { deleting.value = false; }
}

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
const fmt = (iso: string) => new Date(iso).toLocaleDateString(state.ui === "es" ? "es" : "en", { month: "short", day: "numeric", year: "numeric" });
</script>

<template>
  <div ref="root" class="hist-wrap" @keydown.esc.stop="close()">
    <button ref="toggleBtn" type="button" class="icon-btn hist-toggle" :aria-label="s.openHistory" :title="s.openHistory" aria-haspopup="dialog" :aria-expanded="open" @click="toggle">
      <History :size="18" aria-hidden="true" />
    </button>
    <div v-if="open" ref="panel" class="hist-pop" role="dialog" :aria-label="s.history" tabindex="-1">
      <!-- Detail: the summary first -->
      <template v-if="selected">
        <button type="button" class="link-btn hist-back" @click="selected = null"><ArrowLeft :size="14" aria-hidden="true" /> {{ s.allConversations }}</button>
        <h3 class="hist-detail-title">{{ selected.title || s.untitled }}</h3>
        <p class="hist-meta">
          <span v-if="selected.status === 'in_progress'" class="hist-dot" aria-hidden="true" />
          {{ selected.status === "in_progress" ? s.inProgress : s.savedStatus }} · {{ fmt(selected.createdAt) }} · {{ selected.language.toUpperCase() }}
        </p>
        <section class="hist-summary" :aria-label="s.summaryLabel">
          <span class="pp-kicker">{{ s.summaryLabel }}</span>
          <p v-if="selected.summary" :lang="selected.language">{{ selected.summary }}</p>
          <p v-else class="hint">{{ s.noSummaryYet }}</p>
        </section>
        <button type="button" class="btn primary sm" @click="seeFull(selected.conversationId)">
          <MessageSquareText :size="14" aria-hidden="true" />{{ selected.status === "in_progress" ? s.continueConv : s.seeFull }}
        </button>
        <template v-if="selected.status === 'saved'">
          <button v-if="!confirming" type="button" class="link-btn hist-delete" @click="confirming = true"><Trash2 :size="13" aria-hidden="true" /> {{ s.deleteFromHistory }}</button>
          <div v-else class="hist-confirm" role="alertdialog" :aria-label="s.deleteFromHistory">
            <p>{{ s.deleteConfirm }}</p>
            <div class="row">
              <button type="button" class="btn sm danger" :disabled="deleting" @click="remove(selected.conversationId)">{{ deleting ? s.deleting : s.deleteYes }}</button>
              <button type="button" class="btn sm" :disabled="deleting" @click="confirming = false">{{ s.cancel }}</button>
            </div>
            <p v-if="deleteError" class="mic-msg error" role="alert">{{ s.deleteFailed }}</p>
          </div>
        </template>
      </template>

      <!-- List -->
      <template v-else>
        <h2 class="hist-pop-title">{{ s.history }}</h2>
        <p v-if="loading && !items.length" role="status" class="hint">…</p>
        <p v-else-if="failed" class="banner error" role="alert">{{ s.historyError }} <button type="button" class="btn sm" @click="load"><RotateCw :size="12" aria-hidden="true" />{{ s.retry }}</button></p>
        <p v-else-if="!items.length" class="hint">{{ s.historyEmpty }}</p>
        <nav v-else :aria-label="s.history">
          <section v-for="g in groups" :key="g.key" class="hist-group">
            <h3>{{ g.label }}</h3>
            <ul>
              <li v-for="c in g.list" :key="c.conversationId">
                <button type="button" class="hist-item" :aria-current="c.conversationId === props.currentId ? 'page' : undefined" @click="pick(c)">
                  <span class="hist-title">{{ c.title || s.untitled }}</span>
                  <span class="hist-meta">
                    <span v-if="c.status === 'in_progress'" class="hist-dot" aria-hidden="true" />
                    {{ c.status === "in_progress" ? s.inProgress : s.savedStatus }} · {{ fmt(c.createdAt) }}
                  </span>
                </button>
              </li>
            </ul>
          </section>
        </nav>
      </template>
    </div>
  </div>
</template>
