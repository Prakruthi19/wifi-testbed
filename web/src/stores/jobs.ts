import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, DEMO, type Job } from '../api'
import { useSummary } from './summary'

// The lab run started from the panel. It lives here, not in the Start a run page, so leaving that
// page does not lose it: every page can show it, and polling continues until the run ends.
// On load the store asks the API for the current job, so a refresh or a second tab finds it too.
export const useJobs = defineStore('jobs', () => {
  const job = ref<Job | null>(null)
  const error = ref<string | null>(null)
  const running = computed(() => job.value?.status === 'running')
  let timer: number | undefined

  async function resume() {
    if (DEMO) return
    try {
      job.value = await api.currentJob()
      if (running.value) poll()
    } catch {
      // No API: the pages already say so; nothing to resume.
    }
  }

  async function start(suite: string) {
    error.value = null
    try {
      job.value = await api.startRun(suite)
      poll()
    } catch (e) {
      error.value = (e as Error).message
    }
  }

  // Ask the API every 2 s how the run is going until it finishes, then refresh the totals.
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

  return { job, error, running, resume, start }
})
