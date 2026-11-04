<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { AlertTriangle, Check, ClipboardCheck, Pencil, RefreshCw, Search, X } from "lucide-vue-next";
import { api } from "../lib/api";
import { state } from "../session";
import { t } from "../lib/i18n";
import { ApiFailure, CHALLENGE_TAGS, type ChallengeTag, type RelatedData, type ReviewProducer, type ReviewRecord, type ReviewStats } from "../types";

// Reviewer screen (REV-01..REV-24): stats bar, producers + their existing data, and the selected producer's records.
// Every call is authorised server-side; the filters live in the URL so a view can be shared or reloaded.
const s = computed(() => t(state.ui));
const rv = computed(() => s.value.rv);
const route = useRoute(); const router = useRouter();
const fmt = (str: string, v: Record<string, string | number>) => str.replace(/\{(\w+)\}/g, (_, k) => String(v[k] ?? ""));
const tagName = (k: string) => (s.value.tagNames as Record<string, string>)[k] ?? k;
const entityName = (k: string | null) => (k ? (s.value.entity as Record<string, string>)[k] ?? k : "");
const when = (iso: string) => new Date(iso).toLocaleString(state.ui, { dateStyle: "medium", timeStyle: "short" });

// ---------- filters (URL query)
const producerId = computed(() => (route.params.producerId as string | undefined) ?? null);
const q = ref((route.query.q as string) ?? "");
const status = computed(() => (route.query.status as string) ?? "pending");
const outcome = computed(() => (route.query.outcome as string) ?? "all");
const piiOnly = computed(() => route.query.pii === "true");
function setQuery(patch: Record<string, string | undefined>) {
  const next = { ...route.query, ...patch };
  for (const k of Object.keys(next)) if (next[k] === undefined || next[k] === "") delete next[k];
  router.replace({ path: route.path, query: next });
}
let qTimer: ReturnType<typeof setTimeout> | undefined;
watch(q, (v) => { clearTimeout(qTimer); qTimer = setTimeout(() => setQuery({ q: v.trim() || undefined }), 250); });

// ---------- data
const stats = ref<ReviewStats | null>(null);
const producers = ref<ReviewProducer[]>([]);
const records = ref<ReviewRecord[]>([]);
const related = ref<RelatedData | null>(null);
const err = ref(""); const loaded = ref(false); const lastAt = ref(Date.now()); const now = ref(Date.now());
const relTab = ref<"projects" | "surveys" | "cert">("projects");
const recId = computed(() => (route.query.rec as string | undefined) ?? records.value[0]?.recordId ?? null);
const rec = computed(() => records.value.find((r) => r.recordId === recId.value) ?? null);
const current = computed(() => producers.value.find((p) => p.producerId === producerId.value) ?? (rec.value && { producerName: rec.value.producerName }) ?? null);

async function loadList() {
  const [st, pr] = await Promise.all([api.reviewStats(), api.reviewProducers({ review_status: status.value, outcome: outcome.value, pii_only: String(piiOnly.value), ...(route.query.q ? { q: String(route.query.q) } : {}) })]);
  stats.value = st; producers.value = pr.items;
}
async function loadProducer() {
  if (!producerId.value) { records.value = []; related.value = null; return; }
  const [r, rel] = await Promise.all([api.producerRecords(producerId.value), api.related(producerId.value)]);
  records.value = r.items; related.value = rel;
}
async function refresh(all = true) {
  err.value = "";
  try { await Promise.all([loadList(), all ? loadProducer() : Promise.resolve()]); lastAt.value = Date.now(); }
  catch (e) { err.value = (e as Error).message; }
  finally { loaded.value = true; }
}
watch(() => [route.query.q, route.query.status, route.query.outcome, route.query.pii], () => refresh(false));
watch(producerId, () => { editing.value = false; refresh(true); });

// ---------- live refresh, skipped while the reviewer is editing
let poll: ReturnType<typeof setInterval> | undefined; let tick: ReturnType<typeof setInterval> | undefined;
onMounted(() => {
  refresh(true);
  poll = setInterval(() => { if (!editing.value && !busy.value && document.visibilityState === "visible") refresh(true); }, 15_000);
  tick = setInterval(() => (now.value = Date.now()), 1000);
});
onUnmounted(() => { clearInterval(poll); clearInterval(tick); clearTimeout(qTimer); });
const ago = computed(() => Math.max(0, Math.round((now.value - lastAt.value) / 1000)));

function pickProducer(id: string) { router.push({ path: `/review/${encodeURIComponent(id)}`, query: { ...route.query, rec: undefined } }); }
function pickRecord(id: string) { editing.value = false; setQuery({ rec: id }); }

// ---------- review actions
const editing = ref(false); const busy = ref(false); const actionErr = ref("");
const draft = ref({ orig: "", en: "", tags: [] as ChallengeTag[], note: "" });
function startEdit() {
  const r = rec.value!; actionErr.value = "";
  draft.value = { orig: r.summaryOriginal ?? "", en: r.summaryEn ?? "", tags: [...(r.challengeTags ?? [])], note: r.reviewerNote ?? "" };
  editing.value = true;
}
function toggleTag(k: ChallengeTag) {
  if (!editing.value) return;
  const i = draft.value.tags.indexOf(k); if (i >= 0) draft.value.tags.splice(i, 1); else draft.value.tags.push(k);
}
const shownTags = computed<ChallengeTag[]>(() => (editing.value ? draft.value.tags : rec.value?.challengeTags ?? []));
const changedTag = (k: ChallengeTag) => {
  const agent = rec.value?.agentChallengeTags ?? [];
  return shownTags.value.includes(k) !== agent.includes(k);
};
async function decide(kind: "approved" | "corrected") {
  const r = rec.value!; actionErr.value = "";
  const body: Parameters<typeof api.patchRecord>[1] = { review_status: kind };
  if (kind === "corrected") {
    const d = draft.value;
    if (d.orig.trim() !== (r.summaryOriginal ?? "")) body.summary_original = d.orig.trim();
    if (d.en.trim() !== (r.summaryEn ?? "")) body.summary_en = d.en.trim();
    const before = [...(r.challengeTags ?? [])].sort().join(), after = [...d.tags].sort().join();
    if (before !== after) body.challenge_tags = [...d.tags];
    if (d.note.trim() !== (r.reviewerNote ?? "")) body.reviewer_note = d.note.trim();
    if (Object.keys(body).length === 1) { actionErr.value = rv.value.mustChange; return; }
  }
  busy.value = true;
  try {
    const updated = await api.patchRecord(r.recordId, body);
    records.value = records.value.map((x) => (x.recordId === updated.recordId ? updated : x));
    editing.value = false;
    await loadList(); lastAt.value = Date.now();
  } catch (e) {
    const f = e as ApiFailure;
    if (f.status === 409) { actionErr.value = rv.value.conflict; editing.value = false; await loadProducer(); }
    else actionErr.value = f.message;
  } finally { busy.value = false; }
}
const statusCls = (st: ReviewRecord["reviewStatus"]) => (st === "pending" ? "warn" : st ? "ok" : "");
const statusLabel = (r: ReviewRecord) => (r.reviewStatus ? rv.value.stats[r.reviewStatus] : rv.value.outcomes[r.outcome]);
const statKeys = ["pending", "approved", "corrected", "declined", "piiFlagged", "conversationsToday"] as const;
</script>

<template>
  <div class="rv">
    <div class="rv-head">
      <h1 class="page-title"><ClipboardCheck :size="22" aria-hidden="true" style="vertical-align:-3px" /> {{ rv.title }}</h1>
      <span class="rv-live" aria-live="polite"><span class="rv-dot" aria-hidden="true"></span>{{ rv.live }} · {{ fmt(rv.updated, { n: ago }) }}</span>
      <button class="btn sm" type="button" :disabled="busy" @click="refresh(true)"><RefreshCw :size="14" aria-hidden="true" />{{ rv.refresh }}</button>
    </div>

    <!-- REV-01 stats bar -->
    <div class="rv-stats" role="list">
      <div v-for="k in statKeys" :key="k" class="tile rv-stat" :class="{ 'rv-stat-warn': k === 'pending' || k === 'piiFlagged' }" role="listitem">
        <b>{{ stats ? stats[k] : "–" }}</b><span>{{ rv.stats[k] }}</span>
      </div>
    </div>

    <!-- REV-02/03 search and filters -->
    <div class="rv-tools">
      <label class="rv-search"><Search :size="16" aria-hidden="true" /><span class="sr-only">{{ rv.search }}</span>
        <input v-model="q" type="search" :placeholder="rv.search" /></label>
      <div class="seg" role="group" :aria-label="rv.fStatus">
        <button v-for="st in ['pending', 'approved', 'corrected', 'all']" :key="st" type="button" :aria-pressed="status === st" @click="setQuery({ status: st === 'pending' ? undefined : st })">
          {{ st === "all" ? rv.fAll : rv.stats[st as "pending"] }}</button>
      </div>
      <label class="sr-only" for="rv-outcome">{{ rv.fOutcome }}</label>
      <select id="rv-outcome" class="sel" :value="outcome" @change="setQuery({ outcome: ($event.target as HTMLSelectElement).value === 'all' ? undefined : ($event.target as HTMLSelectElement).value })">
        <option v-for="(label, k) in rv.outcomes" :key="k" :value="k">{{ label }}</option>
      </select>
      <label class="rv-check"><input type="checkbox" :checked="piiOnly" @change="setQuery({ pii: ($event.target as HTMLInputElement).checked ? 'true' : undefined })" />{{ rv.piiOnly }}</label>
    </div>

    <p v-if="err" role="alert" class="banner error">{{ err }}</p>
    <p v-if="loaded && stats && stats.pending + stats.approved + stats.corrected + stats.declined === 0" class="card rv-empty">{{ rv.empty }}</p>

    <div v-else class="rv-grid">
      <!-- REV-04..07 producers and their existing data -->
      <section class="rv-left">
        <div class="card rv-producers">
          <h2>{{ rv.producers }}</h2>
          <p v-if="loaded && !producers.length" class="muted">{{ rv.noMatch }}</p>
          <ul class="rv-plist">
            <li v-for="p in producers" :key="p.producerId">
              <button type="button" class="rv-p" :class="{ on: p.producerId === producerId }" :aria-current="p.producerId === producerId ? 'true' : undefined" @click="pickProducer(p.producerId)">
                <span class="rv-p-top"><strong>{{ p.producerName }}</strong>
                  <span v-if="p.piiFlag" class="pill err">PII</span>
                  <span v-if="p.pendingCount" class="pill warn">{{ fmt(rv.nPending, { n: p.pendingCount }) }}</span></span>
                <span class="rv-p-meta">{{ [entityName(p.entityType), p.crop, p.location, fmt(rv.nRecords, { n: p.recordCount })].filter(Boolean).join(" · ") }}</span>
              </button>
            </li>
          </ul>
        </div>

        <div v-if="related" class="card rv-related">
          <h2>{{ rv.existing }}</h2>
          <p class="rv-src">{{ related.source }}</p>
          <div class="rv-tabs" role="tablist">
            <button v-for="k in (['projects', 'surveys', 'cert'] as const)" :key="k" type="button" role="tab" :aria-selected="relTab === k" @click="relTab = k">{{ rv.tabs[k] }}</button>
          </div>
          <div role="tabpanel">
            <template v-if="relTab === 'projects'">
              <p v-if="!related.premiumProjects.length" class="muted">{{ rv.noRows }}</p>
              <ul class="rv-rows"><li v-for="(r, i) in related.premiumProjects" :key="i">
                <strong>{{ r.year }} · {{ r.title }}</strong>
                <span>USD {{ r.amountUsd.toLocaleString() }} · {{ r.status }}<template v-if="r.outcome"> · {{ r.outcome }}</template></span>
                <span class="rv-chips"><span v-for="tg in r.tags" :key="tg" class="pill">{{ tagName(tg) }}</span></span></li></ul>
            </template>
            <template v-else-if="relTab === 'surveys'">
              <p v-if="!related.surveys.length" class="muted">{{ rv.noRows }}</p>
              <ul class="rv-rows"><li v-for="(r, i) in related.surveys" :key="i">
                <strong>{{ r.year }}<template v-if="r.topConcern"> · {{ tagName(r.topConcern) }}</template></strong>
                <span>{{ r.respondents }} {{ rv.respondents }} · {{ r.incomeChangePct > 0 ? "+" : "" }}{{ r.incomeChangePct }}% {{ rv.income }} · {{ r.lowerYieldPct }}% {{ rv.lowerYield }}</span></li></ul>
            </template>
            <template v-else>
              <p v-if="!related.certification.length" class="muted">{{ rv.noRows }}</p>
              <ul class="rv-rows"><li v-for="(r, i) in related.certification" :key="i">
                <strong>{{ r.standard }} {{ r.version }}</strong><span>{{ r.status }} · {{ rv.lastAudit }} {{ r.lastAudit }}</span></li></ul>
            </template>
          </div>
        </div>
      </section>

      <!-- REV-08..24 records of the selected producer -->
      <section class="rv-right">
        <div v-if="!producerId" class="card muted">{{ rv.pickProducer }}</div>
        <template v-else>
          <h2 class="rv-conv-title">{{ fmt(rv.conversationsFrom, { name: current?.producerName ?? producerId }) }}</h2>
          <div class="rv-rtabs" role="tablist">
            <button v-for="r in records" :key="r.recordId" type="button" role="tab" :aria-selected="r.recordId === recId" @click="pickRecord(r.recordId)">
              <span class="rv-rid">{{ r.recordId }}</span>
              <span class="rv-rdate">{{ new Date(r.createdAt).toLocaleDateString(state.ui) }}</span>
              <span class="pill" :class="statusCls(r.reviewStatus)">{{ statusLabel(r) }}</span>
            </button>
          </div>

          <article v-if="rec" class="card rv-rec">
            <header class="rv-rec-hd">
              <h3>{{ rec.recordId }}</h3>
              <span class="pill" :class="statusCls(rec.reviewStatus)">{{ statusLabel(rec) }}</span>
              <span class="pill">{{ rv.outcomes[rec.outcome] }}</span>
              <span class="pill">{{ rec.language.toUpperCase() }}</span>
              <span v-if="rec.peerExampleOk" class="pill ok">{{ rv.peerOk }}</span>
            </header>
            <p class="rv-meta">{{ rv.source }} · {{ when(rec.createdAt) }} · {{ [rec.producerName, entityName(rec.entityType), rec.crop, rec.location].filter(Boolean).join(" · ") }}</p>

            <p v-if="rec.outcome === 'declined'" class="muted">{{ rv.declinedText }}</p>
            <template v-else>
              <div v-if="rec.piiFlag" class="rv-pii" role="note">
                <AlertTriangle :size="18" aria-hidden="true" />
                <div><strong>{{ rv.piiTitle }}</strong><p>{{ fmt(rv.piiText, { types: (rec.piiEntityTypes ?? []).join(", ") || "—" }) }}</p></div>
              </div>

              <div class="rv-sums">
                <div><h4>{{ rv.origSummary }} ({{ rec.language.toUpperCase() }})</h4>
                  <textarea v-if="editing" v-model="draft.orig" rows="5" :aria-label="rv.origSummary"></textarea>
                  <p v-else>{{ rec.summaryOriginal || "—" }}</p></div>
                <div><h4>{{ rv.enSummary }}</h4>
                  <textarea v-if="editing" v-model="draft.en" rows="5" :aria-label="rv.enSummary"></textarea>
                  <p v-else>{{ rec.summaryEn || "—" }}</p></div>
              </div>

              <h4>{{ rv.tags }}</h4>
              <div class="rv-tagchips">
                <button v-for="k in CHALLENGE_TAGS" v-show="editing || shownTags.includes(k)" :key="k" type="button" class="rv-tag"
                  :class="{ on: shownTags.includes(k), changed: changedTag(k) }" :aria-pressed="shownTags.includes(k)" :disabled="!editing" @click="toggleTag(k)">
                  {{ tagName(k) }}<span v-if="changedTag(k)" class="rv-tag-note">· {{ rv.tagChanged }}</span>
                </button>
                <span v-if="!editing && !shownTags.length" class="muted">—</span>
              </div>
              <p v-if="(rec.agentChallengeTags ?? []).length" class="rv-small">{{ rv.agentTagged }}: {{ (rec.agentChallengeTags ?? []).map(tagName).join(", ") }}</p>

              <div class="rv-cols">
                <div><h4>{{ rv.claims }}</h4><p class="muted">{{ rv.noClaims }}</p></div>
                <div><h4>{{ rv.feedback }}</h4><p class="muted">{{ rec.feedbackHelpful ?? rv.noFeedback }}</p></div>
                <div><h4>{{ rv.reasoning }}</h4><p class="muted">{{ rec.reasoningLogRef ?? rv.notRecorded }}</p></div>
              </div>

              <h4>{{ rv.note }}</h4>
              <textarea v-if="editing" v-model="draft.note" rows="2" :placeholder="rv.notePh" :aria-label="rv.note"></textarea>
              <p v-else class="muted">{{ rec.reviewerNote || "—" }}</p>

              <p v-if="actionErr" role="alert" class="banner error">{{ actionErr }}</p>
              <div class="rv-actions">
                <template v-if="rec.reviewStatus === 'pending'">
                  <template v-if="!editing">
                    <button class="btn primary" type="button" :disabled="busy" @click="decide('approved')"><Check :size="16" aria-hidden="true" />{{ rv.approve }}</button>
                    <button class="btn" type="button" :disabled="busy" @click="startEdit"><Pencil :size="16" aria-hidden="true" />{{ rv.edit }}</button>
                  </template>
                  <template v-else>
                    <button class="btn primary" type="button" :disabled="busy" @click="decide('corrected')"><Check :size="16" aria-hidden="true" />{{ rv.saveCorr }}</button>
                    <button class="btn" type="button" :disabled="busy" @click="editing = false"><X :size="16" aria-hidden="true" />{{ rv.cancel }}</button>
                  </template>
                </template>
                <p v-else-if="rec.reviewedAt" class="rv-small">{{ rec.reviewedBy ? fmt(rv.reviewedBy, { name: rec.reviewedBy, time: when(rec.reviewedAt) }) : fmt(rv.reviewedAt, { time: when(rec.reviewedAt) }) }}</p>
              </div>
            </template>
          </article>
        </template>
      </section>
    </div>
  </div>
</template>

<style scoped>
.rv-head { display:flex; align-items:center; gap:.75rem; flex-wrap:wrap; margin-top:1rem; } .rv-head .page-title { margin:0; flex:1; }
.rv-live { display:inline-flex; align-items:center; gap:.4rem; font-size:.8rem; color:var(--muted); }
.rv-dot { width:.5rem; height:.5rem; border-radius:99px; background:var(--lime); box-shadow:0 0 0 3px color-mix(in srgb,var(--lime) 30%,transparent); }
.rv-stats { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:.6rem; margin:1rem 0; }
.rv-stat { display:flex; flex-direction:column; gap:.15rem; padding:.75rem .9rem; } .rv-stat b { font-size:1.5rem; color:var(--brand); } .rv-stat span { font-size:.78rem; color:var(--muted); }
.rv-stat-warn { border-left:4px solid var(--lime); }
.rv-tools { display:flex; flex-wrap:wrap; gap:.6rem; align-items:center; margin-bottom:1rem; } .rv-tools .seg { margin:0; max-width:100%; flex-wrap:wrap; box-sizing:border-box; }
.rv-search { flex:1 1 18rem; display:flex; align-items:center; gap:.45rem; border:1px solid var(--border); border-radius:999px; padding:.35rem .9rem; background:var(--surface); color:var(--muted); }
.rv-search input { flex:1; border:0; outline:0; background:transparent; font:inherit; font-size:.9rem; color:var(--fg); min-width:0; }
.rv-search:focus-within { border-color:var(--brand); }
.rv-check { display:inline-flex; align-items:center; gap:.4rem; font-size:.85rem; }
.rv-grid { display:grid; grid-template-columns:minmax(17rem,22rem) 1fr; gap:1rem; align-items:start; }
.rv-left { display:flex; flex-direction:column; gap:1rem; }
.rv-producers h2, .rv-related h2 { font-size:1rem; }
.rv-plist { list-style:none; margin:.4rem 0 0; padding:0; max-height:24rem; overflow-y:auto; display:flex; flex-direction:column; gap:.35rem; }
.rv-p { width:100%; text-align:left; border:1px solid var(--border); background:var(--surface); border-radius:6px; padding:.6rem .7rem; cursor:pointer; font:inherit; color:var(--fg); display:flex; flex-direction:column; gap:.2rem; }
.rv-p:hover { background:var(--surface-2); } .rv-p.on { border-color:var(--brand); box-shadow:inset 4px 0 0 var(--lime); background:var(--surface-2); }
.rv-p-top { display:flex; gap:.35rem; align-items:center; flex-wrap:wrap; font-size:.9rem; } .rv-p-top strong { flex:1; min-width:8rem; }
.rv-p-meta { font-size:.75rem; color:var(--muted); }
.rv-src { font-size:.75rem; color:var(--muted); margin:.1rem 0 .5rem; }
.rv-tabs, .rv-rtabs { display:flex; gap:.25rem; border-bottom:1px solid var(--border); overflow-x:auto; }
.rv-tabs button, .rv-rtabs button { border:0; background:none; font:inherit; font-size:.82rem; color:var(--muted); padding:.5rem .7rem; cursor:pointer; border-bottom:3px solid transparent; white-space:nowrap; }
.rv-tabs button[aria-selected=true], .rv-rtabs button[aria-selected=true] { color:var(--fg); border-bottom-color:var(--lime); font-weight:600; }
.rv-rtabs button { display:flex; flex-direction:column; align-items:flex-start; gap:.15rem; }
.rv-rid { font-family:ui-monospace,monospace; font-size:.75rem; } .rv-rdate { font-size:.72rem; }
.rv-rows { list-style:none; margin:.5rem 0 0; padding:0; display:flex; flex-direction:column; gap:.55rem; max-height:20rem; overflow-y:auto; }
.rv-rows li { display:flex; flex-direction:column; gap:.15rem; font-size:.82rem; border-bottom:1px dashed var(--border); padding-bottom:.45rem; } .rv-rows span { color:var(--muted); }
.rv-chips { display:flex; flex-wrap:wrap; gap:.25rem; }
.rv-conv-title { font-size:1.05rem; margin:0 0 .4rem; }
.rv-rec { margin-top:.75rem; } .rv-rec h4 { font-size:.85rem; margin:1rem 0 .35rem; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); }
.rv-rec-hd { display:flex; align-items:center; gap:.4rem; flex-wrap:wrap; } .rv-rec-hd h3 { margin:0 .4rem 0 0; font-family:ui-monospace,monospace; font-size:.95rem; }
.rv-meta { font-size:.78rem !important; }
.rv-pii { display:flex; gap:.6rem; margin-top:.8rem; padding:.7rem .85rem; border:1px solid color-mix(in srgb,var(--err) 40%,transparent); background:color-mix(in srgb,var(--err) 7%,transparent); border-radius:6px; color:var(--err); }
.rv-pii p { color:var(--fg) !important; margin:.15rem 0 0 !important; font-size:.85rem !important; }
.rv-sums { display:grid; grid-template-columns:1fr 1fr; gap:1rem; } .rv-sums p { color:var(--fg) !important; font-size:.92rem !important; white-space:pre-wrap; }
.rv-rec textarea { width:100%; box-sizing:border-box; font:inherit; font-size:.9rem; border:1px solid var(--border); border-radius:6px; padding:.5rem .6rem; background:var(--surface); color:var(--fg); resize:vertical; }
.rv-tagchips { display:flex; flex-wrap:wrap; gap:.35rem; }
.rv-tag { font:inherit; font-size:.78rem; border:1px solid var(--border); background:var(--surface); color:var(--muted); border-radius:999px; padding:.25rem .7rem; cursor:pointer; }
.rv-tag:disabled { cursor:default; } .rv-tag.on { border-color:var(--lime); background:color-mix(in srgb,var(--lime) 22%,transparent); color:var(--fg); }
.rv-tag.changed { border-style:dashed; border-color:var(--brand); } .rv-tag-note { font-size:.7rem; margin-left:.25rem; color:var(--brand); }
.rv-small { font-size:.78rem !important; color:var(--muted); margin-top:.4rem !important; }
.rv-cols { display:grid; grid-template-columns:repeat(3,1fr); gap:1rem; }
.rv-actions { display:flex; gap:.6rem; flex-wrap:wrap; margin-top:1rem; align-items:center; }
.rv-empty { color:var(--muted); }
.muted { color:var(--muted); font-size:.85rem; }
.sr-only { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); white-space:nowrap; }
@media (max-width: 64rem) { .rv-stats { grid-template-columns:repeat(3,minmax(0,1fr)); } .rv-grid { grid-template-columns:1fr; } }
@media (max-width: 40rem) { .rv-tools .seg button { padding:.4rem .6rem; font-size:.75rem; } .rv-stats { grid-template-columns:repeat(2,minmax(0,1fr)); } .rv-sums, .rv-cols { grid-template-columns:1fr; } }
</style>
<style>
html.dark .rv-stat b { color:var(--fg); }
html.dark .rv-p.on { border-color:var(--lime); }
html.dark .rv-tag.changed, html.dark .rv-tag-note { border-color:var(--accent); color:var(--accent); }
</style>
