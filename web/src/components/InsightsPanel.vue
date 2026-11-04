<script setup lang="ts">
// Summary and Insights after finalization. Evidence retrieval is not connected in this deployment, so the evidence sections state that limitation
// instead of showing invented findings.
import { computed, ref } from "vue";
import { onMounted } from "vue";
import EvidenceCard from "./EvidenceCard.vue";
import PeerCases from "./PeerCases.vue";
import { api } from "../lib/api";
import { PUBLICATION_STATUS } from "../lib/labels";
import type { ApiFailure, ConversationView, EvidenceItem, RecordStateDto } from "../types";

const props = defineProps<{ view: ConversationView }>();
const emit = defineEmits<{ changed: []; ask: [caseId: string] }>();
const rec = computed<RecordStateDto | null>(() => props.view.record ?? null);
const evidence = ref<EvidenceItem[]>([]); const projects = ref<EvidenceItem[]>([]); const limitation = ref("");
const curated = computed(() => evidence.value.filter((e) => e.curationStatus === "ftusa_curated"));
onMounted(async () => { try { const r = await api.evidence(props.view.conversation.conversationId); evidence.value = r.items; projects.value = r.projects ?? []; limitation.value = r.limitation ?? ""; } catch { limitation.value = "Evidence could not be loaded just now."; } });
const msg = ref(""); const busy = ref(false); const confirmDelete = ref(false);
async function act(fn: () => Promise<unknown>) { busy.value = true; msg.value = ""; try { await fn(); emit("changed"); } catch (e) { msg.value = (e as ApiFailure).message; } finally { busy.value = false; } }
const fbBusy = ref(false);
async function sendFeedback(h: "yes" | "partly" | "no") { fbBusy.value = true; msg.value = ""; try { await api.feedback(props.view.conversation.conversationId, h); emit("changed"); } catch (e) { msg.value = (e as ApiFailure).message; } finally { fbBusy.value = false; } }
const stopSharing = () => act(() => api.updateSharing(props.view.conversation.conversationId, "ftusa_only", false));
const hideName = () => act(() => api.updateSharing(props.view.conversation.conversationId, "share_conversation", false));
const reconfirm = (accept: boolean) => act(() => api.reconfirm(props.view.conversation.conversationId, rec.value!.reconfirmation!.summaryHash, accept));
const deletion = () => act(async () => { const r = await api.requestDeletion(props.view.conversation.conversationId); msg.value = r.note; confirmDelete.value = false; });
</script>

<template>
  <section class="insights" aria-label="Summary and insights">
    <h2>Summary and insights</h2>
    <div class="card"><h3>Your confirmed summary</h3>
      <blockquote class="quote" :lang="view.conversation.language">{{ view.conversation.summaryOriginal ?? view.conversation.summaryEn }}</blockquote>
      <p class="hint">This is only your own confirmed account. Anything below that comes from outside is kept separate.</p></div>
    <div v-if="rec" class="card"><h3>Sharing and review</h3>
      <dl class="kv"><dt>Fair Trade USA review</dt><dd>{{ { pending: "Waiting for review", approved: "Approved", corrected: "Reviewed with edits" }[rec.reviewStatus] }}</dd>
        <dt>Sharing</dt><dd>{{ PUBLICATION_STATUS[rec.publicationStatus] }}</dd><dt>Name shown</dt><dd>{{ rec.identityPermitted ? "Yes" : "No" }}</dd></dl>
      <div v-if="rec.reconfirmation" class="banner info" role="group" aria-label="Reviewer edit"><p>A reviewer suggests this wording. It is shared only if you agree.</p>
        <blockquote class="quote">{{ rec.reconfirmation.summaryOriginal }}</blockquote>
        <div class="row"><button class="btn primary sm" :disabled="busy" @click="reconfirm(true)">Use the edited wording</button><button class="btn sm" :disabled="busy" @click="reconfirm(false)">Keep my original</button></div></div>
      <div v-if="!rec.deletionRequested" class="row">
        <button v-if="rec.sharingChoice !== 'ftusa_only'" class="btn sm" :disabled="busy" @click="stopSharing">Stop sharing with other producers</button>
        <button v-if="rec.identityPermitted" class="btn sm" :disabled="busy" @click="hideName">Hide my name</button>
        <button v-if="!confirmDelete" class="btn sm" :disabled="busy" @click="confirmDelete = true">Request deletion</button>
        <span v-else role="alertdialog" class="row">Ask Fair Trade USA to delete this record? <button class="btn sm danger" :disabled="busy" @click="deletion">Yes, request deletion</button><button class="btn sm" @click="confirmDelete = false">Cancel</button></span>
      </div>
      <p v-else class="hint">Deletion requested. This case is no longer shared.</p>
      <p v-if="msg" class="hint" role="status">{{ msg }}</p></div>
    <div class="card"><h3>What the data shows</h3>
      <EvidenceCard v-for="e in evidence" :key="e.evidenceId" :item="e" />
      <h4 v-if="projects.length" class="ev-sub">Similar project records from public source data</h4>
      <EvidenceCard v-for="e in projects" :key="e.evidenceId" :item="e" />
      <p v-if="!evidence.length && !projects.length" class="hint">{{ limitation || "Loading…" }}</p></div>
    <div class="card"><h3>Information curated by Fair Trade USA</h3>
      <EvidenceCard v-for="e in curated" :key="e.evidenceId" :item="e" />
      <p v-if="!curated.length" class="hint">Nothing curated by Fair Trade USA is available for this case yet.</p></div>
    <PeerCases scope="all" title="What others have done" :related-to="view.conversation.conversationId" @ask="(id) => emit('ask', id)" />
    <div v-if="rec" class="card" role="group" aria-label="Feedback"><h3>Was this helpful?</h3>
      <p v-if="rec.feedback" class="hint" role="status">Thank you. You answered: {{ { yes: "Yes", partly: "Partly", no: "No" }[rec.feedback.helpful] }}. You can change your answer.</p>
      <div class="row"><button v-for="o in [['yes', 'Yes'], ['partly', 'Partly'], ['no', 'No']] as const" :key="o[0]" class="btn sm" :class="{ primary: rec.feedback?.helpful === o[0] }" :aria-pressed="rec.feedback?.helpful === o[0]" :disabled="fbBusy" @click="sendFeedback(o[0])">{{ o[1] }}</button></div></div>
  </section>
</template>
