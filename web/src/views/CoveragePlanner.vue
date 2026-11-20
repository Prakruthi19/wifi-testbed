<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import WalkChart, { type WalkSample } from '../components/WalkChart.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { useSites } from '../stores/sites'
import {
  BAND_MODEL, FLOORS, GOOD_DBM, H, LEVELS, USABLE_DBM, PX_PER_M, W, WALLS, best as bestAt, levelOf, rssi as rssiAt, roomAt, wallsBetween,
  type Band, type Node,
} from '../rfmodel'

// A what-if tool: a furnished house where you place the router and mesh points, see the signal each
// device would get, and walk a phone through the rooms to watch it roam. Signal comes from a textbook
// indoor model (log-distance path loss plus a fixed loss per wall), NOT from measurements: the lab's
// radios are emulated and have no real signal.
//
//   received (dBm) = transmit power - loss at 1 m - 10 * n * log10(distance in m) - walls crossed * loss per wall

const CELL = 6 // heatmap resolution in drawing units

// Windows on the outside walls (x1, y1, x2, y2).
const WINDOWS: [number, number, number, number][] = [
  [20, 100, 20, 200], [90, 20, 200, 20], [520, 20, 640, 20], [700, 290, 700, 410], [480, 460, 560, 460], [100, 460, 20, 460],
]
// Doors: the hinge, the open leaf's end, and the end of the swing arc (on the closed position).
const DOORS = [
  { hinge: [260, 200], leaf: [200, 200], shut: [260, 260] },
  { hinge: [460, 140], leaf: [520, 140], shut: [460, 200] },
  { hinge: [460, 360], leaf: [520, 360], shut: [460, 300] },
  { hinge: [200, 300], leaf: [200, 360], shut: [260, 300] },
  { hinge: [330, 460], leaf: [330, 400], shut: [390, 460] },
].map((d) => ({ ...d, path: `M${d.hinge} L${d.leaf} A60,60 0 0,${sweep(d)} ${d.shut}` }))
function sweep(d: { hinge: number[]; leaf: number[]; shut: number[] }) {
  const [hx, hy] = d.hinge
  const cross = (d.leaf[0] - hx) * (d.shut[1] - hy) - (d.leaf[1] - hy) * (d.shut[0] - hx)
  return cross > 0 ? 1 : 0
}

const SERIES = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)']
const band = ref<Band>('2.4')
const showHeat = ref(true)
const props = defineProps<{ id?: string }>()
const store = useSites()
onMounted(store.load)
const siteId = computed(() => props.id ?? 'lab')
const site = computed(() => store.byId(siteId.value))
const health = computed(() => store.health[siteId.value] ?? null)
const aps = computed(() => site.value?.aps ?? [])
const devices = computed(() => site.value?.devices ?? [])
const cursor = ref<{ x: number; y: number } | null>(null)
const svg = ref<SVGSVGElement | null>(null)
const canvas = ref<HTMLCanvasElement | null>(null)
const dragging = ref<{ list: Node[]; i: number } | null>(null)

function reset() {
  stopWalk(true)
  store.resetSite(siteId.value)
}
watch(siteId, () => stopWalk(true))

const rssi = (ap: Node, x: number, y: number) => rssiAt(ap, x, y, band.value)
const best = (x: number, y: number) => bestAt(aps.value, x, y, band.value)
// Line style for a link: the same thresholds the Health card uses.
const tier = (dbm: number) => (dbm >= GOOD_DBM ? 'good' : dbm >= USABLE_DBM ? 'weak' : 'bad')
// A radio wave from device to access point. Its shape carries the strength as well as its colour:
// good = short, tight, steady waves; weak = long lazy waves; unusable = a flat, broken line.
const WAVE = { good: { len: 12, amp: 4 }, weak: { len: 28, amp: 7 }, bad: { len: 40, amp: 2 } } as const
function wave(x1: number, y1: number, x2: number, y2: number, dbm: number) {
  const { len, amp } = WAVE[tier(dbm)]
  const dx = x2 - x1
  const dy = y2 - y1
  const dist = Math.hypot(dx, dy) || 1
  const nx = -dy / dist // unit normal to the line
  const ny = dx / dist
  const steps = Math.max(8, Math.round(dist / 2))
  let d = ''
  for (let i = 0; i <= steps; i++) {
    const t = i / steps
    const off = amp * Math.sin(Math.PI * t) ** 0.5 * Math.sin((2 * Math.PI * t * dist) / len) // tapers to 0 at both ends
    d += `${i ? 'L' : 'M'}${(x1 + dx * t + nx * off).toFixed(1)},${(y1 + dy * t + ny * off).toFixed(1)}`
  }
  return d
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
      img.data[k + 3] = 95
    }
  ctx.putImageData(img, 0, 0)
}

watch([band, aps, () => canvas.value], paint, { deep: true })

// --- Walk the phone -------------------------------------------------------------------------------
// The phone follows a route through the doorways at walking pace. Like real phones it is "sticky": it
// keeps its access point until that one is weak AND another is clearly stronger. Real phones use
// vendor-specific rules; these two numbers are a simplified, typical version.
const ROAM_BELOW = -70
const ROAM_MARGIN = 8
const WALK_MPS = 1.2
const SAMPLE_S = 0.25
const ROUTE = [
  { x: 120, y: 370 }, { x: 230, y: 300 }, { x: 150, y: 235 }, { x: 260, y: 230 }, // office, living room
  { x: 360, y: 195 }, { x: 460, y: 170 }, { x: 540, y: 105 }, { x: 460, y: 170 }, // kitchen, bedroom 1
  { x: 420, y: 250 }, { x: 400, y: 380 }, { x: 460, y: 330 }, { x: 540, y: 400 }, // hall, bedroom 2
]
const legs = ROUTE.slice(1).map((p, i) => Math.hypot(p.x - ROUTE[i].x, p.y - ROUTE[i].y))
const ROUTE_LEN = legs.reduce((a, b) => a + b, 0)
const WALK_S = Math.ceil(ROUTE_LEN / PX_PER_M / WALK_MPS) + 1
const routePath = ROUTE.map((p, i) => `${i ? 'L' : 'M'}${p.x},${p.y}`).join(' ')

const speed = ref(1)
const walk = reactive({
  state: 'idle' as 'idle' | 'walking' | 'paused' | 'done',
  t: 0,
  dist: 0,
  ap: null as number | null,
  room: 'Office',
  samples: [] as WalkSample[],
  log: [] as { t: number; text: string; kind: 'roam' | 'info' }[],
  nextSample: 0,
})

function walkerPos(dist: number) {
  let left = dist
  for (let i = 0; i < legs.length; i++) {
    if (left <= legs[i] || i === legs.length - 1) {
      const f = Math.min(1, legs[i] ? left / legs[i] : 0)
      const a = ROUTE[i]
      const b = ROUTE[i + 1]
      const x = a.x + (b.x - a.x) * f
      const y = a.y + (b.y - a.y) * f
      return { x, y, room: roomAt(x, y) }
    }
    left -= legs[i]
  }
  return { x: 0, y: 0, room: 'outside' }
}
const walker = computed(() => walkerPos(walk.dist))

function sample() {
  const { x, y } = walker.value
  const name = (i: number) => aps.value[i].name
  const cur = walk.ap
  const top = best(x, y)
  if (!top) {
    if (cur !== null) walk.log.unshift({ t: walk.t, text: 'no access point is on: signal lost', kind: 'info' })
    walk.ap = null
    return
  }
  if (cur === null || !aps.value[cur].on) {
    walk.ap = top.i
    walk.log.unshift({ t: walk.t, text: `joined ${top.ap.name} at ${Math.round(top.dbm)} dBm`, kind: 'info' })
  } else {
    const now = rssi(aps.value[cur], x, y)
    if (now < ROAM_BELOW && top.i !== cur && top.dbm >= now + ROAM_MARGIN) {
      walk.log.unshift({ t: walk.t, text: `moved from ${name(cur)} (${Math.round(now)} dBm) to ${top.ap.name} (${Math.round(top.dbm)} dBm)`, kind: 'roam' })
      walk.ap = top.i
    }
  }
  walk.samples.push({ t: walk.t, dbm: rssi(aps.value[walk.ap!], x, y), ap: walk.ap! })
}

let raf = 0
let last = 0
function frame(now: number) {
  const dt = Math.min(0.1, (now - last) / 1000) * speed.value
  last = now
  walk.t += dt
  walk.dist = Math.min(ROUTE_LEN, walk.dist + WALK_MPS * PX_PER_M * dt)
  walk.room = walker.value.room
  while (walk.nextSample <= walk.t) {
    sample()
    walk.nextSample += SAMPLE_S
  }
  if (walk.dist >= ROUTE_LEN) {
    walk.state = 'done'
    walk.log.unshift({ t: walk.t, text: 'walk finished', kind: 'info' })
    return
  }
  raf = requestAnimationFrame(frame)
}
function startWalk() {
  if (walk.state === 'walking') {
    cancelAnimationFrame(raf)
    walk.state = 'paused'
    return
  }
  if (walk.state === 'done' || walk.state === 'idle') stopWalk(true)
  walk.state = 'walking'
  last = performance.now()
  raf = requestAnimationFrame(frame)
}
function stopWalk(clear: boolean) {
  cancelAnimationFrame(raf)
  if (!clear) return
  Object.assign(walk, { state: 'idle', t: 0, dist: 0, ap: null, room: 'Office', samples: [], log: [], nextSample: 0 })
}
onBeforeUnmount(() => stopWalk(false))
watch(band, () => {
  if (walk.state !== 'idle') walk.log.unshift({ t: walk.t, text: `switched to ${BAND_MODEL[band.value].label}`, kind: 'info' })
})

const walking = computed(() => walk.state !== 'idle')
const walkNow = computed(() => {
  const s = walk.samples.at(-1)
  return s ? { ...s, ap: aps.value[s.ap]?.name, color: SERIES[s.ap] } : null
})
const roams = computed(() => walk.log.filter((l) => l.kind === 'roam').length)
const apNames = computed(() => aps.value.map((a) => a.name))

// --- Static devices --------------------------------------------------------------------------------
// Each device's line and label use the band that device actually picks (the same rule as the Health
// card), so the map and the Health card always agree. The band buttons only change the floor colours.
const links = computed(() =>
  devices.value.map((d, i) => {
    const st = health.value?.devices[i]
    const hidden = walking.value && d.icon === 'phone' // the walking phone replaces the parked one
    const ap = aps.value.find((a) => a.name === st?.ap) ?? null
    const b = ap && st?.dbm != null ? { ap, dbm: st.dbm } : null
    const dbm = b ? `${Math.round(b.dbm)} dBm on ${st!.band} GHz` : ''
    const text = !st || st.state === 'not seen' ? 'offline (not seen)'
      : !b ? 'no access point on'
      : st.state === 'no internet' ? `${dbm}, but no internet (router off)`
      : `${dbm} via ${ap!.name}`
    return { d, b, text, usable: !!b && b.dbm >= USABLE_DBM && st!.state !== 'no internet', hidden }
  }),
)

// Labels near the left or right wall grow inwards so they are never cut off at the edge.
const labelAnchor = (x: number) => (x < 140 ? 'start' : x > 580 ? 'end' : 'middle')
const labelX = (x: number) => (x < 140 ? -15 : x > 580 ? 15 : 0)

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
  const per = aps.value.filter((a) => a.on).map((a) => ({ name: a.name, dbm: Math.round(rssi(a, x, y)), walls: wallsBetween(a.x, a.y, x, y) }))
  return { per: per.sort((a, b) => b.dbm - a.dbm), where: roomAt(x, y) }
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
  <RouterLink v-if="props.id" to="/sites" class="back">← All sites</RouterLink>
  <div class="titlerow">
    <h1>{{ props.id && site ? site.name : 'Coverage planner' }}</h1>
    <StatusBadge v-if="health" :status="health.status" />
    <span v-if="site?.simulated" class="simtag">Simulated site</span>
    <span v-if="site" class="muted">{{ site.area }}</span>
  </div>
  <p class="sub">
    A furnished floor plan of {{ site?.simulated ? 'this simulated home' : "the lab's home network" }}. Drag the router, mesh points and devices, switch access points
    off, or walk the phone through the rooms and watch it change access point. <b>This is a model, not a
    measurement:</b> the lab's radios are emulated, so the signal comes from a standard indoor formula (distance loss
    plus {{ BAND_MODEL[band].wallDb }} dB per wall on {{ BAND_MODEL[band].label }}).
  </p>

  <div class="layout">
    <div>
      <section class="card plan">
        <div class="toolbar">
          <span class="seglabel" id="floor-band">Floor colours:</span>
          <div role="group" aria-labelledby="floor-band" class="segs">
            <button v-for="b in (['2.4', '5'] as Band[])" :key="b" type="button" class="seg" :aria-pressed="band === b" @click="band = b">
              {{ BAND_MODEL[b].label }}
            </button>
          </div>
          <label class="check"><input v-model="showHeat" type="checkbox" /> Signal colours</label>
          <span class="stat"><b>{{ coverage }}%</b> of the house good enough for video calls</span>
          <button type="button" class="seg" @click="reset">Reset</button>
        </div>

        <div class="stage">
          <!-- floor: room finishes, drawn under the signal colours -->
          <svg :viewBox="`0 0 ${W} ${H}`" aria-hidden="true" class="floor">
            <defs>
              <pattern id="wood" width="60" height="14" patternUnits="userSpaceOnUse">
                <rect width="60" height="14" fill="var(--floor-wood)" />
                <path d="M0,13.5 H60 M38,0 V14" stroke="var(--floor-wood-line)" stroke-width="1" />
              </pattern>
              <pattern id="tile" width="20" height="20" patternUnits="userSpaceOnUse">
                <rect width="20" height="20" fill="var(--floor-tile)" />
                <path d="M0,19.5 H20 M19.5,0 V20" stroke="var(--floor-tile-line)" stroke-width="1" />
              </pattern>
            </defs>
            <rect x="0" y="0" :width="W" :height="H" class="yard" />
            <rect v-for="f in FLOORS" :key="f.name" :x="f.x" :y="f.y" :width="f.w" :height="f.h" :fill="f.floor === 'carpet' ? 'var(--floor-carpet)' : `url(#${f.floor})`" />
          </svg>

          <canvas v-show="showHeat" ref="canvas" aria-hidden="true" />

          <svg
            ref="svg"
            :viewBox="`0 0 ${W} ${H}`"
            role="application"
            aria-label="Floor plan. Tab to a router or device and use the arrow keys to move it."
            @pointermove="move"
            @pointerup="dragging = null"
            @pointerleave="cursor = null"
          >
            <!-- furniture -->
            <g class="furn" aria-hidden="true">
              <!-- living room: sofa, coffee table, rug, TV -->
              <ellipse cx="150" cy="165" rx="70" ry="52" class="rug" />
              <rect x="34" y="108" width="40" height="114" rx="8" /><rect x="34" y="108" width="14" height="114" rx="6" />
              <rect x="120" y="142" width="58" height="40" rx="4" />
              <rect x="244" y="112" width="9" height="78" rx="2" class="dark" />
              <!-- office: desk, chair, bookshelf -->
              <rect x="30" y="404" width="128" height="46" rx="3" />
              <circle cx="110" cy="386" r="11" />
              <rect x="186" y="438" width="66" height="14" rx="2" />
              <!-- kitchen: counters, sink, hob, fridge, island -->
              <rect x="270" y="26" width="146" height="28" rx="2" />
              <rect x="296" y="32" width="26" height="16" rx="5" class="sink" />
              <circle cx="360" cy="40" r="5" class="dark" /><circle cx="378" cy="40" r="5" class="dark" />
              <rect x="420" y="26" width="34" height="36" rx="3" />
              <rect x="322" y="120" width="88" height="40" rx="4" />
              <!-- hall: dining table and chairs, shoe rack by the front door -->
              <rect x="296" y="284" width="82" height="46" rx="6" />
              <circle cx="316" cy="276" r="7" /><circle cx="358" cy="276" r="7" /><circle cx="316" cy="338" r="7" /><circle cx="358" cy="338" r="7" />
              <rect x="400" y="444" width="44" height="10" rx="2" />
              <!-- bedroom 1: bed, pillows, nightstand, wardrobe -->
              <rect x="586" y="36" width="104" height="132" rx="6" />
              <rect x="592" y="42" width="42" height="22" rx="5" class="pillow" /><rect x="642" y="42" width="42" height="22" rx="5" class="pillow" />
              <rect x="560" y="36" width="22" height="22" rx="2" />
              <rect x="470" y="200" width="80" height="30" rx="2" />
              <!-- bedroom 2: bed, pillow, desk -->
              <rect x="590" y="300" width="96" height="136" rx="6" />
              <rect x="598" y="306" width="80" height="22" rx="5" class="pillow" />
              <rect x="472" y="420" width="76" height="28" rx="2" />
            </g>

            <text v-for="r in FLOORS" :key="r.name" :x="r.lx" :y="r.ly" class="room">{{ r.name }}</text>

            <line v-for="(w, i) in WALLS" :key="i" :x1="w[0]" :y1="w[1]" :x2="w[2]" :y2="w[3]" class="wall" />
            <g v-for="(w, i) in WINDOWS" :key="'w' + i" aria-hidden="true">
              <line :x1="w[0]" :y1="w[1]" :x2="w[2]" :y2="w[3]" class="win-gap" />
              <line :x1="w[0]" :y1="w[1]" :x2="w[2]" :y2="w[3]" class="win" />
            </g>
            <path v-for="(d, i) in DOORS" :key="'d' + i" :d="d.path" class="door" aria-hidden="true" />

            <!-- links from each parked device to the AP it would use -->
            <template v-for="l in links" :key="'l' + l.d.name">
              <path v-if="l.b && !l.hidden" :d="wave(l.d.x, l.d.y, l.b.ap.x, l.b.ap.y, l.b.dbm)" class="link" :class="tier(l.b.dbm)" />
            </template>

            <g
              v-for="(d, i) in devices"
              v-show="!links[i]?.hidden"
              :key="d.name"
              class="node device"
              :class="{ bad: !links[i]?.usable, off: !d.on }"
              :transform="`translate(${d.x},${d.y})`"
              tabindex="0"
              :aria-label="`${d.name}: ${links[i]?.text}`"
              @pointerdown="down(devices, i, $event)"
              @keydown="nudge(d, $event)"
            >
              <circle r="15" class="badge" />
              <g class="icon">
                <template v-if="d.icon === 'phone'"><rect x="-5" y="-9" width="10" height="18" rx="2" /><line x1="-1.5" y1="6" x2="1.5" y2="6" /></template>
                <template v-else-if="d.icon === 'laptop'"><rect x="-7" y="-7" width="14" height="10" rx="1" /><path d="M-10,6 H10 L8,8 H-8 Z" /></template>
                <template v-else-if="d.icon === 'camera'"><rect x="-9" y="-6" width="14" height="11" rx="2" /><path d="M5,-2 L10,-5 V4 L5,1" /><circle cx="-2" cy="-0.5" r="2.5" /></template>
                <template v-else-if="d.icon === 'plug'"><rect x="-6" y="-6" width="12" height="13" rx="3" /><line x1="-2.5" y1="-6" x2="-2.5" y2="-10" /><line x1="2.5" y1="-6" x2="2.5" y2="-10" /></template>
                <template v-else-if="d.icon === 'speaker'"><rect x="-6" y="-9" width="12" height="18" rx="3" /><circle cy="3" r="3" /><circle cy="-4.5" r="1.2" /></template>
                <template v-else-if="d.icon === 'tv'"><rect x="-10" y="-8" width="20" height="13" rx="1.5" /><line x1="-5" y1="9" x2="5" y2="9" /><line x1="0" y1="5" x2="0" y2="9" /></template>
                <template v-else-if="d.icon === 'tablet'"><rect x="-7" y="-9" width="14" height="18" rx="2" /><circle cy="6" r="0.8" /></template>
                <rect v-else x="-6" y="-6" width="12" height="12" rx="2" />
              </g>
              <text y="28" :x="labelX(d.x)" :text-anchor="labelAnchor(d.x)" class="nlabel">{{ d.name }}</text>
              <text y="41" :x="labelX(d.x)" :text-anchor="labelAnchor(d.x)" class="nsub">{{ links[i]?.text }}</text>
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
              <circle v-if="a.on" r="13" :stroke="SERIES[i]" class="ripple" />
              <circle v-if="a.on" r="13" :stroke="SERIES[i]" class="ripple late" />
              <circle r="13" :fill="SERIES[i]" class="apdot" />
              <path d="M-6,-2 a8,8 0 0,1 12,0 M-3,1 a4,4 0 0,1 6,0" class="glyph" />
              <circle r="1.6" cy="4" class="dot" />
              <text y="-19" text-anchor="middle" class="nlabel">{{ a.name }}</text>
            </g>

            <!-- the walking phone -->
            <g v-if="walking" aria-hidden="true">
              <path :d="routePath" class="route" />
              <path v-if="walk.ap !== null && aps[walk.ap]" :d="wave(walker.x, walker.y, aps[walk.ap].x, aps[walk.ap].y, walkNow?.dbm ?? -99)" class="link live" :class="tier(walkNow?.dbm ?? -99)" />
              <g :transform="`translate(${walker.x},${walker.y})`" class="walker">
                <circle r="16" :fill="walk.ap !== null ? SERIES[walk.ap] : 'var(--muted)'" />
                <rect x="-5" y="-9" width="10" height="18" rx="2" class="wphone" />
                <text y="30" text-anchor="middle" class="nlabel">you + phone</text>
              </g>
            </g>
          </svg>
        </div>

        <p class="readout" aria-live="polite">
          <template v-if="readout">
            {{ readout.where }}:
            <span v-for="p in readout.per" :key="p.name" class="per">{{ p.name }} {{ p.dbm }} dBm ({{ p.walls }} wall{{ p.walls === 1 ? '' : 's' }})</span>
          </template>
          <template v-else>Move the pointer over the house to read the modelled signal from each access point.</template>
        </p>
      </section>

      <section class="card walkcard" aria-labelledby="walk-h">
        <div class="walkhead">
          <h2 id="walk-h">Walk the phone</h2>
          <button type="button" class="primary" @click="startWalk">
            {{ walk.state === 'walking' ? '❚❚ Pause' : walk.state === 'paused' ? '▶ Keep walking' : walk.state === 'done' ? '↺ Walk again' : '▶ Walk the phone' }}
          </button>
          <div role="group" aria-label="Walking speed" class="segs">
            <button v-for="s in [1, 3, 10]" :key="s" type="button" class="seg" :aria-pressed="speed === s" @click="speed = s">{{ s }}×</button>
          </div>
        </div>
        <p class="muted small rule">
          The phone walks from the office through every room at {{ WALK_MPS }} m/s. Like a real phone it is sticky: it
          keeps its access point until that signal drops below {{ ROAM_BELOW }} dBm <i>and</i> another one is at least
          {{ ROAM_MARGIN }} dB stronger. Real phones each use their own rules; this is a simplified, typical one. Try it on
          both bands, or switch a mesh point off first.
        </p>

        <div class="now" aria-live="polite">
          <template v-if="walkNow">
            <span><span class="k">Room</span> {{ walk.room }}</span>
            <span><span class="k">Connected to</span> <i class="sw" :style="{ background: walkNow.color }" /> {{ walkNow.ap }}</span>
            <span><span class="k">Signal</span> {{ Math.round(walkNow.dbm) }} dBm</span>
            <span><span class="k">Roams</span> {{ roams }}</span>
          </template>
          <template v-else-if="walking">The phone has no access point to join.</template>
        </div>

        <div class="walkbody">
          <WalkChart :samples="walk.samples" :ap-names="apNames" :colors="SERIES" :window-s="WALK_S" />
          <div>
            <p v-if="walk.state === 'done' && !roams" class="note">
              The phone never changed access point: its signal never fell below {{ ROAM_BELOW }} dBm, so the sticky rule kept
              it on {{ walk.ap !== null ? aps[walk.ap]?.name : 'the first one' }} the whole way. That is the "sticky client"
              problem real homes have. Try 5 GHz, where walls cost more.
            </p>
            <ol v-if="walk.log.length" class="log" aria-label="What happened on the walk, newest first">
              <li v-for="(l, i) in walk.log.slice(0, 8)" :key="walk.log.length - i" :class="l.kind">
                <span class="ts">{{ l.t.toFixed(1) }} s</span> {{ l.text }}
              </li>
            </ol>
            <p v-else class="muted small">Every join and change of access point will be listed here.</p>
          </div>
        </div>
      </section>
    </div>

    <aside class="side">
      <section v-if="health" class="card">
        <h2>Health</h2>
        <p v-if="!health.issues.length" class="good">No problems: every access point is on and every device has a good signal.</p>
        <ul v-else class="issues">
          <li v-for="i in health.issues" :key="i.key" :class="i.severity">{{ i.text }}</li>
        </ul>
        <p class="muted small">
          Status comes from the model, not real radios. Devices with a 5 GHz radio use 5 GHz while it is −72 dBm or better and
          fall back to 2.4 GHz otherwise. The lines on the map use the same band as this card; the band buttons only change
          the floor colours. Switch boxes on and off here; the <RouterLink to="/sites">Sites</RouterLink> page updates too.
        </p>
      </section>
      <section class="card">
        <h2>Signal waves</h2>
        <p class="muted small">Each device sends a wave to the access point it uses. The wave's shape and colour show how strong that signal is.</p>
        <ul class="linekey key">
          <li><svg viewBox="0 0 48 16" aria-hidden="true"><path :d="wave(2, 8, 46, 8, -50)" class="good" /></svg>Good: tight waves, −67 dBm or stronger</li>
          <li><svg viewBox="0 0 48 16" aria-hidden="true"><path :d="wave(2, 8, 46, 8, -70)" class="weak" /></svg>Weak: long waves, −67 to −75 dBm</li>
          <li><svg viewBox="0 0 48 16" aria-hidden="true"><path :d="wave(2, 8, 46, 8, -90)" class="bad" /></svg>Unusable: flat, broken, below −75 dBm</li>
        </ul>
        <h2 class="spaced">Signal levels</h2>
        <p class="muted small">dBm is the received signal power; closer to 0 is stronger, and every 10 dB less is ten times weaker.</p>
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
            <b>{{ l.d.name }}</b>{{ " " }}
            <span v-if="l.hidden" class="muted">walking (see below the plan)</span>
            <span v-else :class="l.usable ? 'good' : 'badtxt'">{{ l.text }}</span>
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
.seglabel { font-size: 14px; color: var(--muted); }
.segs { display: flex; gap: 4px; }
.seg { background: var(--bg); color: var(--ink); border: 1px solid var(--line); min-height: 36px; padding: 6px 12px; }
.seg[aria-pressed='true'] { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
.check { display: inline-flex; align-items: center; gap: 6px; font-size: 14px; }
.check input { width: 18px; height: 18px; }
.stat { flex: 1; font-size: 14px; }
.stat b { font-size: 18px; font-variant-numeric: tabular-nums; }
.stage { position: relative; width: 100%; aspect-ratio: 720 / 480; border-radius: 8px; overflow: hidden; }
.stage canvas, .stage svg { position: absolute; inset: 0; width: 100%; height: 100%; }
.stage svg { touch-action: none; }
.yard { fill: var(--bg); }
.furn rect, .furn circle, .furn ellipse { fill: var(--furniture); stroke: var(--furniture-edge); stroke-width: 1.2; pointer-events: none; }
.furn .rug { fill: var(--floor-carpet); opacity: 0.8; }
.furn .dark { fill: var(--furniture-edge); }
.furn .pillow { fill: var(--card); }
.furn .sink { fill: var(--floor-tile); }
.room { fill: var(--muted); font-size: 13px; font-weight: 600; pointer-events: none; paint-order: stroke; stroke: var(--card); stroke-width: 3px; }
.wall { stroke: var(--ink); stroke-width: 6; stroke-linecap: square; }
.win-gap { stroke: var(--card); stroke-width: 4; }
.win { stroke: var(--window); stroke-width: 2; }
.door { fill: none; stroke: var(--muted); stroke-width: 1.2; stroke-dasharray: 3 3; pointer-events: none; }
.link, .key path { fill: none; stroke-linecap: round; stroke-linejoin: round; }
.link { pointer-events: none; animation: flow 1.2s linear infinite; }
.link.good, .key .good { stroke: var(--pass); stroke-width: 2.5; stroke-dasharray: 18 4; }
.link.weak, .key .weak { stroke: var(--skip); stroke-width: 2.5; stroke-dasharray: 10 6; }
.link.bad, .key .bad { stroke: var(--fail); stroke-width: 2.5; stroke-dasharray: 3 7; }
.link.live { stroke-width: 4; }
.linekey { list-style: none; padding: 0; margin: 0; display: grid; gap: 6px; font-size: 14px; }
.linekey svg { width: 48px; height: 16px; vertical-align: middle; margin-right: 8px; }
@keyframes flow { to { stroke-dashoffset: -22; } }
@keyframes flow-weak { to { stroke-dashoffset: -16; } }
@keyframes flow-bad { to { stroke-dashoffset: -10; } }
.link.weak { animation: flow-weak 1.6s linear infinite; }
.link.bad { animation: flow-bad 2s linear infinite; }
.node { cursor: grab; outline: none; }
.node:active { cursor: grabbing; }
.node:focus-visible .badge, .node:focus-visible .apdot { stroke: var(--ink); stroke-width: 3; }
.badge { fill: var(--card); stroke: var(--ink); stroke-width: 1.5; }
.device.off { opacity: 0.4; }
.device.bad .badge { stroke: var(--fail); stroke-width: 2; stroke-dasharray: 3 2; }
.icon * { fill: none; stroke: var(--ink); stroke-width: 1.6; stroke-linejoin: round; stroke-linecap: round; }
.apdot { stroke: var(--card); stroke-width: 2; }
.ripple { fill: none; stroke-width: 2; transform-box: fill-box; transform-origin: center; animation: ripple 2.4s ease-out infinite; pointer-events: none; }
.ripple.late { animation-delay: 1.2s; }
@keyframes ripple { from { transform: scale(1); opacity: 0.6; } to { transform: scale(3.2); opacity: 0; } }
.ap.off { opacity: 0.35; }
.glyph { fill: none; stroke: #fff; stroke-width: 1.8; stroke-linecap: round; }
.dot { fill: #fff; }
.route { fill: none; stroke: var(--ink); stroke-width: 1.5; stroke-dasharray: 2 6; opacity: 0.5; stroke-linecap: round; }
.walker circle { stroke: var(--card); stroke-width: 3; }
.wphone { fill: var(--card); stroke: var(--ink); stroke-width: 1.5; }
.nlabel { fill: var(--ink); font-size: 12px; font-weight: 600; paint-order: stroke; stroke: var(--card); stroke-width: 3px; }
.nsub { fill: var(--ink); font-size: 11px; paint-order: stroke; stroke: var(--card); stroke-width: 3px; }
@media (prefers-reduced-motion: reduce) {
  .ripple { display: none; }
  .link, .link.weak, .link.bad { animation: none; }
}
/* On phones the plan shrinks to ~40% size, so labels are drawn bigger and the per-device line moves to the list. */
@media (max-width: 640px) {
  .stat { order: 3; flex-basis: 100%; }
  .nlabel { font-size: 24px; stroke-width: 5px; }
  .nsub, .room { display: none; }
}
.readout { min-height: 1.5em; font-size: 14px; margin: 10px 0 0; }
.per { margin-left: 10px; white-space: nowrap; }
.walkhead { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; }
.walkhead h2 { margin: 0; flex: 1; min-width: 160px; }
.rule { margin: 8px 0 10px; }
.now { display: flex; flex-wrap: wrap; gap: 4px 20px; font-size: 14px; min-height: 1.5em; margin-bottom: 6px; }
.now .k { color: var(--muted); font-size: 12px; margin-right: 4px; }
.sw { width: 10px; height: 10px; border-radius: 50%; display: inline-block; vertical-align: 0; }
.walkbody { display: grid; grid-template-columns: minmax(0, 1fr) minmax(240px, 34%); gap: 16px; align-items: start; }
@media (max-width: 720px) { .walkbody { grid-template-columns: 1fr; } }
.note { font-size: 13px; margin: 0 0 8px; padding: 8px; border-radius: 6px; background: var(--skip-bg); }
.log { list-style: none; padding: 0; margin: 0; font-size: 13px; display: grid; gap: 4px; }
.log li { padding: 4px 8px; border-radius: 6px; background: var(--bg); }
.log li.roam { background: var(--skip-bg); }
.log .ts { font-variant-numeric: tabular-nums; color: var(--muted); margin-right: 6px; }
.spaced { margin-top: 18px; }
.back { display: inline-block; margin-bottom: 6px; font-size: 14px; }
.titlerow { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 12px; }
.titlerow h1 { margin: 0; }
.simtag { font-size: 12px; border: 1px dashed var(--muted); color: var(--muted); border-radius: 999px; padding: 1px 8px; }
.issues { list-style: none; padding: 0; margin: 0 0 8px; display: grid; gap: 6px; font-size: 14px; }
.issues li { padding: 6px 8px; border-radius: 6px; border-left: 4px solid var(--skip); background: var(--skip-bg); }
.issues li.problem, .issues li.offline { border-color: var(--fail); background: var(--fail-bg); }
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
