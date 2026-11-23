// Plain-words summaries of a run, shared by the runs list and the run page.
import type { Counts, RunDetail, TestResult } from './api'
import { describe } from './describe'

export const failedCount = (c: Counts) => c.failed + c.error
export const totalCount = (c: Counts) => c.passed + c.failed + c.error + c.skipped

// "All 8 passed", "2 failed: DNS broken, Address server switched off", "All 8 skipped".
export function runSentence(counts: Counts, results?: TestResult[]) {
  const total = totalCount(counts)
  const bad = failedCount(counts)
  if (!total) return 'No tests ran'
  if (!bad && counts.skipped === total) return `All ${total} skipped`
  if (!bad) return `All ${counts.passed} passed` + (counts.skipped ? `, ${counts.skipped} skipped` : '')
  const names = (results ?? []).filter((r) => r.outcome === 'failed' || r.outcome === 'error').map((r) => describe(r.nodeid).title)
  if (!names.length) return `${bad} of ${total} failed`
  const shown = names.slice(0, 2).join(', ')
  return `${bad} failed: ${shown}` + (names.length > 2 ? ` and ${names.length - 2} more` : '')
}

export const tone = (counts: Counts) => (failedCount(counts) ? 'bad' : counts.passed ? 'good' : 'skip')

// Sum of the time each test took; close to the run's length, since tests run one after another.
export const testTime = (run: RunDetail) => run.results.reduce((s, r) => s + (r.duration_s || 0), 0)

export function formatDuration(s: number) {
  if (s < 60) return `${Math.round(s)} s`
  const m = Math.floor(s / 60)
  const r = Math.round(s % 60)
  return m < 60 ? `${m} min ${r} s` : `${Math.floor(m / 60)} h ${m % 60} min`
}

// One test across runs (oldest first). "Changed" counts pass <-> fail switches between runs where it
// ran; skipped runs are ignored, so a test skipped while the lab was down does not count as a change.
export interface TestHistory { id: string; suite: string; cells: (TestResult | null)[]; changes: number; failingNow: boolean }

export function testHistories(runs: RunDetail[]): TestHistory[] {
  const cols = [...runs].sort((a, b) => a.finished.localeCompare(b.finished))
  const ids = new Map<string, string>()
  cols.forEach((r) => r.results.forEach((t) => ids.set(t.nodeid, t.suite)))
  return [...ids].map(([id, suite]) => {
    const cells = cols.map((r) => r.results.find((t) => t.nodeid === id) ?? null)
    const ran = cells.filter((c): c is TestResult => !!c && c.outcome !== 'skipped').map((c) => c.outcome === 'passed')
    const changes = ran.slice(1).filter((ok, i) => ok !== ran[i]).length
    const last = [...cells].reverse().find(Boolean)
    return { id, suite, cells, changes, failingNow: last?.outcome === 'failed' || last?.outcome === 'error' }
  })
}
