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

export interface HomeNetwork {
  ssid: string
  access_points: { name: string; iface: string; channel: number }[]
  devices: { name: string; iface: string; profile: string; bands: string[] }[]
}

export interface Lab {
  aps?: AccessPoint[]
  home?: HomeNetwork
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
  started: string
  finished: string | null
  progress: { done: number; total: number | null }
  log_tail: string[]
}

export const DEMO = import.meta.env.VITE_DEMO === '1'

// Packet captures (testbed/capturejobs.py + testbed/pcap_analysis.py).
export type CaptureStatus = 'capturing' | 'analysing' | 'done' | 'failed'
export interface CaptureDevice {
  mac: string; bssid: string | null; ssid: string | null; stage: string; stage_label: string; summary: string
  notes: string[]; frames_sent: number; frames_received: number; retries: number; signal_dbm: number | null
  ip: string | null; dns_names: string[]
}
export interface CaptureAnalysis {
  frames: number; truncated: boolean; duration_s: number
  by_type: Record<'management' | 'control' | 'data' | 'other', number>
  by_kind: { kind: string; label: string; count: number }[]
  retries: number; retry_pct: number
  networks: { bssid: string; ssid: string | null; beacons: number; secured: boolean; signal_dbm: number | null }[]
  devices: CaptureDevice[]
  disconnects: { no: number; t: number; kind: string; from: string; to: string; sender: string; reason: number | null; meaning: string }[]
  handshakes: { client: string; bssid: string; messages: number[]; complete: boolean; duration_ms: number; retries: number }[]
  dhcp: { no: number; t: number; type: string; client: string | null; ip: string | null; server: string | null }[]
  dns: { no: number; t: number; response: boolean; name: string | null; rcode: number | null; answer: string | null }[]
  events: { no: number; t: number; kind: string; label: string; text: string }[]
  events_total: number
  notes: string[]
}
export interface CaptureJob {
  id: string; source: 'live' | 'upload' | 'sample'; status: CaptureStatus; started: string; finished: string | null
  error: string | null; bytes: number; seconds: number | null; iface: string | null; filename: string | null
  decrypt: string | null; elapsed_s?: number; sample?: boolean; result: CaptureAnalysis | null
}
export interface CaptureListItem extends Omit<CaptureJob, 'result'> { frames: number | null; devices: number; disconnects: number }

// A saved network plan, as listed (no body) and as opened (with the plan in the download file format).
export interface SavedPlan { id: number; name: string; home: string; aps: number; created: string; updated: string }
export interface User { email: string; client: string }
export interface SavedPlanFull extends SavedPlan { plan: unknown }
export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

// Sends JSON and turns an error reply into an ApiError with the server's own message.
async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (res.status === 204) return undefined as T
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const d = (data as { detail?: unknown }).detail
    throw new ApiError(res.status, typeof d === 'string' ? d : `${res.status} ${res.statusText}`)
  }
  return data as T
}

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
  // One page of runs, newest first; `before` is the id of the last run already shown (keyset paging).
  // The demo has a single frozen runs.json, so it is paged here the same way the API pages it.
  async runsPage(limit: number, before?: string): Promise<RunSummary[]> {
    if (DEMO) {
      const all = await get<RunSummary[]>('/runs')
      return all.filter((r) => !before || r.id < before).slice(0, limit)
    }
    const q = new URLSearchParams({ limit: String(limit), ...(before ? { before } : {}) })
    return get<RunSummary[]>(`/runs?${q}`)
  },
  run: (id: string) => get<RunDetail>(`/runs/${encodeURIComponent(id)}`),
  // The newest runs in full, in one request (the API caps it; the demo has a frozen copy).
  recentRuns: () => get<RunDetail[]>('/runs/recent'),
  tests: () => get<TestResult[]>('/tests'),
  job: (id: string) => get<Job>(`/jobs/${encodeURIComponent(id)}`),
  // The running job, else the last one; null before any run (and always in the demo, which has no lab).
  currentJob: async () => (DEMO ? null : (await get<{ job: Job | null }>('/jobs/current')).job),

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

  // Logging in sets an HttpOnly session cookie: this code never sees the token, the browser sends it.
  auth: {
    me: async (): Promise<User | null> => {
      try { return await send<User>('GET', '/auth/me') } catch (e) { if (e instanceof ApiError && e.status === 401) return null; throw e }
    },
    login: (email: string, password: string) => send<User>('POST', '/auth/login', { email, password }),
    logout: () => send<void>('POST', '/auth/logout'),
  },

  // Saved plans live in the API's SQLite database, so the read-only demo has none.
  plans: {
    list: () => send<SavedPlan[]>('GET', '/plans'),
    get: (id: number) => send<SavedPlanFull>('GET', `/plans/${id}`),
    save: (name: string, plan: unknown, replace = false) => send<SavedPlan>('POST', '/plans', { name, plan, replace }),
    remove: (id: number) => send<void>('DELETE', `/plans/${id}`),
  },

  // Captures: start one (live on hwsim0, or an uploaded file), then poll get(id) until it ends.
  captures: {
    networks: () => send<{ ssid: string; security: string }[]>('GET', '/captures/networks'),
    list: () => send<CaptureListItem[]>('GET', '/captures'),
    current: async () => (await send<{ capture: CaptureJob | null }>('GET', '/captures/current')).capture,
    // The demo has one frozen, made-up example (public/demo/captures/sample.json).
    get: (id: string) => (DEMO ? get<CaptureJob>(`/captures/${encodeURIComponent(id)}`) : send<CaptureJob>('GET', `/captures/${encodeURIComponent(id)}`)),
    start: (seconds: number, decrypt: string | null) => send<CaptureJob>('POST', '/captures', { seconds, decrypt }),
    // The file goes as the raw request body: no form encoding, and the browser streams it.
    async upload(file: File, decrypt: string | null): Promise<CaptureJob> {
      const q = new URLSearchParams({ name: file.name, ...(decrypt ? { decrypt } : {}) })
      const res = await fetch(`/api/captures/upload?${q}`, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new ApiError(res.status, typeof data.detail === 'string' ? data.detail : `${res.status} ${res.statusText}`)
      return data as CaptureJob
    },
    pcapUrl: (id: string) => (DEMO ? null : `/api/captures/${encodeURIComponent(id)}/pcap`),
  },

  artifactUrl: (dir: string, name: string) =>
    DEMO ? null : `/api/artifacts/${encodeURIComponent(dir)}/${encodeURIComponent(name)}`,
}

// Test ids look like tests/test_failures.py::test_induced_failure[mac_blocked]; people want "induced_failure[mac_blocked]".
export const testName = (nodeid: string) => nodeid.split('::').slice(1).join('::').replace(/^test_/, '')

export const formatTime = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : 'never'
