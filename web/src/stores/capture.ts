import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, DEMO, type CaptureJob, type CaptureListItem } from '../api'

// The packet capture started from the Capture page. Like the lab run (stores/jobs.ts) it lives in a
// store, not in the page, so leaving the page does not lose it and the top bar can show it.
//
// Updates come by polling: after starting, ask GET /api/captures/{id} every second until the job
// is done or failed. Polling fits here: a capture lasts seconds to minutes, the answer is tiny, and
// there is a clear end, so the cost of asking is small and nothing has to hold a connection open.
export const POLL_MS = 1000
const MAX_MISSES = 5 // stop after this many failed polls in a row (API stopped, VM asleep)

export const useCapture = defineStore('capture', () => {
  const job = ref<CaptureJob | null>(null)
  const error = ref<string | null>(null)
  const recent = ref<CaptureListItem[]>([])
  const active = computed(() => job.value?.status === 'capturing' || job.value?.status === 'analysing')
  let timer: number | undefined
  let misses = 0

  // One poll, then schedule the next one only if the job is still going. setTimeout (not
  // setInterval) so a slow answer never piles up a second request behind it.
  function poll() {
    window.clearTimeout(timer)
    timer = window.setTimeout(async () => {
      if (!job.value) return
      try {
        job.value = await api.captures.get(job.value.id)
        error.value = null
        misses = 0
      } catch (e) {
        misses += 1
        error.value = `Lost contact with the API (${(e as Error).message}). Trying again…`
        if (misses >= MAX_MISSES) {
          error.value = 'Lost contact with the API. Reload the page once it is running again.'
          return
        }
      }
      if (active.value) poll()
      else loadRecent()
    }, POLL_MS)
  }

  async function begin(started: Promise<CaptureJob>) {
    error.value = null
    try {
      job.value = await started
      misses = 0
      poll()
    } catch (e) {
      error.value = (e as Error).message
    }
  }

  const start = (seconds: number, decrypt: string | null) => begin(api.captures.start(seconds, decrypt))
  const upload = (file: File, decrypt: string | null) => begin(api.captures.upload(file, decrypt))

  async function open(id: string) {
    error.value = null
    try {
      job.value = await api.captures.get(id)
      if (active.value) poll()
    } catch (e) {
      error.value = (e as Error).message
    }
  }

  // After a reload: pick up a capture that is still going, else show the newest finished one.
  async function resume() {
    if (DEMO) {
      if (!job.value) await open('sample')
      return
    }
    try {
      const cur = await api.captures.current()
      if (cur) { job.value = cur; poll() }
      await loadRecent()
      if (!job.value && recent.value[0]) await open(recent.value[0].id)
    } catch {
      // No API: the page says so.
    }
  }

  async function loadRecent() {
    if (DEMO) return
    try { recent.value = await api.captures.list() } catch { /* list stays as it was */ }
  }

  return { job, error, recent, active, start, upload, open, resume, loadRecent }
})
