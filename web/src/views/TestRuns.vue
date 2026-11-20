<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, formatTime, type RunDetail, type RunSummary } from '../api'
import CountsBar from '../components/CountsBar.vue'
import ResultsGrid from '../components/ResultsGrid.vue'

const runs = ref<RunSummary[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const suite = ref('')
const onlyFailing = ref(false)
const view = ref<'grid' | 'table'>('grid')
const details = ref<RunDetail[]>([])
const GRID_RUNS = 20 // the grid shows the latest 20 runs; older ones stay in the table

onMounted(async () => {
  try {
    runs.value = await api.runs()
    details.value = await Promise.all(runs.value.slice(0, GRID_RUNS).map((r) => api.run(r.id)))
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
})

const suites = computed(() => [...new Set(runs.value.flatMap((r) => r.suites))].sort())
const gridRuns = computed(() => details.value.filter((d) => shown.value.some((r) => r.id === d.id)))
const shown = computed(() =>
  runs.value.filter(
    (r) => (!suite.value || r.suites.includes(suite.value)) && (!onlyFailing.value || r.counts.failed + r.counts.error > 0),
  ),
)
</script>

<template>
  <h1>Test runs</h1>
  <p class="sub">Every pytest session run in the lab, newest first.</p>

  <div class="filters">
    <label>Suite
      <select v-model="suite">
        <option value="">All suites</option>
        <option v-for="s in suites" :key="s" :value="s">{{ s }}</option>
      </select>
    </label>
    <label class="check"><input v-model="onlyFailing" type="checkbox" /> Only runs with failures</label>
    <div role="group" aria-label="View" class="segs">
      <button type="button" class="seg" :aria-pressed="view === 'grid'" @click="view = 'grid'">Grid</button>
      <button type="button" class="seg" :aria-pressed="view === 'table'" @click="view = 'table'">Table</button>
    </div>
  </div>

  <p v-if="error" class="error">Could not load runs: {{ error }}</p>
  <p v-else-if="loading" class="muted">Loading…</p>
  <p v-else-if="!shown.length" class="muted">No runs match.</p>

  <div v-else-if="view === 'grid'" class="card">
    <h2>Every test in every run</h2>
    <ResultsGrid :runs="gridRuns" />
  </div>
  <div v-else class="card">
    <table class="stack">
      <thead><tr><th>Finished</th><th>Suites</th><th>Passed</th><th>Failed</th><th>Result</th></tr></thead>
      <tbody>
        <tr v-for="r in shown" :key="r.id">
          <td data-label="Finished"><RouterLink :to="{ name: 'run', params: { id: r.id } }">{{ formatTime(r.finished) }}</RouterLink></td>
          <td data-label="Suites">{{ r.suites.join(', ') }}</td>
          <td data-label="Passed" class="num">{{ r.counts.passed }}</td>
          <td data-label="Failed" class="num">{{ r.counts.failed + r.counts.error }}</td>
          <td data-label="Result"><CountsBar :counts="r.counts" /></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.filters { display: flex; flex-wrap: wrap; gap: 12px 20px; align-items: center; margin-bottom: 16px; }
.filters label { display: flex; align-items: center; gap: 8px; }
.check input { width: 18px; height: 18px; }
.segs { display: flex; gap: 4px; margin-left: auto; }
.seg { background: var(--bg); color: var(--ink); border: 1px solid var(--line); min-height: 36px; padding: 6px 12px; }
.seg[aria-pressed='true'] { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
</style>
