<script setup lang="ts">
import InfoTip from '../components/InfoTip.vue'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { formatTime } from '../api'
import { PAGE, useRuns } from '../stores/runs'
import { SUITES } from '../describe'
import { formatDuration, runSentence, testHistories, testTime, tone, totalCount } from '../runs'
import { useJobs } from '../stores/jobs'
import { useSummary } from '../stores/summary'
import CountsBar from '../components/CountsBar.vue'
import ResultsGrid from '../components/ResultsGrid.vue'

const router = useRouter()
const jobs = useJobs()
const store = useRuns()
const runs = computed(() => store.runs)
const details = computed(() => store.details)
const loading = computed(() => store.loading)
const error = computed(() => store.error)
const suite = ref('')
const onlyFailing = ref(false)
const tab = ref<'runs' | 'history'>('runs')
const load = (force = false) => store.load(force)
onMounted(() => load())
// When the live run finishes, its results land in the list without a reload.
watch(() => jobs.running, (now, before) => { if (before && !now) load(true) })

const suites = computed(() => [...new Set(runs.value.flatMap((r) => r.suites))].sort())
const shown = computed(() =>
  runs.value.filter((r) => (!suite.value || r.suites.includes(suite.value)) && (!onlyFailing.value || r.counts.failed + r.counts.error > 0)),
)
// 10 runs per page. The API sends one page at a time (keyset: before=<last id>). The total comes from
// the summary (already loaded for the top bar), so every page number shows before its runs are fetched.
// Clicking a page fetches only the runs up to it that are not loaded yet; earlier pages are reused.
const ROWS = PAGE
const summary = useSummary()
const page = ref(1)
watch([suite, onlyFailing], () => (page.value = 1))
const filtered = computed(() => Boolean(suite.value || onlyFailing.value))
// Filters run on the loaded runs only, so a filtered view counts what it has.
const total = computed(() => (filtered.value ? shown.value.length : Math.max(summary.data?.runs ?? 0, runs.value.length)))
const pages = computed(() => Math.max(1, Math.ceil(total.value / ROWS)))
const pageRows = computed(() => shown.value.slice((page.value - 1) * ROWS, page.value * ROWS))
const from = computed(() => (total.value ? (page.value - 1) * ROWS + 1 : 0))
const to = computed(() => Math.min(page.value * ROWS, total.value))
const canNext = computed(() => page.value < pages.value || (filtered.value && store.hasMore))
// Every page number up to 10 pages; beyond that first, last, and two pages either side of this one.
const pageList = computed<(number | '…')[]>(() => {
  const n = pages.value, p = page.value
  if (n <= 10) return Array.from({ length: n }, (_, i) => i + 1)
  const mid = [p - 2, p - 1, p, p + 1, p + 2].filter((x) => x > 1 && x < n)
  const out: (number | '…')[] = [1]
  if (mid[0] > 2) out.push('…')
  out.push(...mid)
  if (mid[mid.length - 1] < n - 1) out.push('…')
  out.push(n)
  return out
})
async function goTo(n: number) {
  if (n < 1) return
  if (filtered.value) { if (n > pages.value && store.hasMore) await store.loadMore() }
  else await store.loadUntil(n * ROWS)
  page.value = Math.min(n, pages.value)
}
const gridRuns = computed(() => shown.value.slice(0, 20).map((r) => details.value[r.id]).filter(Boolean))

// Tests that switched between pass and fail across the loaded runs (same rule as the Test history tab).
// The list now loads 10 at a time, so read the newest 20 from the full runs the store already has.
const recentDetails = computed(() => Object.values(details.value).sort((x, y) => (x.id < y.id ? 1 : -1)).slice(0, 20))
const flaky = computed(() => testHistories(recentDetails.value).filter((h) => h.changes).length)
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
    <div class="tile"><span>Runs loaded</span><b>{{ runs.length }}{{ store.hasMore ? '+' : '' }}</b></div>
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
        <tr v-for="r in pageRows" :key="r.id" :class="tone(r.counts)" @click="open(r.id)">
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

    <nav v-if="tab === 'runs' && !loading && !error && shown.length" class="pager" aria-label="Pages">
      <span class="muted small">{{ from }}–{{ to }} of {{ total }}{{ filtered && store.hasMore ? '+' : '' }} runs<template v-if="filtered"> (filtered)</template></span>
      <div class="pages">
        <button type="button" class="pg" :disabled="page === 1" aria-label="Previous page" @click="goTo(page - 1)">‹ Prev</button>
        <template v-for="(n, i) in pageList" :key="i">
          <span v-if="n === '…'" class="gap" aria-hidden="true">…</span>
          <button v-else type="button" class="pg num" :aria-label="`Page ${n}`" :aria-current="n === page ? 'page' : undefined" :disabled="store.loadingMore" @click="goTo(n)">{{ n }}</button>
        </template>
        <button type="button" class="pg" :disabled="!canNext || store.loadingMore" aria-label="Next page" @click="goTo(page + 1)">{{ store.loadingMore ? 'Loading…' : 'Next ›' }}</button>
      </div>
    </nav>
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
.pager { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px 12px; padding: 12px 16px; border-top: 1px solid var(--line); }
.pages { display: flex; flex-wrap: wrap; gap: 4px; }
/* Pager buttons use theme tokens only (--card, --ink, --line, --hover, --accent), so light and dark
   each get their own hover colour from style.css instead of one hard-coded shade. */
.pg { min-height: 32px; padding: 4px 10px; font-size: 13px; background: var(--card); color: var(--ink); border: 1px solid var(--line); }
.pg.num { min-width: 34px; }
.pg:hover:not(:disabled) { background: var(--hover); color: var(--accent); border-color: var(--accent); }
.pg[aria-current='page'], .pg[aria-current='page']:hover { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
.pg:disabled:not([aria-current]) { opacity: .45; cursor: default; }
.gap { align-self: center; padding: 0 4px; color: var(--muted); }
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
