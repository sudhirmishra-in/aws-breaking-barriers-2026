<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";
import { Loader2, Mic, Square, X } from "lucide-vue-next";
import { api, newRequestId } from "../lib/api";
import { MAX_SECONDS, MIN_SECONDS, TARGET_RATE, concat, downsample, seconds, toBase64, toInt16Bytes } from "../lib/audio";
import { markExpired, state } from "../session";
import { t } from "../lib/i18n";
import { ApiFailure, type Lang } from "../types";

const props = defineProps<{ language: Lang; disabled?: boolean }>();
const emit = defineEmits<{ text: [value: string] }>();

const s = computed(() => t(state.ui));
const supported = typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof AudioContext !== "undefined" && typeof AudioWorkletNode !== "undefined";
const phase = ref<"idle" | "requesting" | "recording" | "transcribing">("idle");
const elapsed = ref(0);
const message = ref<{ kind: "error" | "info"; text: string; retry?: () => void } | null>(null);

let ctx: AudioContext | undefined, stream: MediaStream | undefined, node: AudioWorkletNode | undefined, timer: number | undefined;
let chunks: Float32Array[] = [];
let lastAudio: string | undefined;
let attempt = 0; // lets a cancelled permission request be ignored when it eventually settles

function cleanup() {
  window.clearInterval(timer); node?.disconnect(); stream?.getTracks().forEach((tr) => tr.stop()); void ctx?.close();
  node = undefined; stream = undefined; ctx = undefined;
}
onBeforeUnmount(() => { chunks = []; lastAudio = undefined; cleanup(); });

async function start() {
  message.value = null; chunks = []; elapsed.value = 0;
  const mine = ++attempt; phase.value = "requesting";
  let got: MediaStream;
  try {
    got = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
  } catch { if (mine === attempt) { phase.value = "idle"; message.value = { kind: "error", text: s.value.micDenied }; } return; }
  if (mine !== attempt) { got.getTracks().forEach((tr) => tr.stop()); return; } // cancelled while the prompt was open
  stream = got;
  try {
    ctx = new AudioContext();
    await ctx.audioWorklet.addModule("/pcm-worklet.js");
    node = new AudioWorkletNode(ctx, "pcm-capture");
    node.port.onmessage = (e: MessageEvent<Float32Array>) => chunks.push(e.data);
    ctx.createMediaStreamSource(stream).connect(node);
  } catch { cleanup(); phase.value = "idle"; message.value = { kind: "error", text: s.value.micError }; return; }
  phase.value = "recording";
  timer = window.setInterval(() => { elapsed.value += 1; if (elapsed.value >= MAX_SECONDS) void stop(); }, 1000);
}

function cancel() { attempt++; chunks = []; cleanup(); phase.value = "idle"; }

async function stop() {
  const rate = ctx?.sampleRate ?? TARGET_RATE;
  const samples = concat(chunks); chunks = []; cleanup();
  if (seconds(samples.length, rate) < MIN_SECONDS) { phase.value = "idle"; message.value = { kind: "error", text: s.value.micTooShort }; return; }
  lastAudio = toBase64(toInt16Bytes(downsample(samples, rate)));
  await send(newRequestId());
}

async function send(requestId: string) {
  if (!lastAudio) return;
  phase.value = "transcribing"; message.value = null;
  try {
    const { text } = await api.transcribe(requestId, props.language, lastAudio);
    if (!text.trim()) { message.value = { kind: "error", text: s.value.micEmpty }; return; }
    lastAudio = undefined; // the recording is dropped as soon as it has been turned into text
    emit("text", text.trim()); message.value = { kind: "info", text: s.value.micAdded };
  } catch (e) {
    const f = e as ApiFailure;
    if (f.status === 401) markExpired();
    message.value = { kind: "error", text: f.status === 401 ? s.value.expired : f.code === "audio_too_short" ? s.value.micTooShort : s.value.micError, retry: f.retryable ? () => void send(requestId) : undefined };
  } finally { phase.value = "idle"; }
}
</script>

<template>
  <span v-if="supported" class="dictate">
    <button v-if="phase === 'idle'" type="button" class="mic" :disabled="disabled" :aria-label="s.micStart" :title="s.micStart" @click="start"><Mic :size="18" aria-hidden="true" /></button>
    <template v-else-if="phase === 'requesting'">
      <button type="button" class="mic" :aria-label="s.micCancel" :title="s.micCancel" @click="cancel"><X :size="16" aria-hidden="true" /></button>
      <span class="mic-status">{{ s.micAsking }}</span>
    </template>
    <template v-else-if="phase === 'recording'">
      <button type="button" class="mic rec" :aria-label="s.micStop" :title="s.micStop" @click="stop"><Square :size="16" aria-hidden="true" /></button>
      <button type="button" class="mic" :aria-label="s.micCancel" :title="s.micCancel" @click="cancel"><X :size="16" aria-hidden="true" /></button>
    </template>
    <span v-else class="mic" aria-hidden="true"><Loader2 :size="18" class="spin" /></span>
    <span class="sr" role="status" aria-live="polite">{{ phase === "requesting" ? s.micAsking : phase === "recording" ? s.micRecording : phase === "transcribing" ? s.micWorking : message?.text }}</span>
    <span v-if="phase === 'recording'" class="mic-status" aria-hidden="true">● {{ s.micRecording }} {{ Math.floor(elapsed / 60) }}:{{ String(elapsed % 60).padStart(2, "0") }}</span>
    <span v-else-if="phase === 'transcribing'" class="mic-status" aria-hidden="true">{{ s.micWorking }}</span>
  </span>
  <p v-if="supported && message && phase === 'idle'" class="mic-msg" :class="message.kind" role="alert">
    {{ message.text }} <button v-if="message.retry" type="button" class="btn sm" @click="message.retry()">{{ s.retry }}</button>
  </p>
</template>
