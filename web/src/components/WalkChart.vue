<script setup lang="ts">
import { computed, ref } from 'vue'

// Live signal of the walking phone: time across, dBm up, the line coloured by the access point the
// phone was connected to at that moment, so every roam shows up as a colour change.
export interface WalkSample { t: number; dbm: number; ap: number }

const props = defineProps<{ samples: WalkSample[]; apNames: string[]; colors: string[]; windowS?: number }>()

const W = 560
const H = 180
const PAD = { l: 40, r: 12, t: 12, b: 26 }
const MIN = -90
const MAX = -30
const span = computed(() => props.windowS ?? 40)
const t1 = computed(() => Math.max(span.value, props.samples.at(-1)?.t ?? 0))
const t0 = computed(() => t1.value - span.value)
const x = (t: number) => PAD.l + ((t - t0.value) / span.value) * (W - PAD.l - PAD.r)
const y = (d: number) => PAD.t + ((MAX - Math.max(MIN, Math.min(MAX, d))) / (MAX - MIN)) * (H - PAD.t - PAD.b)

// One polyline per run of samples on the same AP (consecutive runs share an end point so the line is unbroken).
const runs = computed(() => {
  const vis = props.samples.filter((s) => s.t >= t0.value)
  const out: { ap: number; pts: string }[] = []
  let cur: WalkSample[] = []
  vis.forEach((s, i) => {
    if (cur.length && s.ap !== cur[0].ap) {
      cur.push(s)
      out.push({ ap: cur[0].ap, pts: cur.map((p) => `${x(p.t)},${y(p.dbm)}`).join(' ') })
      cur = []
    }
    cur.push(s)
    if (i === vis.length - 1) out.push({ ap: cur[0].ap, pts: cur.map((p) => `${x(p.t)},${y(p.dbm)}`).join(' ') })
  })
  return out
})
const ticksY = [-40, -50, -60, -67, -75, -90]
const ticksX = computed(() => {
  const step = 10
  const first = Math.ceil(t0.value / step) * step
  return Array.from({ length: Math.floor((t1.value - first) / step) + 1 }, (_, i) => first + i * step)
})

const hover = ref<WalkSample | null>(null)
function onMove(e: PointerEvent) {
  const svg = e.currentTarget as SVGSVGElement
  const r = svg.getBoundingClientRect()
  const t = t0.value + (((e.clientX - r.left) / r.width) * W - PAD.l) / (W - PAD.l - PAD.r) * span.value
  let best: WalkSample | null = null
  for (const s of props.samples) if (!best || Math.abs(s.t - t) < Math.abs(best.t - t)) best = s
  hover.value = best && best.t >= t0.value ? best : null
}
const used = computed(() => [...new Set(props.samples.map((s) => s.ap))].sort())
</script>

<template>
  <div>
    <div class="legend">
      <span v-for="i in used" :key="i"><i :style="{ background: colors[i] }" />{{ apNames[i] }}</span>
    </div>
    <svg :viewBox="`0 0 ${W} ${H}`" role="img" aria-label="Signal of the walking phone over time" @pointermove="onMove" @pointerleave="hover = null">
      <g v-for="v in ticksY" :key="v">
        <line :x1="PAD.l" :x2="W - PAD.r" :y1="y(v)" :y2="y(v)" :class="v === -67 ? 'thr' : 'grid'" />
        <text :x="PAD.l - 6" :y="y(v) + 4" text-anchor="end" class="tick">{{ v }}</text>
      </g>
      <text :x="W - PAD.r" :y="y(-67) - 4" text-anchor="end" class="thrlabel">video calls OK above this line</text>
      <text v-for="t in ticksX" :key="t" :x="x(t)" :y="H - 8" text-anchor="middle" class="tick">{{ t }} s</text>
      <polyline v-for="(r, i) in runs" :key="i" :points="r.pts" :stroke="colors[r.ap]" class="line" />
      <template v-if="hover">
        <line :x1="x(hover.t)" :x2="x(hover.t)" :y1="PAD.t" :y2="H - PAD.b" class="cross" />
        <circle :cx="x(hover.t)" :cy="y(hover.dbm)" r="5" :fill="colors[hover.ap]" class="ring" />
      </template>
    </svg>
    <p class="tip" aria-live="polite">
      <template v-if="hover">{{ hover.t.toFixed(1) }} s: <b>{{ Math.round(hover.dbm) }} dBm</b> from {{ apNames[hover.ap] }}</template>
      <template v-else-if="samples.length">Hover the line to read any moment.</template>
      <template v-else>Press "Walk the phone" to start.</template>
    </p>
  </div>
</template>

<style scoped>
svg { width: 100%; height: auto; display: block; }
.grid { stroke: var(--line); }
.thr { stroke: var(--muted); stroke-dasharray: 4 4; }
.thrlabel, .tick { fill: var(--muted); font-size: 11px; }
.line { fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
.cross { stroke: var(--muted); }
.ring { stroke: var(--card); stroke-width: 2; }
.legend { display: flex; gap: 12px; font-size: 13px; flex-wrap: wrap; margin-bottom: 4px; }
.legend i { width: 12px; height: 3px; display: inline-block; vertical-align: middle; margin-right: 6px; border-radius: 2px; }
.tip { min-height: 1.4em; margin: 4px 0 0; font-size: 13px; }
</style>
