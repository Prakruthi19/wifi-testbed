<script setup lang="ts">
import InfoTip from '../components/InfoTip.vue'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api, formatTime, type RunDetail, type RunSummary } from '../api'
import { SUITES } from '../describe'
import { formatDuration, runSentence, testHistories, testTime, tone, totalCount } from '../runs'
import { useJobs } from '../stores/jobs'
import CountsBar from '../components/CountsBar.vue'
import ResultsGrid from '../components/ResultsGrid.vue'

const router = useRouter()
const jobs = useJobs()
const runs = ref<RunSummary[]>([])
const details = ref<Record<string, RunDetail>>({})
const loading = ref(true)
const error = ref<string | null>(null)
const suite = ref('')
const onlyFailing = ref(false)
const tab = ref<'runs' | 'history'>('runs')
const DETAIL_RUNS = 20 // the latest 20 runs are loaded in full, for the sentences and the flaky-tests grid

async function load() {
  try {
    runs.value = await api.runs()
    const ds = await Promise.all(runs.value.slice(0, DETAIL_RUNS).map((r) => api.run(r.id)))
    details.value = Object.fromEntries(ds.map((d) => [d.id, d]))
    error.value = null
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}
onMounted(load)
// When the live run finishes, its results land in the list without a reload.
watch(() => jobs.running, (now, before) => { if (before && !now) load() })

const suites = computed(() => [...new Set(runs.value.flatMap((r) => r.suites))].sort())
const shown = computed(() =>
  runs.value.filter((r) => (!suite.value || r.suites.includes(suite.value)) && (!onlyFailing.value || r.counts.failed + r.counts.error > 0)),
)
const gridRuns = computed(() => shown.value.map((r) => details.value[r.id]).filter(Boolean))

// Tests that switched between pass and fail across the loaded runs (same rule as the Test history tab).
const flaky = computed(() => testHistories(Object.values(details.value)).filter((h) => h.changes).length)
const latest = computed(() => runs.value[0] ?? null)
const passRate = computed(() => {
  const c = latest.value?.counts
  const ran = c ? c.passed + c.failed + c.error : 0
  return c && ran ? Math.round((100 * c.passed) / ran) : null
})

// The live run card: elapsed time ticks once a second while it runs.
const now = ref(Date.now())
let clock: number | undefined
watch(() => jobs.running, (on) => {
  window.clearInterval(clock)
  if (on) clock = window.setInterval(() => (now.value = Date.now()), 1000)
}, { immediate: true })
onUnmounted(() => window.clearInterval(clock))
const elapsed = computed(() => (jobs.job ? formatDuration(Math.max(0, (now.value - Date.parse(jobs.job.started)) / 1000)) : ''))
const pct = computed(() => {
  const p = jobs.job?.progress
  return p?.total ? Math.round((100 * p.done) / p.total) : null
})

const open = (id: string) => router.push({ name: 'run', params: { id } })
</script>

<template>
  <div class="head">
    <div>
      <h1>Test runs</h1>
    </div>
    <RouterLink to="/start" class="btn">Start a run</RouterLink>
  </div>

  <section v-if="jobs.running && jobs.job" class="card live" aria-live="polite" aria-label="Run in progress">
    <div class="live-head">
      <span class="dot" aria-hidden="true"></span>
      <h2>Running now: {{ SUITES[jobs.job.suite] ?? jobs.job.suite }}</h2>
      <span class="muted">started {{ elapsed }} ago</span>
      <RouterLink to="/start" class="more">Open live log</RouterLink>
    </div>
    <div v-if="jobs.job.progress?.total" class="progress">
      <div class="track"><div class="fill" :style="{ width: pct + '%' }"></div></div>
      <span>{{ jobs.job.progress.done }} of {{ jobs.job.progress.total }} tests finished</span>
    </div>
    <pre>{{ jobs.job.log_tail.slice(-4).join('\n') || 'Waiting for output…' }}</pre>
  </section>

  <div class="tiles kpis">
    <div class="tile"><span>Runs</span><b>{{ runs.length }}</b></div>
    <div class="tile"><span>Latest run</span><b class="small" :class="latest ? tone(latest.counts) : ''">{{ latest ? runSentence(latest.counts, details[latest.id]?.results) : '—' }}</b></div>
    <div class="tile"><span>Pass rate, latest run</span><b>{{ passRate === null ? '—' : passRate + '%' }}</b></div>
    <div class="tile"><span>Changed result <InfoTip text="Tests that passed in one run and failed in another. Not all are flaky: a known cause, like the lab not being set up, also counts." /></span><b :class="{ warn: flaky }">{{ flaky }}</b></div>
  </div>

  <div class="panel">
    <div class="toolbar">
      <div role="tablist" aria-label="Show" class="tabs">
        <button type="button" role="tab" :aria-selected="tab === 'runs'" @click="tab = 'runs'">Runs <span class="count">{{ shown.length }}</span></button>
        <button type="button" role="tab" :aria-selected="tab === 'history'" @click="tab = 'history'">Test history</button>
      </div>
      <div class="filters">
        <label>Suite
          <select v-model="suite">
            <option value="">All suites</option>
            <option v-for="s in suites" :key="s" :value="s">{{ SUITES[s] ?? s }}</option>
          </select>
        </label>
        <label class="check"><input v-model="onlyFailing" type="checkbox" /> Only runs with failures</label>
      </div>
    </div>

    <p v-if="error" class="error">Could not load runs: {{ error }}</p>
    <p v-else-if="loading" class="muted pad">Loading…</p>
    <p v-else-if="!shown.length" class="muted pad">{{ runs.length ? "No runs match." : "No runs yet. Start one, and it shows up here when it finishes." }}</p>

    <table v-else-if="tab === 'runs'" class="stack runs" aria-label="Runs">
      <thead><tr><th>Result</th><th>Finished</th><th>Suites</th><th>Summary</th><th>Tests</th><th>Test time</th></tr></thead>
      <tbody>
        <tr v-for="r in shown" :key="r.id" :class="tone(r.counts)" @click="open(r.id)">
          <td data-label="Result"><span class="status" :class="tone(r.counts)">{{ tone(r.counts) === 'bad' ? 'Failed' : tone(r.counts) === 'good' ? 'Passed' : 'Skipped' }}</span></td>
          <td data-label="Finished"><RouterLink :to="{ name: 'run', params: { id: r.id } }" @click.stop>{{ formatTime(r.finished) }}</RouterLink></td>
          <td data-label="Suites" class="hide-sm">{{ r.suites.map((s) => (s === 'other' ? 'Other' : SUITES[s] ?? s)).join(', ') }}</td>
          <td data-label="Summary" class="summary">{{ runSentence(r.counts, details[r.id]?.results) }}</td>
          <td data-label="Tests"><div class="tests"><CountsBar :counts="r.counts" /><span class="num">{{ r.counts.passed }}/{{ totalCount(r.counts) }}</span></div></td>
          <td data-label="Test time" class="num hide-sm">{{ details[r.id] ? formatDuration(testTime(details[r.id])) : '—' }}</td>
        </tr>
      </tbody>
    </table>

    <div v-else class="pad">
      <ResultsGrid :runs="gridRuns" />
    </div>
  </div>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.btn { background: var(--accent); color: var(--accent-ink); text-decoration: none; padding: 8px 14px; border-radius: var(--radius); font-weight: 600; white-space: nowrap; }
.kpis { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.tile b.small { font-size: 15px; line-height: 1.35; margin-top: 4px; }
.tile b.good { color: var(--pass); } .tile b.bad { color: var(--fail); } .tile b.skip, .tile b.warn { color: var(--skip); }

.live { border-left: 3px solid var(--accent); }
.live-head { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 12px; }
.live-head h2 { margin: 0; font-size: 16px; }
.live-head .more { margin-left: auto; }
.dot { width: 10px; height: 10px; border-radius: 50%; background: var(--accent); animation: pulse 1.4s ease-in-out infinite; }
@keyframes pulse { 50% { opacity: .3; } }
@media (prefers-reduced-motion: reduce) { .dot { animation: none; } }
.progress { display: flex; align-items: center; gap: 12px; margin: 12px 0 8px; font-size: 14px; }
.track { flex: 1; max-width: 420px; height: 8px; background: var(--line); border-radius: var(--radius-sm); overflow: hidden; }
.fill { height: 100%; background: var(--accent); transition: width .4s; }
.live pre { margin: 8px 0 0; max-height: 90px; }

.panel { background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); overflow: hidden; }
.toolbar { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px 16px; padding: 0 16px; border-bottom: 1px solid var(--line); }
.tabs { display: flex; gap: 4px; }
.tabs button { background: none; color: var(--muted); border-radius: 0; padding: 14px 10px 12px; border-bottom: 2px solid transparent; font-weight: 600; min-height: 0; }
.tabs button[aria-selected='true'] { color: var(--ink); border-bottom-color: var(--accent); }
.count { display: inline-block; min-width: 20px; margin-left: 4px; padding: 0 6px; font-size: 12px; background: var(--bg); border: 1px solid var(--line); border-radius: var(--radius-sm); color: var(--muted); }
.filters { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center; padding: 8px 0; font-size: 14px; }
.filters label { display: flex; align-items: center; gap: 8px; }
.filters select { min-height: 34px; padding: 4px 8px; }
.check input { width: 16px; height: 16px; }
.pad { padding: 16px; margin: 0; }
.error { margin: 16px; }

.runs th { white-space: nowrap; padding: 10px 16px; background: var(--bg); border-bottom: 1px solid var(--line); font-size: 12px; text-transform: uppercase; letter-spacing: .03em; }
.runs td { padding: 12px 16px; vertical-align: middle; }
.runs tbody tr { cursor: pointer; }
.runs tbody tr:hover { background: var(--bg); }
.summary { max-width: 360px; }
.tests { display: flex; align-items: center; gap: 10px; min-width: 150px; }
.tests :deep(.bar) { flex: 1; }
.status { display: inline-block; padding: 2px 8px; font-size: 12px; font-weight: 600; border-radius: var(--radius-sm); }
.status.good { color: var(--pass); background: var(--pass-bg); }
.status.bad { color: var(--fail); background: var(--fail-bg); }
.status.skip { color: var(--skip); background: var(--skip-bg); }
@media (max-width: 900px) { .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 640px) {
  .runs td { padding: 4px 16px; }
  .hide-sm { display: none !important; }
  .tabs { overflow-x: auto; }
  .tests { min-width: 0; }
  .summary { max-width: none; text-align: right; }
}
</style>
