// The network builder's data: home templates, access point models, the plan a person makes, and the
// checks run on it. Coverage uses the same textbook model as the coverage planner (rfmodel.ts):
// it is a model, NOT a measurement, and the AP models below are made up for the demo.
import { BAND_MODEL, FLOORS, GOOD_DBM, PX_PER_M, WALLS, rssi, type Band, type Wall } from './rfmodel'

export interface Room { name: string; x: number; y: number; w: number; h: number; floor: 'wood' | 'tile' | 'carpet'; lx: number; ly: number }
export interface Home { id: HomeId; name: string; size: string; walls: Wall[]; rooms: Room[]; bounds: { x0: number; y0: number; x1: number; y1: number } }
export type HomeId = 'apartment' | 'house' | 'office'

const room = (name: string, x: number, y: number, w: number, h: number, floor: Room['floor']): Room =>
  ({ name, x, y, w, h, floor, lx: x + 14, ly: y + 22 })

// Drawing units are 40 per metre on a 720 x 480 canvas, as in rfmodel.ts. Gaps in walls are doorways.
export const HOMES: Home[] = [
  {
    id: 'apartment', name: 'Apartment', size: '12 × 9 m, 5 rooms',
    bounds: { x0: 120, y0: 60, x1: 600, y1: 420 },
    walls: [
      [120, 60, 600, 60], [600, 60, 600, 420], [600, 420, 120, 420], [120, 420, 120, 60],
      [360, 60, 360, 140], [360, 200, 360, 300], [360, 360, 360, 420],
      [360, 240, 420, 240], [460, 240, 600, 240],
      [480, 240, 480, 320], [480, 370, 480, 420],
      [120, 300, 220, 300], [280, 300, 360, 300],
    ],
    rooms: [
      room('Living + kitchen', 120, 60, 240, 240, 'wood'), room('Hall', 120, 300, 240, 120, 'wood'),
      room('Bedroom', 360, 60, 240, 180, 'carpet'), room('Bathroom', 360, 240, 120, 180, 'tile'),
      room('Bedroom 2', 480, 240, 120, 180, 'carpet'),
    ],
  },
  {
    id: 'house', name: 'Family house', size: '17 × 11 m, 6 rooms',
    bounds: { x0: 20, y0: 20, x1: 700, y1: 460 },
    walls: WALLS,
    rooms: FLOORS.map((f) => ({ ...f, floor: f.floor as Room['floor'] })),
  },
  {
    id: 'office', name: 'Small office', size: '17 × 9 m, 5 rooms',
    bounds: { x0: 20, y0: 60, x1: 700, y1: 420 },
    walls: [
      [20, 60, 700, 60], [700, 60, 700, 420], [700, 420, 20, 420], [20, 420, 20, 60],
      [480, 60, 480, 110], [480, 160, 480, 230], [480, 270, 480, 350], [480, 390, 480, 420],
      [480, 200, 700, 200], [480, 300, 600, 300], [650, 300, 700, 300], [580, 300, 580, 420],
    ],
    rooms: [
      room('Open plan', 20, 60, 460, 360, 'carpet'), room('Meeting A', 480, 60, 220, 140, 'wood'),
      room('Meeting B', 480, 200, 220, 100, 'wood'), room('Server room', 480, 300, 100, 120, 'tile'),
      room('Kitchen', 580, 300, 120, 120, 'tile'),
    ],
  },
]
export const homeOf = (id: HomeId) => HOMES.find((h) => h.id === id) ?? HOMES[0]

// Made-up access point models: they differ in transmit power and in which bands they have.
export const MODELS = {
  compact: { name: 'Compact', txDelta: -3, bands: ['2.4'] as Band[], blurb: '2.4 GHz only, lower power' },
  standard: { name: 'Standard', txDelta: 0, bands: ['2.4', '5'] as Band[], blurb: 'Both bands' },
  longrange: { name: 'Long range', txDelta: 3, bands: ['2.4', '5'] as Band[], blurb: 'Both bands, +3 dB power' },
} as const
export type ModelId = keyof typeof MODELS

export const CHANNELS: Record<Band, number[]> = { '2.4': [1, 6, 11], '5': [36, 40, 44, 48, 149, 153, 157, 161] }
const AUTO: Record<Band, number[]> = { '2.4': [1, 6, 11], '5': [36, 149, 44, 157] } // spread out, no overlap
export const MAX_APS = 4
export const NAME_MAX = 20

export type BandChoice = 'both' | Band
export interface PlanAp { id: string; name: string; model: ModelId; band: BandChoice; ch: Record<Band, number | 'auto'>; x: number; y: number }
export interface Plan { home: HomeId; aps: PlanAp[] }

export const emptyPlan = (): Plan => ({ home: 'house', aps: [] })

// The bands an AP actually radiates on: what was picked, limited to what its model has.
export const bandsOf = (ap: PlanAp): Band[] =>
  (ap.band === 'both' ? (['2.4', '5'] as Band[]) : [ap.band]).filter((b) => (MODELS[ap.model].bands as readonly Band[]).includes(b))

export function channelOf(plan: Plan, ap: PlanAp, band: Band): number {
  const c = ap.ch[band]
  return c === 'auto' ? AUTO[band][plan.aps.indexOf(ap) % AUTO[band].length] : c
}

export function newAp(plan: Plan): PlanAp {
  const b = homeOf(plan.home).bounds
  const used = new Set(plan.aps.map((a) => a.name))
  let n = plan.aps.length + 1
  while (used.has(`AP ${n}`)) n++
  // Start each new AP at a different spot so they do not stack on top of each other.
  const spots = [[0.3, 0.35], [0.7, 0.65], [0.7, 0.3], [0.3, 0.7]]
  const [fx, fy] = spots[plan.aps.length % spots.length]
  return {
    id: Math.random().toString(36).slice(2, 8), name: `AP ${n}`, model: 'standard', band: 'both',
    ch: { '2.4': 'auto', '5': 'auto' },
    x: Math.round(b.x0 + (b.x1 - b.x0) * fx), y: Math.round(b.y0 + (b.y1 - b.y0) * fy),
  }
}

// -- checks ------------------------------------------------------------------------------------
// Errors stop the person moving on; warnings are advice.
export function fieldErrors(plan: Plan, ap: PlanAp): Partial<Record<'name' | 'band', string>> {
  const e: Partial<Record<'name' | 'band', string>> = {}
  const name = ap.name.trim()
  if (!name) e.name = 'Give this access point a name.'
  else if (name.length > NAME_MAX) e.name = `Keep the name to ${NAME_MAX} characters or fewer.`
  else if (plan.aps.some((o) => o !== ap && o.name.trim().toLowerCase() === name.toLowerCase())) e.name = 'Another access point already has this name.'
  if (!bandsOf(ap).length) e.band = `${MODELS[ap.model].name} has no 5 GHz radio. Pick 2.4 GHz or another model.`
  return e
}
export const planValid = (plan: Plan) => plan.aps.length > 0 && plan.aps.every((a) => !Object.keys(fieldErrors(plan, a)).length)

// Best signal at a point on one band, and which AP gives it.
export function bestAt(plan: Plan, x: number, y: number, band: Band) {
  const walls = homeOf(plan.home).walls
  let top: { ap: PlanAp; dbm: number } | null = null
  for (const ap of plan.aps) {
    if (!bandsOf(ap).includes(band)) continue
    const dbm = rssi(ap, x, y, band, walls, MODELS[ap.model].txDelta)
    if (!top || dbm > top.dbm) top = { ap, dbm }
  }
  return top
}

export interface RoomCoverage { room: string; band: Band; good: number; worst: number | null; by: string | null }
// Share of each room with a good signal (video calls work, ≥ −67 dBm), sampled every half metre.
export function roomCoverage(plan: Plan, band: Band): RoomCoverage[] {
  return homeOf(plan.home).rooms.map((r) => {
    let good = 0, n = 0, worst: number | null = null
    const by = new Map<string, number>()
    for (let x = r.x + 10; x < r.x + r.w; x += 20)
      for (let y = r.y + 10; y < r.y + r.h; y += 20) {
        const b = bestAt(plan, x, y, band)
        n++
        if (!b) continue
        if (b.dbm >= GOOD_DBM) good++
        worst = worst === null ? b.dbm : Math.min(worst, b.dbm)
        by.set(b.ap.name, (by.get(b.ap.name) ?? 0) + 1)
      }
    const main = [...by.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null
    return { room: r.name, band, good: n ? good / n : 0, worst, by: main }
  })
}

export interface Warning { kind: 'channel' | 'close' | 'weak'; text: string; aps: string[] }
export function warnings(plan: Plan): Warning[] {
  const out: Warning[] = []
  const aps = plan.aps
  for (let i = 0; i < aps.length; i++)
    for (let j = i + 1; j < aps.length; j++) {
      const a = aps[i], b = aps[j]
      for (const band of bandsOf(a).filter((x) => bandsOf(b).includes(x))) {
        const ca = channelOf(plan, a, band), cb = channelOf(plan, b, band)
        if (ca === cb) out.push({ kind: 'channel', aps: [a.id, b.id], text: `${a.name} and ${b.name} share channel ${ca} on ${BAND_MODEL[band].label}, so they slow each other down. Set one to another channel or Auto.` })
      }
      const m = Math.hypot(a.x - b.x, a.y - b.y) / PX_PER_M
      if (m < 4) out.push({ kind: 'close', aps: [a.id, b.id], text: `${a.name} and ${b.name} are ${m.toFixed(1)} m apart. Spread them out to cover more of the home.` })
    }
  for (const band of ['2.4', '5'] as Band[]) {
    if (!aps.some((a) => bandsOf(a).includes(band))) continue
    for (const r of roomCoverage(plan, band))
      if (r.good < 0.8) out.push({ kind: 'weak', aps: [], text: `${r.room}: only ${Math.round(r.good * 100)}% has a good ${BAND_MODEL[band].label} signal. Move an access point closer or add one.` })
  }
  return out
}

// -- share link ----------------------------------------------------------------------------------
// The whole plan fits in the URL, so a link opens the same plan on another device. Short keys keep it small.
export function encodePlan(plan: Plan): string {
  const compact = { h: plan.home, a: plan.aps.map((a) => [a.name, a.model, a.band, a.ch['2.4'], a.ch['5'], a.x, a.y]) }
  return btoa(unescape(encodeURIComponent(JSON.stringify(compact)))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

// One checker for both a shared link and an uploaded file: unknown values fall back to safe defaults,
// positions are kept inside the home, and at most MAX_APS access points are kept.
type RawAp = { name: unknown; model: unknown; band: unknown; ch24: unknown; ch5: unknown; x: unknown; y: unknown }
function sanitize(home: unknown, raw: RawAp[]): Plan | null {
  if (!HOMES.some((h) => h.id === home)) return null
  const b = homeOf(home as HomeId).bounds
  const clamp = (v: unknown, lo: number, hi: number) => Math.min(hi, Math.max(lo, Number(v) || lo))
  const chan = (v: unknown, band: Band) => (CHANNELS[band].includes(Number(v)) ? Number(v) : 'auto')
  const aps: PlanAp[] = raw.slice(0, MAX_APS).map((a, i) => ({
    id: `s${i}`, name: String(a.name ?? '').slice(0, 40),
    model: typeof a.model === 'string' && a.model in MODELS ? (a.model as ModelId) : 'standard',
    band: ['both', '2.4', '5'].includes(a.band as string) ? (a.band as BandChoice) : 'both',
    ch: { '2.4': chan(a.ch24, '2.4'), '5': chan(a.ch5, '5') },
    x: Math.round(clamp(a.x, b.x0, b.x1)), y: Math.round(clamp(a.y, b.y0, b.y1)),
  }))
  return { home: home as HomeId, aps }
}

// Anything wrong in a shared link (edited by hand, cut short) gives null instead of a broken plan.
export function decodePlan(text: string): Plan | null {
  try {
    const raw = JSON.parse(decodeURIComponent(escape(atob(text.replace(/-/g, '+').replace(/_/g, '/')))))
    if (!Array.isArray(raw.a)) return null
    return sanitize(raw.h, raw.a.map((a: unknown[]) => ({ name: a[0], model: a[1], band: a[2], ch24: a[3], ch5: a[4], x: a[5], y: a[6] })))
  } catch {
    return null
  }
}

// -- download and upload -------------------------------------------------------------------------
// A plan file is plain, readable JSON with positions in metres, so a person can open it and see what it says.
export const PLAN_FORMAT = 'wifi-plan'
export function planToFile(plan: Plan): string {
  const m = (v: number) => Math.round((v / PX_PER_M) * 10) / 10
  return JSON.stringify({
    format: PLAN_FORMAT, version: 1, home: plan.home,
    accessPoints: plan.aps.map((a) => ({ name: a.name, model: a.model, band: a.band, channel24: a.ch['2.4'], channel5: a.ch['5'], xMetres: m(a.x), yMetres: m(a.y) })),
  }, null, 2)
}

export function planFromFile(text: string): { plan: Plan; note?: string } | { error: string } {
  let raw: { format?: unknown; home?: unknown; accessPoints?: unknown }
  try { raw = JSON.parse(text) } catch { return { error: 'That file is not a plan: it is not valid JSON.' } }
  if (!raw || raw.format !== PLAN_FORMAT || !Array.isArray(raw.accessPoints)) return { error: 'That JSON file is not a Wi-Fi plan saved from this page.' }
  const list = raw.accessPoints as Record<string, unknown>[]
  const plan = sanitize(raw.home, list.map((a) => ({
    name: a?.name, model: a?.model, band: a?.band, ch24: a?.channel24, ch5: a?.channel5,
    x: Number(a?.xMetres) * PX_PER_M, y: Number(a?.yMetres) * PX_PER_M,
  })))
  if (!plan) return { error: `That plan is for a home this page does not have (${String(raw.home)}).` }
  return list.length > MAX_APS ? { plan, note: `Only the first ${MAX_APS} access points were loaded.` } : { plan }
}
