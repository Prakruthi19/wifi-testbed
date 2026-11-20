<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import { api, DEMO, type Job } from '../api'
import { useSummary } from '../stores/summary'

const summary = useSummary()
const suite = ref('failures')
const job = ref<Job | null>(null)
const error = ref<string | null>(null)
let timer: number | undefined

async function start() {
  error.value = null
  try {
    job.value = await api.startRun(suite.value)
    poll()
  } catch (e) {
    error.value = (e as Error).message
  }
}

// Ask the API every 2 s how the run is going until it finishes.
function poll() {
  timer = window.setTimeout(async () => {
    if (!job.value) return
    try {
      job.value = await api.job(job.value.id)
    } catch (e) {
      error.value = (e as Error).message
      return
    }
    if (job.value.status === 'running') poll()
    else summary.load()
  }, 2000)
}
onUnmounted(() => window.clearTimeout(timer))
</script>

<template>
  <h1>Start a run</h1>
  <p class="sub">Runs one pytest suite against the lab. Only one run at a time, because the tests share the radios.</p>

  <p v-if="DEMO" class="error">This is the read-only demo. Starting runs needs the API running in the lab VM.</p>
  <p v-else-if="summary.data && !summary.data.can_start_runs" class="error">
    The API is not running as root, so it can only show results. Start it with <code>sudo -E .venv/bin/uvicorn testbed.api:app</code>.
  </p>

  <form class="card form" @submit.prevent="start">
    <label>Suite
      <select v-model="suite">
        <option v-for="s in summary.data?.startable_suites ?? []" :key="s" :value="s">{{ s }}</option>
      </select>
    </label>
    <button type="submit" :disabled="DEMO || !summary.data?.can_start_runs || job?.status === 'running'">
      {{ job?.status === 'running' ? 'Running…' : 'Start run' }}
    </button>
  </form>

  <p v-if="error" class="error">{{ error }}</p>
  <section v-if="job" class="card" aria-live="polite">
    <h2>Run {{ job.id }}: {{ job.suite }} <span class="muted">({{ job.status }})</span></h2>
    <pre>{{ job.log_tail.join('\n') || 'Waiting for output…' }}</pre>
    <RouterLink v-if="job.status !== 'running'" to="/runs">See it in Test runs</RouterLink>
  </section>
</template>

<style scoped>
.form { display: flex; flex-wrap: wrap; gap: 12px; align-items: end; }
.form label { display: flex; flex-direction: column; gap: 4px; }
</style>
