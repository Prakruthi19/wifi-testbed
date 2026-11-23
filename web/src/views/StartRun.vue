<script setup lang="ts">
import InfoTip from '../components/InfoTip.vue'
import { computed, ref } from 'vue'
import { DEMO } from '../api'
import { useJobs } from '../stores/jobs'
import { useSummary } from '../stores/summary'

const summary = useSummary()
const jobs = useJobs()
const suite = ref('failures')
const job = computed(() => jobs.job)
const pct = computed(() => {
  const p = job.value?.progress
  return p?.total ? Math.round((100 * p.done) / p.total) : null
})
</script>

<template>
  <h1>Start a run <InfoTip text="Runs one pytest suite against the lab. One run at a time, because the tests share the radios." /></h1>

  <p v-if="DEMO" class="error">This is the read-only demo. Starting runs needs the API running in the lab VM.</p>
  <p v-else-if="summary.data && !summary.data.can_start_runs" class="error">
    The API is not running as root, so it can only show results. Start it with <code>sudo -E .venv/bin/uvicorn testbed.api:app</code>.
  </p>

  <form class="card form" @submit.prevent="jobs.start(suite)">
    <label>Suite
      <select v-model="suite">
        <option v-for="s in summary.data?.startable_suites ?? []" :key="s" :value="s">{{ s }}</option>
      </select>
    </label>
    <button type="submit" :disabled="DEMO || !summary.data?.can_start_runs || job?.status === 'running'">
      {{ job?.status === 'running' ? 'Running…' : 'Start run' }}
    </button>
  </form>

  <p v-if="jobs.error" class="error">{{ jobs.error }}</p>
  <section v-if="job" class="card" aria-live="polite">
    <h2>Run {{ job.id }}: {{ job.suite }} <span class="muted">({{ job.status }})</span></h2>
    <p v-if="job.progress?.total" class="muted">
      {{ job.progress.done }} of {{ job.progress.total }} tests finished
      <progress :value="job.progress.done" :max="job.progress.total" :aria-label="`${pct}% of tests finished`" />
    </p>
    <p v-if="job.status === 'running'" class="muted small">Safe to leave this page: the run keeps going.</p>
    <pre>{{ job.log_tail.join('\n') || 'Waiting for output…' }}</pre>
    <RouterLink v-if="job.status !== 'running'" to="/runs">See it in Test runs</RouterLink>
  </section>
</template>

<style scoped>
.form { display: flex; flex-wrap: wrap; gap: 12px; align-items: end; }
.form label { display: flex; flex-direction: column; gap: 4px; }
progress { vertical-align: middle; margin-left: 8px; width: 160px; }
</style>
