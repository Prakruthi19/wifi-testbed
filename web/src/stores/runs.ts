import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, type RunDetail, type RunSummary } from '../api'

// Runs are kept here, outside any page, so going back to Test runs shows them at once instead of
// fetching everything again. Data younger than FRESH_MS is reused as is; older data stays on
// screen while a refresh runs in the background (stale-while-revalidate).
const FRESH_MS = 30_000
export const PAGE = 10 // runs per page: the table shows one page, Next fetches the next one

export const useRuns = defineStore('runs', () => {
  const runs = ref<RunSummary[]>([])
  const details = ref<Record<string, RunDetail>>({})
  const loadedAt = ref(0)
  const loading = ref(false) // true only when there is nothing to show yet
  const refreshing = ref(false)
  const error = ref<string | null>(null)
  const hasMore = ref(false)
  const loadingMore = ref(false)
  let inFlight: Promise<void> | null = null

  async function fetchAll() {
    // Two requests in parallel: the list, and the newest runs in full.
    // A refresh re-reads as many runs as are already on screen, so pages loaded with Load more stay.
    const want = Math.max(PAGE, runs.value.length)
    const [list, recent] = await Promise.all([api.runsPage(want), api.recentRuns().catch(() => null)])
    // An older demo export has no recent.json: fall back to one request per run.
    const full = recent ?? (await Promise.all(list.slice(0, 20).map((r) => api.run(r.id))))
    runs.value = list
    hasMore.value = list.length === want
    details.value = { ...details.value, ...Object.fromEntries(full.map((d) => [d.id, d])) }
    loadedAt.value = Date.now()
  }

  // force: reload even if fresh (for example when a run just finished).
  function load(force = false): Promise<void> {
    if (inFlight) return inFlight
    if (!force && loadedAt.value && Date.now() - loadedAt.value < FRESH_MS) return Promise.resolve()
    const first = !loadedAt.value
    loading.value = first
    refreshing.value = !first
    inFlight = fetchAll()
      .then(() => { error.value = null })
      .catch((e) => { error.value = (e as Error).message })
      .finally(() => { loading.value = false; refreshing.value = false; inFlight = null })
    return inFlight
  }

  // The next page of older runs, appended below the ones already shown.
  async function loadMore() {
    const last = runs.value[runs.value.length - 1]
    if (!last || loadingMore.value) return
    loadingMore.value = true
    try {
      const page = await api.runsPage(PAGE, last.id)
      runs.value = [...runs.value, ...page.filter((r) => !runs.value.some((x) => x.id === r.id))]
      hasMore.value = page.length === PAGE
      error.value = null
    } catch (e) {
      error.value = (e as Error).message
    } finally {
      loadingMore.value = false
    }
  }

  // Make sure at least `count` runs are loaded (jumping to page 7 needs the first 70), in one request.
  async function loadUntil(count: number) {
    const last = runs.value[runs.value.length - 1]
    const need = count - runs.value.length
    if (!last || need <= 0 || !hasMore.value || loadingMore.value) return
    loadingMore.value = true
    try {
      const page = await api.runsPage(need, last.id)
      runs.value = [...runs.value, ...page.filter((r) => !runs.value.some((x) => x.id === r.id))]
      hasMore.value = page.length === need
      error.value = null
    } catch (e) {
      error.value = (e as Error).message
    } finally {
      loadingMore.value = false
    }
  }

  // One run in full: from memory when we have it, otherwise fetched once and kept.
  async function run(id: string): Promise<RunDetail> {
    const hit = details.value[id]
    if (hit) return hit
    const d = await api.run(id)
    details.value = { ...details.value, [id]: d }
    return d
  }

  return { runs, details, loadedAt, loading, refreshing, error, hasMore, loadingMore, load, loadMore, loadUntil, run }
})
