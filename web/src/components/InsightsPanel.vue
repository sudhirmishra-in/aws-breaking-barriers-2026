<script setup lang="ts">
// Summary and Insights after finalization. Evidence retrieval is not connected in this deployment, so the evidence sections state that limitation
// instead of showing invented findings.
import { computed, ref } from "vue";
import { onMounted } from "vue";
import EvidenceCard from "./EvidenceCard.vue";
import IssueHistory from "./IssueHistory.vue";
import PeerCases from "./PeerCases.vue";
import { api } from "../lib/api";
import { useL } from "../lib/labels";
import type { ApiFailure, ConversationView, EvidenceItem, RecordStateDto } from "../types";

const props = defineProps<{ view: ConversationView }>();
const l = useL();
const emit = defineEmits<{ changed: []; ask: [caseId: string] }>();
const rec = computed<RecordStateDto | null>(() => props.view.record ?? null);
const evidence = ref<EvidenceItem[]>([]); const projects = ref<EvidenceItem[]>([]); const limitation = ref("");
const curated = computed(() => evidence.value.filter((e) => e.curationStatus === "ftusa_curated"));
onMounted(async () => { try { const r = await api.evidence(props.view.conversation.conversationId); evidence.value = r.items; projects.value = r.projects ?? []; limitation.value = r.limitation ? l.value.ins.noEvidence : ""; } catch { limitation.value = l.value.ins.loadFail; } });
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
    <h2>{{ l.ins.title }}</h2>
    <div class="card"><h3>{{ l.ins.confirmed }}</h3>
      <blockquote class="quote" :lang="view.conversation.language">{{ view.conversation.summaryOriginal ?? view.conversation.summaryEn }}</blockquote>
      <p class="hint">{{ l.ins.only }}</p></div>
    <div v-if="rec" class="card"><h3>{{ l.ins.sharingReview }}</h3>
      <dl class="kv"><dt>{{ l.ins.review }}</dt><dd>{{ l.ins.reviewSt[rec.reviewStatus] }}</dd>
        <dt>{{ l.ins.sharingL }}</dt><dd>{{ l.pub[rec.publicationStatus] }}</dd><dt>{{ l.ins.nameShown }}</dt><dd>{{ rec.identityPermitted ? l.ins.yes : l.ins.no }}</dd></dl>
      <div v-if="rec.reconfirmation" class="banner info" role="group" aria-label="Reviewer edit"><p>{{ l.ins.reviewerEdit }}</p>
        <blockquote class="quote">{{ rec.reconfirmation.summaryOriginal }}</blockquote>
        <div class="row"><button class="btn primary sm" :disabled="busy" @click="reconfirm(true)">{{ l.ins.useEdited }}</button><button class="btn sm" :disabled="busy" @click="reconfirm(false)">{{ l.ins.keepOrig }}</button></div></div>
      <div v-if="!rec.deletionRequested" class="row">
        <button v-if="rec.sharingChoice !== 'ftusa_only'" class="btn sm" :disabled="busy" @click="stopSharing">{{ l.ins.stop }}</button>
        <button v-if="rec.identityPermitted" class="btn sm" :disabled="busy" @click="hideName">{{ l.ins.hide }}</button>
        <button v-if="!confirmDelete" class="btn sm" :disabled="busy" @click="confirmDelete = true">{{ l.ins.reqDel }}</button>
        <span v-else role="alertdialog" class="row">{{ l.ins.askDel }} <button class="btn sm danger" :disabled="busy" @click="deletion">{{ l.ins.yesDel }}</button><button class="btn sm" @click="confirmDelete = false">{{ l.info.cancel }}</button></span>
      </div>
      <p v-else class="hint">{{ l.ins.delDone }}</p>
      <p v-if="msg" class="hint" role="status">{{ msg }}</p></div>
    <IssueHistory :conversation-id="view.conversation.conversationId" />
    <div class="card"><h3>{{ l.ins.data }}</h3>
      <EvidenceCard v-for="e in evidence" :key="e.evidenceId" :item="e" />
      <h4 v-if="projects.length" class="ev-sub">{{ l.ins.projects }}</h4>
      <EvidenceCard v-for="e in projects" :key="e.evidenceId" :item="e" />
      <p v-if="!evidence.length && !projects.length" class="hint">{{ limitation || l.loading }}</p></div>
    <div class="card"><h3>{{ l.ins.curated }}</h3>
      <EvidenceCard v-for="e in curated" :key="e.evidenceId" :item="e" />
      <p v-if="!curated.length" class="hint">{{ l.ins.noCurated }}</p></div>
    <PeerCases scope="all" :title="l.ins.others" :related-to="view.conversation.conversationId" @ask="(id) => emit('ask', id)" />
    <div v-if="rec" class="card" role="group" aria-label="Feedback"><h3>{{ l.ins.helpful }}</h3>
      <p v-if="rec.feedback" class="hint" role="status">{{ l.ins.thanksFb.replace("{a}", { yes: l.ins.yes, partly: l.ins.partly, no: l.ins.no }[rec.feedback.helpful]) }}</p>
      <div class="row"><button v-for="o in [['yes', l.ins.yes], ['partly', l.ins.partly], ['no', l.ins.no]] as const" :key="o[0]" class="btn sm" :class="{ primary: rec.feedback?.helpful === o[0] }" :aria-pressed="rec.feedback?.helpful === o[0]" :disabled="fbBusy" @click="sendFeedback(o[0])">{{ o[1] }}</button></div></div>
  </section>
</template>
