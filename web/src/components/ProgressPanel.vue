<script setup lang="ts">
// "Your progress" (spec CHAT-07/08): five stages, current stage from the backend, terminal outcome label.
import { computed, ref } from "vue";
import { Check } from "lucide-vue-next";
import { state } from "../session";
import { t } from "../lib/i18n";
import type { Stage } from "../types";

const props = defineProps<{ stage: Stage; outcome: "saved" | "declined" | null; reached: Stage[]; variant: "panel" | "inline" }>();
const emit = defineEmits<{ jump: [stage: Stage] }>();
const s = computed(() => t(state.ui));
const ORDER: Stage[] = ["intake", "playback", "response", "consent", "feedback"];
const current = computed(() => ORDER.indexOf(props.stage));
const isDone = (i: number) => (props.outcome ? i <= 3 : i < current.value);
const stepLabel = computed(() => s.value.stepOf.replace("{n}", String(current.value + 1)));
const expanded = ref(false);
</script>

<template>
  <div class="pp" :class="variant">
    <button v-if="variant === 'inline'" type="button" class="pp-toggle" :aria-expanded="expanded" @click="expanded = !expanded">
      <template v-if="outcome"><span class="pp-outcome" :class="outcome">{{ outcome === "saved" ? s.outcomeSaved : s.outcomeDeclined }}</span></template>
      <template v-else>{{ stepLabel }} · {{ s.stageNames[stage] }}</template>
      <span class="pp-chev">{{ expanded ? s.hideProgress : s.showProgress }}</span>
    </button>
    <div v-show="variant === 'panel' || expanded">
      <div v-if="variant === 'panel'" class="pp-head">
        <span class="pp-kicker">{{ s.progressTitle }}</span>
        <span v-if="outcome" class="pp-outcome" :class="outcome">{{ outcome === "saved" ? s.outcomeSaved : s.outcomeDeclined }}</span>
        <span v-else class="pp-step">{{ stepLabel }}</span>
      </div>
      <ol class="pp-list">
        <li v-for="(st, i) in ORDER" :key="st" :class="{ done: isDone(i), now: !outcome && i === current }" :aria-current="!outcome && i === current ? 'step' : undefined">
          <span class="pp-mark" aria-hidden="true"><Check v-if="isDone(i)" :size="13" :stroke-width="3" /><template v-else>{{ i + 1 }}</template></span>
          <div class="pp-body">
            <button v-if="isDone(i) && reached.includes(st)" type="button" class="pp-name link-btn" :title="s.jumpTo" @click="emit('jump', st)">{{ s.stageNames[st] }}</button>
            <span v-else class="pp-name">{{ s.stageNames[st] }}</span>
            <span class="pp-desc">{{ s.stageDesc[st] }}</span>
            <span v-if="!outcome && i === current" class="pp-here">{{ s.youAreHere }}</span>
            <span v-if="st === 'feedback'" class="pp-desc pp-muted">{{ s.notYet }}</span>
          </div>
        </li>
      </ol>
    </div>
  </div>
</template>
