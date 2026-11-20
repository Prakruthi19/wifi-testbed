<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api, type Lab } from '../api'

// A what-if tool: place the router and mesh points in a house and see the signal strength each
// device would get. Signal comes from a textbook indoor model (log-distance path loss plus a fixed
// loss per wall), NOT from measurements: the lab's radios are emulated and have no real signal.
//
//   received (dBm) = transmit power - loss at 1 m - 10 * n * log10(distance in m) - walls crossed * loss per wall

const W = 720 // drawing units; 40 per metre, so the house is 18 m x 12 m
const H = 480
const PX_PER_M = 40
const CELL = 6 // heatmap resolution in drawing units

const BAND_MODEL = {
  '2.4': { label: '2.4 GHz', txDbm: 20, loss1m: 40, n: 3.0, wallDb: 5 },
  '5': { label: '5 GHz', txDbm: 20, loss1m: 47, n: 3.5, wallDb: 9 },
} as const
type Band = keyof typeof BAND_MODEL

// Signal levels people use when planning Wi-Fi, strongest first.
const LEVELS = [
  { min: -50, label: 'Excellent (≥ −50 dBm)', color: [16, 66, 129] },
  { min: -60, label: 'Very good (−50 to −60)', color: [42, 120, 214] },
  { min: -67, label: 'Good: video calls OK (−60 to −67)', color: [109, 167, 236] },
  { min: -75, label: 'Weak: browsing only (−67 to −75)', color: [183, 211, 246] },
  { min: -Infinity, label: 'Unusable (below −75)', color: null },
] as const
const levelOf = (dbm: number) => LEVELS.findIndex((l) => dbm >= l.min)

// Outer walls and rooms, in drawing units.
const WALLS: [number, number, number, number][] = [
  [20, 20, 700, 20], [700, 20, 700, 460], [700, 460, 20, 460], [20, 460, 20, 20], // outside
  [260, 20, 260, 200], [260, 260, 260, 460], // living | kitchen
  [460, 20, 460, 140], [460, 200, 460, 460], // kitchen | bedrooms
  [460, 240, 700, 240], // bedroom | bedroom
  [20, 300, 200, 300], // living | office
]
const ROOMS = [
  { name: 'Living room', x: 34, y: 42 },
  { name: 'Office', x: 34, y: 322 },
  { name: 'Kitchen', x: 274, y: 42 },
  { name: 'Bedroom 1', x: 474, y: 42 },
  { name: 'Bedroom 2', x: 474, y: 262 },
]

const SERIES = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)']
// The router starts where the internet line usually comes in (office corner); mesh points start in the hall.
const START_APS = [{ x: 70, y: 420 }, { x: 300, y: 330 }, { x: 430, y: 330 }]
const START_DEVICES = [
  { x: 150, y: 200 }, { x: 160, y: 400 }, { x: 620, y: 80 }, { x: 380, y: 110 }, { x: 600, y: 400 },
]

interface Node { name: string; x: number; y: number; on: boolean; detail: string; bands?: string[] }

const band = ref<Band>('2.4')
const aps = reactive<Node[]>([])
const devices = reactive<Node[]>([])
const cursor = ref<{ x: number; y: number } | null>(null)
const svg = ref<SVGSVGElement | null>(null)
const canvas = ref<HTMLCanvasElement | null>(null)
const dragging = ref<{ list: Node[]; i: number } | null>(null)

function reset(lab: Lab | null) {
  const home = lab?.home
  const apList = home?.access_points ?? [{ name: 'router', channel: 6 }, { name: 'mesh-living', channel: 1 }, { name: 'mesh-bedroom', channel: 11 }]
  const devList = home?.devices ?? []
  aps.splice(0, aps.length, ...apList.slice(0, 3).map((a, i) => ({ name: a.name, ...START_APS[i], on: true, detail: `channel ${a.channel}` })))
  devices.splice(0, devices.length, ...devList.slice(0, 5).map((d, i) => ({
    name: d.name, ...START_DEVICES[i], on: true, bands: d.bands, detail: `${d.profile}, radios: ${d.bands.join(' + ')} GHz`,
  })))
}

let lab: Lab | null = null
onMounted(async () => {
  try {
    lab = await api.lab()
  } catch {
    lab = null
  }
  reset(lab)
})

function wallsBetween(x0: number, y0: number, x1: number, y1: number) {
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

function rssi(ap: Node, x: number, y: number) {
  const m = BAND_MODEL[band.value]
  const d = Math.max(0.5, Math.hypot(ap.x - x, ap.y - y) / PX_PER_M)
  return m.txDbm - m.loss1m - 10 * m.n * Math.log10(d) - wallsBetween(ap.x, ap.y, x, y) * m.wallDb
}

function best(x: number, y: number) {
  let top: { ap: Node; i: number; dbm: number } | null = null
  aps.forEach((ap, i) => {
    if (!ap.on) return
    const dbm = rssi(ap, x, y)
    if (!top || dbm > top.dbm) top = { ap, i, dbm }
  })
  return top as { ap: Node; i: number; dbm: number } | null
}

function paint() {
  const el = canvas.value
  if (!el) return
  const cols = W / CELL
  const rows = H / CELL
  el.width = cols
  el.height = rows
  const ctx = el.getContext('2d')!
  const img = ctx.createImageData(cols, rows)
  for (let r = 0; r < rows; r++)
    for (let c = 0; c < cols; c++) {
      const x = c * CELL + CELL / 2
      const y = r * CELL + CELL / 2
      if (x < 20 || x > 700 || y < 20 || y > 460) continue
      const b = best(x, y)
      const color = b ? LEVELS[levelOf(b.dbm)].color : null
      if (!color) continue
      const k = 4 * (r * cols + c)
      img.data[k] = color[0]
      img.data[k + 1] = color[1]
      img.data[k + 2] = color[2]
      img.data[k + 3] = 150
    }
  ctx.putImageData(img, 0, 0)
}

watch([band, aps, () => canvas.value], paint, { deep: true })

const links = computed(() =>
  devices.map((d) => {
    const fiveOnly = band.value === '5' && d.bands && !d.bands.includes('5')
    const b = fiveOnly ? null : best(d.x, d.y)
    const usable = b && b.dbm >= -75
    return {
      d,
      b,
      text: fiveOnly ? 'no 5 GHz radio' : !b ? 'no AP on' : `${Math.round(b.dbm)} dBm via ${b.ap.name}`,
      usable,
    }
  }),
)

const coverage = computed(() => {
  const counts = LEVELS.map(() => 0)
  let total = 0
  for (let y = 26; y < 460; y += 12)
    for (let x = 26; x < 700; x += 12) {
      const b = best(x, y)
      counts[b ? levelOf(b.dbm) : LEVELS.length - 1]++
      total++
    }
  const good = counts.slice(0, 3).reduce((a, b) => a + b, 0)
  return Math.round((100 * good) / total)
})

const readout = computed(() => {
  if (!cursor.value) return null
  const { x, y } = cursor.value
  if (x < 20 || x > 700 || y < 20 || y > 460) return null
  const per = aps.filter((a) => a.on).map((a) => ({ name: a.name, dbm: Math.round(rssi(a, x, y)), walls: wallsBetween(a.x, a.y, x, y) }))
  return { per: per.sort((a, b) => b.dbm - a.dbm), where: `${(x / PX_PER_M).toFixed(1)} m, ${(y / PX_PER_M).toFixed(1)} m` }
})

function toSvg(e: PointerEvent) {
  const s = svg.value!
  const p = s.createSVGPoint()
  p.x = e.clientX
  p.y = e.clientY
  const q = p.matrixTransform(s.getScreenCTM()!.inverse())
  return { x: Math.min(696, Math.max(24, q.x)), y: Math.min(456, Math.max(24, q.y)) }
}
function down(list: Node[], i: number, e: PointerEvent) {
  dragging.value = { list, i }
  ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
}
function move(e: PointerEvent) {
  const p = toSvg(e)
  cursor.value = p
  if (dragging.value) Object.assign(dragging.value.list[dragging.value.i], p)
}
function nudge(n: Node, e: KeyboardEvent) {
  const step = e.shiftKey ? 40 : 10
  const dx = { ArrowLeft: -step, ArrowRight: step }[e.key] ?? 0
  const dy = { ArrowUp: -step, ArrowDown: step }[e.key] ?? 0
  if (!dx && !dy) return
  e.preventDefault()
  n.x = Math.min(696, Math.max(24, n.x + dx))
  n.y = Math.min(456, Math.max(24, n.y + dy))
}
</script>

<template>
  <h1>Coverage planner</h1>
  <p class="sub">
    Drag the router, mesh points and devices around the house. The colours show the modelled signal from the
    strongest access point. <b>This is a model, not a measurement:</b> the lab's radios are emulated, so it uses a
    standard indoor formula (distance loss plus {{ BAND_MODEL[band].wallDb }} dB per wall on {{ BAND_MODEL[band].label }}).
  </p>

  <div class="layout">
    <section class="card plan">
      <div class="toolbar">
        <div role="group" aria-label="Band" class="segs">
          <button v-for="b in (['2.4', '5'] as Band[])" :key="b" type="button" class="seg" :aria-pressed="band === b" @click="band = b">
            {{ BAND_MODEL[b].label }}
          </button>
        </div>
        <span class="stat"><b>{{ coverage }}%</b> of the house good enough for video calls</span>
        <button type="button" class="seg" @click="reset(lab)">Reset</button>
      </div>

      <div class="stage">
        <canvas ref="canvas" aria-hidden="true" />
        <svg
          ref="svg"
          :viewBox="`0 0 ${W} ${H}`"
          role="application"
          aria-label="Floor plan. Tab to a router or device and use the arrow keys to move it."
          @pointermove="move"
          @pointerup="dragging = null"
          @pointerleave="cursor = null"
        >
          <text v-for="r in ROOMS" :key="r.name" :x="r.x" :y="r.y" class="room">{{ r.name }}</text>
          <line v-for="(w, i) in WALLS" :key="i" :x1="w[0]" :y1="w[1]" :x2="w[2]" :y2="w[3]" class="wall" />

          <g v-for="l in links" :key="'l' + l.d.name">
            <line v-if="l.b" :x1="l.d.x" :y1="l.d.y" :x2="l.b.ap.x" :y2="l.b.ap.y" :stroke="SERIES[l.b.i]" class="link" :class="{ weak: !l.usable }" />
          </g>

          <g
            v-for="(d, i) in devices"
            :key="d.name"
            class="node device"
            :class="{ bad: !links[i]?.usable }"
            :transform="`translate(${d.x},${d.y})`"
            tabindex="0"
            :aria-label="`${d.name}: ${links[i]?.text}`"
            @pointerdown="down(devices, i, $event)"
            @keydown="nudge(d, $event)"
          >
            <rect x="-9" y="-9" width="18" height="18" rx="4" />
            <text y="24" text-anchor="middle" class="nlabel">{{ d.name }}</text>
            <text y="37" text-anchor="middle" class="nsub">{{ links[i]?.text }}</text>
          </g>

          <g
            v-for="(a, i) in aps"
            :key="a.name"
            class="node ap"
            :class="{ off: !a.on }"
            :transform="`translate(${a.x},${a.y})`"
            tabindex="0"
            :aria-label="`${a.name} (${a.detail}) ${a.on ? 'on' : 'off'}`"
            @pointerdown="down(aps, i, $event)"
            @keydown="nudge(a, $event)"
          >
            <circle r="13" :fill="SERIES[i]" />
            <path d="M-6,-2 a8,8 0 0,1 12,0 M-3,1 a4,4 0 0,1 6,0" class="glyph" />
            <circle r="1.6" cy="4" class="dot" />
            <text y="-19" text-anchor="middle" class="nlabel">{{ a.name }}</text>
          </g>
        </svg>
      </div>

      <p class="readout" aria-live="polite">
        <template v-if="readout">
          At {{ readout.where }}:
          <span v-for="p in readout.per" :key="p.name" class="per">{{ p.name }} {{ p.dbm }} dBm ({{ p.walls }} wall{{ p.walls === 1 ? '' : 's' }})</span>
        </template>
        <template v-else>Move the pointer over the house to read the modelled signal from each access point.</template>
      </p>
    </section>

    <aside class="side">
      <section class="card">
        <h2>Signal levels</h2>
        <ul class="legend">
          <li v-for="l in LEVELS" :key="l.label">
            <i :style="{ background: l.color ? `rgb(${l.color.join(',')})` : 'transparent' }" :class="{ empty: !l.color }" />
            {{ l.label }}
          </li>
        </ul>
      </section>
      <section class="card">
        <h2>Access points</h2>
        <p class="muted small">Switch one off to see what a "mesh point down" test covers.</p>
        <label v-for="(a, i) in aps" :key="a.name" class="toggle">
          <input v-model="a.on" type="checkbox" />
          <i :style="{ background: SERIES[i] }" />
          {{ a.name }} <span class="muted">{{ a.detail }}</span>
        </label>
      </section>
      <section class="card">
        <h2>Devices</h2>
        <ul class="devs">
          <li v-for="l in links" :key="l.d.name">
            <b>{{ l.d.name }}</b> <span :class="l.usable ? 'good' : 'badtxt'">{{ l.text }}</span>
            <div class="muted small">{{ l.d.detail }}</div>
          </li>
        </ul>
      </section>
    </aside>
  </div>
</template>

<style scoped>
.layout { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 16px; align-items: start; }
@media (max-width: 960px) { .layout { grid-template-columns: 1fr; } }
.toolbar { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center; margin-bottom: 10px; }
.segs { display: flex; gap: 4px; }
.seg { background: var(--bg); color: var(--ink); border: 1px solid var(--line); min-height: 36px; padding: 6px 12px; }
.seg[aria-pressed='true'] { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
.stat { flex: 1; font-size: 14px; }
.stat b { font-size: 18px; font-variant-numeric: tabular-nums; }
.stage { position: relative; width: 100%; aspect-ratio: 720 / 480; background: var(--bg); border-radius: 8px; overflow: hidden; }
.stage canvas, .stage svg { position: absolute; inset: 0; width: 100%; height: 100%; }
.stage svg { touch-action: none; }
.room { fill: var(--muted); font-size: 13px; pointer-events: none; }
.wall { stroke: var(--ink); stroke-width: 4; stroke-linecap: round; }
.link { stroke-width: 2; stroke-dasharray: 5 4; opacity: 0.9; pointer-events: none; }
.link.weak { opacity: 0.4; }
.node { cursor: grab; outline: none; }
.node:active { cursor: grabbing; }
.node:focus-visible rect, .node:focus-visible circle:first-child { stroke: var(--ink); stroke-width: 3; }
.device rect { fill: var(--card); stroke: var(--ink); stroke-width: 2; }
.device.bad rect { stroke: var(--fail); stroke-dasharray: 3 2; }
.ap circle:first-child { stroke: var(--card); stroke-width: 2; }
.ap.off { opacity: 0.35; }
.glyph { fill: none; stroke: #fff; stroke-width: 1.8; stroke-linecap: round; }
.dot { fill: #fff; }
.nlabel { fill: var(--ink); font-size: 12px; font-weight: 600; paint-order: stroke; stroke: var(--card); stroke-width: 3px; }
.nsub { fill: var(--ink); font-size: 11px; paint-order: stroke; stroke: var(--card); stroke-width: 3px; }
/* On phones the plan shrinks to ~40% size, so labels are drawn bigger and the per-device line moves to the list. */
@media (max-width: 640px) {
  .stat { order: 3; flex-basis: 100%; }
  .nlabel { font-size: 26px; stroke-width: 5px; }
  .nsub, .room { display: none; }
}
.readout { min-height: 1.5em; font-size: 14px; margin: 10px 0 0; }
.per { margin-left: 10px; white-space: nowrap; }
.legend, .devs { list-style: none; padding: 0; margin: 0; display: grid; gap: 6px; font-size: 14px; }
.legend i, .toggle i { width: 14px; height: 14px; border-radius: 3px; display: inline-block; vertical-align: -2px; margin-right: 6px; }
.legend i.empty { border: 1px dashed var(--muted); }
.toggle { display: flex; align-items: center; gap: 6px; font-size: 14px; padding: 4px 0; flex-wrap: wrap; }
.toggle input { width: 18px; height: 18px; }
.toggle i { margin-right: 0; border-radius: 50%; }
.small { font-size: 12px; margin: 2px 0 6px; }
.good { color: var(--pass); }
.badtxt { color: var(--fail); }
</style>
