// The indoor signal model shared by the coverage planner and the sites portal. It is a textbook
// formula, NOT a measurement: the lab's radios are emulated and have no real signal.
//
//   received (dBm) = transmit power - loss at 1 m - 10 * n * log10(distance in m) - walls crossed * loss per wall

export const W = 720 // drawing units; 40 per metre, so the house is 18 m x 12 m
export const H = 480
export const PX_PER_M = 40

export const BAND_MODEL = {
  '2.4': { label: '2.4 GHz', txDbm: 20, loss1m: 40, n: 3.0, wallDb: 5 },
  '5': { label: '5 GHz', txDbm: 20, loss1m: 47, n: 3.5, wallDb: 9 },
} as const
export type Band = keyof typeof BAND_MODEL

// Signal levels people use when planning Wi-Fi, strongest first.
export const LEVELS = [
  { min: -50, label: 'Excellent (≥ −50 dBm)', color: [16, 66, 129] },
  { min: -60, label: 'Very good (−50 to −60)', color: [42, 120, 214] },
  { min: -67, label: 'Good: video calls OK (−60 to −67)', color: [109, 167, 236] },
  { min: -75, label: 'Weak: browsing only (−67 to −75)', color: [183, 211, 246] },
  { min: -Infinity, label: 'Unusable (below −75)', color: null },
] as const
export const levelOf = (dbm: number) => LEVELS.findIndex((l) => dbm >= l.min)
export const GOOD_DBM = -67
export const USABLE_DBM = -75

// Walls in drawing units. Gaps between segments are doorways, which the signal passes without a wall loss.
export const WALLS: [number, number, number, number][] = [
  [20, 20, 700, 20], [700, 20, 700, 460], [700, 460, 390, 460], [330, 460, 20, 460], [20, 460, 20, 20], // outside, front door 330-390
  [260, 20, 260, 200], [260, 260, 260, 460], // living | kitchen and hall
  [460, 20, 460, 140], [460, 200, 460, 300], [460, 360, 460, 460], // kitchen and hall | bedrooms
  [460, 240, 700, 240], // bedroom | bedroom
  [20, 300, 200, 300], // living | office
]
// Floor areas: x, y, w, h, the floor finish and where the room name goes.
export const FLOORS = [
  { name: 'Living room', x: 20, y: 20, w: 240, h: 280, floor: 'wood', lx: 34, ly: 42 },
  { name: 'Office', x: 20, y: 300, w: 240, h: 160, floor: 'wood', lx: 34, ly: 322 },
  { name: 'Kitchen', x: 260, y: 20, w: 200, h: 220, floor: 'tile', lx: 274, ly: 76 },
  { name: 'Hall', x: 260, y: 240, w: 200, h: 220, floor: 'wood', lx: 274, ly: 262 },
  { name: 'Bedroom 1', x: 460, y: 20, w: 240, h: 220, floor: 'carpet', lx: 474, ly: 42 },
  { name: 'Bedroom 2', x: 460, y: 240, w: 240, h: 220, floor: 'carpet', lx: 474, ly: 262 },
]
export const roomAt = (x: number, y: number) =>
  FLOORS.find((f) => x >= f.x && x <= f.x + f.w && y >= f.y && y <= f.y + f.h)?.name ?? 'outside'

// A router, mesh point or device placed on the plan.
export interface Node { name: string; x: number; y: number; on: boolean; detail: string; bands?: string[]; icon: string }

const ICONS = ['phone', 'laptop', 'camera', 'plug', 'speaker', 'tv', 'tablet']
export const iconOf = (name: string) => ICONS.find((k) => name.toLowerCase().includes(k)) ?? 'generic'

export function wallsBetween(x0: number, y0: number, x1: number, y1: number) {
  let n = 0
  for (const [a, b, c, d] of WALLS) {
    const den = (x1 - x0) * (d - b) - (y1 - y0) * (c - a)
    if (den === 0) continue
    const t = ((a - x0) * (d - b) - (b - y0) * (c - a)) / den
    const u = ((a - x0) * (y1 - y0) - (b - y0) * (x1 - x0)) / den
    if (t > 0 && t < 1 && u >= 0 && u <= 1) n++
  }
  return n
}

export function rssi(ap: { x: number; y: number }, x: number, y: number, band: Band) {
  const m = BAND_MODEL[band]
  const d = Math.max(0.5, Math.hypot(ap.x - x, ap.y - y) / PX_PER_M)
  return m.txDbm - m.loss1m - 10 * m.n * Math.log10(d) - wallsBetween(ap.x, ap.y, x, y) * m.wallDb
}

export function best(aps: Node[], x: number, y: number, band: Band) {
  let top: { ap: Node; i: number; dbm: number } | null = null
  aps.forEach((ap, i) => {
    if (!ap.on) return
    const dbm = rssi(ap, x, y, band)
    if (!top || dbm > top.dbm) top = { ap, i, dbm }
  })
  return top as { ap: Node; i: number; dbm: number } | null
}

// The band a device would normally use: 5 GHz when it has a 5 GHz radio (less crowded), otherwise 2.4 GHz.
export const preferredBand = (d: Node): Band => (d.bands?.includes('5') ? '5' : '2.4')
