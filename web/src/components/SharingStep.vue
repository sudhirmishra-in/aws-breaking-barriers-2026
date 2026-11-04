<script setup lang="ts">
// Confirm the summary and choose sharing. Choices show exactly what each one exposes; identity is a separate, explicit tick.
import { computed, ref } from "vue";
import { ShieldCheck } from "lucide-vue-next";
import { useL } from "../lib/labels";
import type { ConfirmationDto, SharingChoice } from "../types";

const props = defineProps<{ confirmation: ConfirmationDto; busy: boolean }>();
const emit = defineEmits<{ confirm: [summaryHash: string, sharing: SharingChoice, identity: boolean] }>();
const l = useL();
const sharing = ref<SharingChoice | null>(null);
const identity = ref(false);
const canName = computed(() => sharing.value === "share_conversation");
function submit() { if (sharing.value) emit("confirm", props.confirmation.summaryHash, sharing.value, canName.value && identity.value); }
</script>

<template>
  <div class="decision pop" role="group" :aria-label="l.share.title" data-stage="consent">
    <h2>{{ l.share.title }}</h2>
    <p class="hint">{{ l.share.retention }}</p>
    <blockquote class="quote" :lang="confirmation.language">{{ confirmation.summaryOriginal }}</blockquote>
    <details v-if="confirmation.language !== 'en'"><summary>{{ l.share.english }}</summary><blockquote class="quote" lang="en">{{ confirmation.summaryEn }}</blockquote></details>
    <fieldset class="share-opts"><legend>{{ l.share.who }}</legend>
      <label v-for="o in l.sharing" :key="o.value" class="share-opt" :class="{ on: sharing === o.value }">
        <input v-model="sharing" type="radio" name="sharing" :value="o.value" /><span><b>{{ o.title }}</b><span class="hint">{{ o.exposes }}</span></span>
      </label>
    </fieldset>
    <label v-if="canName" class="chk"><input v-model="identity" type="checkbox" /> {{ l.share.name }}</label>
    <button class="btn primary" type="button" :disabled="busy || !sharing" @click="submit"><ShieldCheck :size="16" aria-hidden="true" /> {{ l.share.confirm }}</button>
    <p class="hint">{{ l.share.footer }}</p>
  </div>
</template>
