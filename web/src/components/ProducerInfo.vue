<script setup lang="ts">
// "Your producer information": existing, read-only information. Never a registration or profile-creation form.
// Corrections are proposals reviewed by FTUSA; they do not change the source record.
import { computed, onMounted, ref } from "vue";
import { ChevronDown, Info, Pencil } from "lucide-vue-next";
import { api, newRequestId } from "../lib/api";
import { CORRECTION_STATUS, INFO_LABEL, NOT_PROVIDED, show } from "../lib/labels";
import { state } from "../session";
import type { ApiFailure, InfoKey, ProducerInfo } from "../types";

const props = defineProps<{ open?: boolean }>();
const info = ref<ProducerInfo | null>(null);
const err = ref("");
const loading = ref(true);
const correcting = ref(false);
const picked = ref<Record<string, boolean>>({});
const proposed = ref<Record<string, string>>({});
const why = ref("");
const busy = ref(false);
const formErr = ref("");
const done = ref(false);
let formRequestId = newRequestId(); // one id per form session so a retry is de-duplicated

const configError = computed(() => state.me?.configurationError);
const org = computed(() => info.value?.organization);
const summaryLine = computed(() => {
  if (!info.value) return "";
  const p = info.value.summary.products; return `${p.length ? p.join(", ") : NOT_PROVIDED} · ${info.value.summary.country ?? NOT_PROVIDED}`;
});
const SHOWN: InfoKey[] = ["account_category_name", "product_category_name", "account_type_name", "certification_scope_name", "certification_status_name", "country_name", "raw_supply_chain_role_txt", "structure_txt"];
const current = (k: InfoKey) => { const v = org.value?.fields[k]; return Array.isArray(v) ? v.join("; ") : v ?? ""; };
const chosen = computed(() => (info.value?.correctableFields ?? []).filter((k) => picked.value[k]));

async function load() {
  loading.value = true; err.value = "";
  try { info.value = await api.producerInfo(); } catch (e) { err.value = (e as ApiFailure).message; } finally { loading.value = false; }
}
onMounted(() => { if (!configError.value) void load(); else loading.value = false; });
function startCorrection() { correcting.value = true; done.value = false; formErr.value = ""; picked.value = {}; proposed.value = {}; why.value = ""; formRequestId = newRequestId(); }
async function submit() {
  formErr.value = "";
  const changes = chosen.value.map((field) => ({ field, proposed: (proposed.value[field] ?? "").trim() }));
  if (!changes.length || changes.some((c) => !c.proposed)) { formErr.value = "Choose at least one field and enter the proposed value for each."; return; }
  busy.value = true;
  try { await api.submitCorrection(formRequestId, changes, why.value.trim() || undefined); done.value = true; correcting.value = false; await load(); }
  catch (e) { formErr.value = (e as ApiFailure).message; } finally { busy.value = false; }
}
defineExpose({ load });
</script>

<template>
  <section class="card pinfo" aria-label="Your producer information">
    <p v-if="configError" class="banner error" role="alert">This account is not linked to a producer. Please contact Fair Trade USA support; no producer information can be shown.</p>
    <p v-else-if="err" class="banner error" role="alert">{{ err }} <button type="button" class="btn sm" @click="load">Try again</button></p>
    <p v-else-if="loading" role="status" class="hint">Loading your producer information…</p>
    <details v-else-if="info" :open="props.open" class="pinfo-d">
      <summary>
        <span class="pinfo-h"><Info :size="15" aria-hidden="true" /> Your producer information</span>
        <span class="pinfo-sum">{{ summaryLine }}</span><ChevronDown :size="16" class="pinfo-chev" aria-hidden="true" />
      </summary>
      <div class="pinfo-body">
        <h3>About you</h3>
        <dl class="kv"><dt>Name</dt><dd>{{ info.individual.displayName }}</dd><dt>Preferred language</dt><dd>{{ { en: "English", es: "Spanish", fr: "French" }[info.individual.preferredLanguage] }}</dd></dl>
        <template v-if="org">
          <h3>Your organization: {{ org.name }}</h3>
          <p class="hint">Shared by everyone in your organization. This is the information on record, not something you set up here.</p>
          <dl class="kv"><template v-for="k in SHOWN" :key="k"><dt>{{ INFO_LABEL[k] }}</dt><dd>{{ show(org.fields[k]) }}</dd></template></dl>
          <details class="pinfo-ref"><summary>Account details</summary><dl class="kv"><dt>{{ INFO_LABEL.account_sk }}</dt><dd class="mono">{{ show(org.fields.account_sk) }}</dd></dl></details>
        </template>
        <p v-else class="hint">No organization information is on record for this account.</p>

        <div v-if="info.pendingCorrections.length" class="pinfo-pending" aria-label="Pending correction requests">
          <h3>Correction requests</h3>
          <p class="hint">These are suggestions waiting for Fair Trade USA. They are not verified facts and do not change the information above yet.</p>
          <ul class="list"><li v-for="c in info.pendingCorrections" :key="c.correctionId" class="pinfo-corr">
            <span class="pill warn">{{ CORRECTION_STATUS[c.status] }}</span>
            <span v-for="ch in c.changes" :key="ch.field"><b>{{ INFO_LABEL[ch.field] }}:</b> {{ ch.original ?? NOT_PROVIDED }} → {{ ch.proposed }}</span>
            <span v-if="!c.requestedByYou" class="hint">Requested by a colleague</span>
          </li></ul>
        </div>

        <p v-if="done" class="banner info" role="status">Thank you. Your correction request was sent to Fair Trade USA for review. The information above has not changed.</p>
        <button v-if="org && !correcting" type="button" class="btn sm" @click="startCorrection"><Pencil :size="13" aria-hidden="true" /> Suggest a correction</button>
        <form v-if="correcting && org" class="pinfo-form" @submit.prevent="submit">
          <fieldset><legend>1. Which information needs correcting?</legend>
            <label v-for="k in info.correctableFields" :key="k" class="chk"><input v-model="picked[k]" type="checkbox" /> {{ INFO_LABEL[k] }}</label>
          </fieldset>
          <fieldset v-if="chosen.length"><legend>2. Recorded value and your proposed value</legend>
            <div v-for="k in chosen" :key="k" class="fld">
              <span>{{ INFO_LABEL[k] }} <span class="hint">(recorded: {{ current(k) || NOT_PROVIDED }})</span></span>
              <input v-model="proposed[k]" maxlength="300" :aria-label="`Proposed ${INFO_LABEL[k]}`" placeholder="Proposed value" />
            </div>
          </fieldset>
          <label class="fld">3. Anything else we should know? (optional)<textarea v-model="why" rows="2" maxlength="1000" /></label>
          <p v-if="formErr" class="banner error" role="alert">{{ formErr }}</p>
          <div class="row"><button class="btn primary" type="submit" :disabled="busy">{{ busy ? "Sending…" : "Submit correction" }}</button><button class="btn" type="button" @click="correcting = false">Cancel</button></div>
          <p class="hint">Account references, organization membership and permissions cannot be changed here.</p>
        </form>
      </div>
    </details>
  </section>
</template>
