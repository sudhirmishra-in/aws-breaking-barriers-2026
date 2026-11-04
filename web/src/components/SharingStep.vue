<script setup lang="ts">
// Confirm the summary and choose sharing. Choices show exactly what each one exposes; identity is a separate, explicit tick.
import { computed, ref } from "vue";
import { ShieldCheck } from "lucide-vue-next";
import { RETENTION_TEXT, SHARING } from "../lib/labels";
import type { ConfirmationDto, SharingChoice } from "../types";

const props = defineProps<{ confirmation: ConfirmationDto; busy: boolean }>();
const emit = defineEmits<{ confirm: [summaryHash: string, sharing: SharingChoice, identity: boolean] }>();
const sharing = ref<SharingChoice | null>(null);
const identity = ref(false);
const canName = computed(() => sharing.value === "share_conversation");
function submit() { if (sharing.value) emit("confirm", props.confirmation.summaryHash, sharing.value, canName.value && identity.value); }
</script>

<template>
  <div class="decision pop" role="group" aria-label="Confirm your summary" data-stage="consent">
    <h2>Is this summary right?</h2>
    <p class="hint">{{ RETENTION_TEXT }}</p>
    <blockquote class="quote" :lang="confirmation.language">{{ confirmation.summaryOriginal }}</blockquote>
    <details v-if="confirmation.language !== 'en'"><summary>English translation</summary><blockquote class="quote" lang="en">{{ confirmation.summaryEn }}</blockquote></details>
    <fieldset class="share-opts"><legend>Who may see this case?</legend>
      <label v-for="o in SHARING" :key="o.value" class="share-opt" :class="{ on: sharing === o.value }">
        <input v-model="sharing" type="radio" name="sharing" :value="o.value" /><span><b>{{ o.title }}</b><span class="hint">{{ o.exposes }}</span></span>
      </label>
    </fieldset>
    <label v-if="canName" class="chk"><input v-model="identity" type="checkbox" /> Show my name on the shared case</label>
    <button class="btn primary" type="button" :disabled="busy || !sharing" @click="submit"><ShieldCheck :size="16" aria-hidden="true" /> Confirm summary and finish</button>
    <p class="hint">Confirming sends this account to Fair Trade USA for review. Nothing is shared with other producers until FTUSA approves it.</p>
  </div>
</template>
