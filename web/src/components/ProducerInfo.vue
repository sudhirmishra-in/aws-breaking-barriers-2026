<script setup lang="ts">
// "Your producer information": existing, read-only information. Never a registration or profile-creation form.
// Corrections are proposals reviewed by FTUSA; they do not change the source record.
import { computed, onMounted, ref } from "vue";
import { ChevronDown, Info, Pencil } from "lucide-vue-next";
import { api, newRequestId } from "../lib/api";
import { show, useL } from "../lib/labels";
import { state } from "../session";
import type { ApiFailure, InfoKey, ProducerInfo } from "../types";

const props = defineProps<{ open?: boolean }>();
const l = useL();
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
  const p = info.value.summary.products; return `${p.length ? p.join(", ") : l.value.notProvided} · ${info.value.summary.country ?? l.value.notProvided}`;
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
  if (!changes.length || changes.some((c) => !c.proposed)) { formErr.value = l.value.info.chooseOne; return; }
  busy.value = true;
  try { await api.submitCorrection(formRequestId, changes, why.value.trim() || undefined); done.value = true; correcting.value = false; await load(); }
  catch (e) { formErr.value = (e as ApiFailure).message; } finally { busy.value = false; }
}
defineExpose({ load });
</script>

<template>
  <section class="card pinfo" :aria-label="l.info.title">
    <p v-if="configError" class="banner error" role="alert">{{ configError === "organization_missing" ? l.info.cfgOrg : l.info.cfgProducer }} {{ l.info.support }}</p>
    <p v-else-if="err" class="banner error" role="alert">{{ err }} <button type="button" class="btn sm" @click="load">{{ l.tryAgain }}</button></p>
    <p v-else-if="loading" role="status" class="hint">{{ l.info.loading }}</p>
    <details v-else-if="info" :open="props.open" class="pinfo-d">
      <summary>
        <span class="pinfo-h"><Info :size="15" aria-hidden="true" /> {{ l.info.title }}</span>
        <span class="pinfo-sum">{{ summaryLine }}</span><ChevronDown :size="16" class="pinfo-chev" aria-hidden="true" />
      </summary>
      <div class="pinfo-body">
        <h3>{{ l.info.aboutYou }}</h3>
        <dl class="kv"><dt>{{ l.info.name }}</dt><dd>{{ info.individual.displayName }}</dd><dt>{{ l.info.prefLang }}</dt><dd>{{ l.info.langs[info.individual.preferredLanguage] }}</dd></dl>
        <template v-if="org">
          <h3>{{ l.info.yourOrg }}: {{ org.name }}</h3>
          <p class="hint">{{ l.info.shared }}</p>
          <dl class="kv"><template v-for="k in SHOWN" :key="k"><dt>{{ l.infoLabel[k] }}</dt><dd>{{ show(org.fields[k], l) }}</dd></template></dl>
          <details class="pinfo-ref"><summary>{{ l.info.accountDetails }}</summary><dl class="kv"><dt>{{ l.infoLabel.account_sk }}</dt><dd class="mono">{{ show(org.fields.account_sk, l) }}</dd></dl></details>
        </template>
        <p v-else class="hint">{{ l.info.noOrg }}</p>

        <div v-if="info.pendingCorrections.length" class="pinfo-pending" :aria-label="l.info.corrReqs">
          <h3>{{ l.info.corrReqs }}</h3>
          <p class="hint">{{ l.info.corrHint }}</p>
          <ul class="list"><li v-for="c in info.pendingCorrections" :key="c.correctionId" class="pinfo-corr">
            <span class="pill warn">{{ l.corrStatus[c.status] }}</span>
            <span v-for="ch in c.changes" :key="ch.field"><b>{{ l.infoLabel[ch.field] }}:</b> {{ ch.original ?? l.notProvided }} → {{ ch.proposed }}</span>
            <span v-if="!c.requestedByYou" class="hint">{{ l.info.byColleague }}</span>
          </li></ul>
        </div>

        <p v-if="done" class="banner info" role="status">{{ l.info.thanks }}</p>
        <button v-if="org && !correcting" type="button" class="btn sm" @click="startCorrection"><Pencil :size="13" aria-hidden="true" /> {{ l.info.suggest }}</button>
        <form v-if="correcting && org" class="pinfo-form" @submit.prevent="submit">
          <fieldset><legend>{{ l.info.step1 }}</legend>
            <label v-for="k in info.correctableFields" :key="k" class="chk"><input v-model="picked[k]" type="checkbox" /> {{ l.infoLabel[k] }}</label>
          </fieldset>
          <fieldset v-if="chosen.length"><legend>{{ l.info.step2 }}</legend>
            <div v-for="k in chosen" :key="k" class="fld">
              <span>{{ l.infoLabel[k] }} <span class="hint">({{ l.info.recorded }}: {{ current(k) || l.notProvided }})</span></span>
              <input v-model="proposed[k]" maxlength="300" :aria-label="`${l.info.proposedFor} ${l.infoLabel[k]}`" :placeholder="l.info.proposed" />
            </div>
          </fieldset>
          <label class="fld">{{ l.info.step3 }}<textarea v-model="why" rows="2" maxlength="1000" /></label>
          <p v-if="formErr" class="banner error" role="alert">{{ formErr }}</p>
          <div class="row"><button class="btn primary" type="submit" :disabled="busy">{{ busy ? l.info.sending : l.info.submit }}</button><button class="btn" type="button" @click="correcting = false">{{ l.info.cancel }}</button></div>
          <p class="hint">{{ l.info.cannot }}</p>
        </form>
      </div>
    </details>
  </section>
</template>
