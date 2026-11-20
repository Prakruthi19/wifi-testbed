// Every call to the Python API goes through here. Shapes match testbed/api.py.
// In demo mode (VITE_DEMO=1) the same data comes from frozen JSON files in public/demo/.

export type Outcome = 'passed' | 'failed' | 'error' | 'skipped'
export type Counts = Record<Outcome, number>

export interface Summary {
  sample?: boolean // true only for made-up placeholder data, never for an export of real runs
  runs: number
  last_finished: string | null
  tests: number
  counts: Counts
  can_start_runs: boolean
  startable_suites: string[]
}

export interface AccessPoint {
  name: string
  ssid: string
  security: string
  pmf?: number
  channel: number
}

export interface Lab {
  aps?: AccessPoint[]
  client_radios?: { name: string; iface: string; namespace: string }[]
  vlans?: { ssid: string; vlan: number; subnet: string }[]
  [key: string]: unknown
}

export interface TestResult {
  nodeid: string
  suite: string
  outcome: Outcome
  duration_s: number
  message: string
  properties: Record<string, unknown>
  artifact_dir: string
  files: string[]
  classifier_stage: string | null
  history?: Outcome[]
  when?: string
}

export interface RunSummary {
  id: string
  finished: string
  counts: Counts
  suites: string[]
}

export interface RunDetail {
  id: string
  finished: string
  counts: Counts
  results: TestResult[]
}

export interface Job {
  id: string
  suite: string
  status: 'running' | 'passed' | 'failed'
  returncode: number | null
  log_tail: string[]
}

export const DEMO = import.meta.env.VITE_DEMO === '1'

async function get<T>(path: string): Promise<T> {
  // /runs/2026... -> demo/runs/2026....json ; /summary -> demo/summary.json
  const url = DEMO ? `${import.meta.env.BASE_URL}demo${path}.json` : `/api${path}`
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${url}`)
  return res.json() as Promise<T>
}

export const api = {
  summary: () => get<Summary>('/summary'),
  lab: () => get<Lab>('/lab'),
  runs: () => get<RunSummary[]>('/runs'),
  run: (id: string) => get<RunDetail>(`/runs/${encodeURIComponent(id)}`),
  tests: () => get<TestResult[]>('/tests'),
  job: (id: string) => get<Job>(`/jobs/${encodeURIComponent(id)}`),

  async startRun(suite: string): Promise<Job> {
    if (DEMO) throw new Error('The demo cannot start runs; it has no lab behind it.')
    const res = await fetch('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ suite }),
    })
    const body = await res.json()
    if (!res.ok) throw new Error(body.detail ?? `${res.status} ${res.statusText}`)
    return body as Job
  },

  artifactUrl: (dir: string, name: string) =>
    DEMO ? null : `/api/artifacts/${encodeURIComponent(dir)}/${encodeURIComponent(name)}`,
}

// Test ids look like tests/test_failures.py::test_induced_failure[mac_blocked]; people want "induced_failure[mac_blocked]".
export const testName = (nodeid: string) => nodeid.split('::').slice(1).join('::').replace(/^test_/, '')

export const formatTime = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : 'never'
