import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, DEMO, type Job } from '../api'
import { useSummary } from './summary'

// The lab run started from the panel. It lives here, not in the Start a run page, so leaving that
// page does not lose it: every page can show it, and polling continues until the run ends.
// On load the store asks the API for the current job, so a refresh or a second tab finds it too.
// Updates arrive by Server-Sent Events: one open connection, and the API pushes each change.
// If the stream cannot open (an older API without it), the store falls back to asking every 2 s.
export const useJobs = defineStore('jobs', () => {
  const job = ref<Job | null>(null)
  const error = ref<string | null>(null)
  const running = computed(() => job.value?.status === 'running')
  let timer: number | undefined
  let source: EventSource | null = null
  const live = ref(false) // true while updates arrive by push

  function finished() {
    source?.close()
    source = null
    live.value = false
    useSummary().load()
  }

  // Follow the job by push. EventSource reconnects by itself after a network blip; if it never
  // managed to open at all, polling takes over.
  function follow() {
    if (!job.value) return
    source?.close()
    window.clearTimeout(timer)
    let opened = false
    const es = new EventSource(`/api/jobs/${encodeURIComponent(job.value.id)}/events`)
    source = es
    es.onopen = () => { opened = true; live.value = true }
    es.addEventListener('job', (e) => {
      job.value = JSON.parse((e as MessageEvent).data) as Job
      error.value = null
      if (!running.value) finished()
    })
    es.onerror = () => {
      if (!running.value) return finished() // the server closed the stream after the last update
      if (!opened) { es.close(); source = null; live.value = false; poll() }
    }
  }

  async function resume() {
    if (DEMO) return
    try {
      job.value = await api.currentJob()
      if (running.value) follow()
    } catch {
      // No API: the pages already say so; nothing to resume.
    }
  }

  async function start(suite: string) {
    error.value = null
    try {
      job.value = await api.startRun(suite)
      follow()
    } catch (e) {
      error.value = (e as Error).message
    }
  }

  // Fallback: ask the API every 2 s how the run is going until it finishes, then refresh the totals.
  function poll() {
    window.clearTimeout(timer)
    timer = window.setTimeout(async () => {
      if (!job.value) return
      try {
        job.value = await api.job(job.value.id)
        error.value = null
      } catch (e) {
        error.value = (e as Error).message
      }
      if (running.value) poll()
      else useSummary().load()
    }, 2000)
  }

  return { job, error, running, live, resume, start }
})
