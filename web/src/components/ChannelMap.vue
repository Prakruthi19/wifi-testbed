<script setup lang="ts">
import { computed, ref } from 'vue'

// Where each access point sits in the radio spectrum, drawn from its configured channel.
// A 20 MHz channel is a block centred on 2407 + 5 x channel MHz (2.4 GHz) or 5000 + 5 x channel MHz (5 GHz).
// Two 2.4 GHz APs closer than 5 channels apart overlap and slow each other down; 1, 6 and 11 never do.
export interface ChannelAp {
  name: string
  channel: number
  ssid?: string
  security?: string
}

const props = defineProps<{ aps: ChannelAp[] }>()

const BANDS = {
  '2.4': { label: '2.4 GHz', min: 2400, max: 2484, ticks: [1, 6, 11, 13], freq: (ch: number) => 2407 + 5 * ch },
  '5': { label: '5 GHz (UNII-1)', min: 5165, max: 5255, ticks: [36, 40, 44, 48], freq: (ch: number) => 5000 + 5 * ch },
} as const
type Band = keyof typeof BANDS

const W = 640
const H = 190
const PAD = { l: 16, r: 16, t: 24, b: 40 }
const SERIES = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)']

const bandOf = (ch: number): Band => (ch > 14 ? '5' : '2.4')
const present = computed(() => (['2.4', '5'] as Band[]).filter((b) => props.aps.some((a) => bandOf(a.channel) === b)))
const band = ref<Band>(present.value[0] ?? '2.4')
const hovered = ref<string | null>(null)

const x = (mhz: number) => {
  const b = BANDS[band.value]
  return PAD.l + ((mhz - b.min) / (b.max - b.min)) * (W - PAD.l - PAD.r)
}

// Colour follows the AP (its position in the full list), so switching band never repaints an AP.
const shapes = computed(() =>
  props.aps
    .map((ap, i) => ({ ap, color: SERIES[i % SERIES.length] }))
    .filter(({ ap }) => bandOf(ap.channel) === band.value)
    .map(({ ap, color }, j) => {
      const f = BANDS[band.value].freq(ap.channel)
      const lane = j % 3 // stagger heights so overlapping blocks stay visible
      const top = PAD.t + 18 + lane * 22
      const x0 = x(f - 10)
      const x1 = x(f + 10)
      const base = H - PAD.b
      // trapezoid: the signal's edges roll off rather than stopping square
      const d = `M${x0},${base} L${x0 + 8},${top} L${x1 - 8},${top} L${x1},${base} Z`
      return { ap, color, d, cx: (x0 + x1) / 2, top }
    }),
)

const overlaps = computed(() => {
  const s = shapes.value
  const out: string[] = []
  for (let i = 0; i < s.length; i++)
    for (let j = i + 1; j < s.length; j++) {
      const gap = Math.abs(s[i].ap.channel - s[j].ap.channel)
      if (band.value === '2.4' ? gap > 0 && gap < 5 : gap > 0 && gap < 4)
        out.push(`${s[i].ap.name} (ch ${s[i].ap.channel}) and ${s[j].ap.name} (ch ${s[j].ap.channel}) partly overlap`)
      else if (gap === 0) out.push(`${s[i].ap.name} and ${s[j].ap.name} share channel ${s[i].ap.channel} and take turns to talk`)
    }
  return out
})

const ticks = computed(() => BANDS[band.value].ticks.map((ch) => ({ ch, x: x(BANDS[band.value].freq(ch)) })))
const info = computed(() => props.aps.find((a) => a.name === hovered.value) ?? null)
</script>

<template>
  <div class="viz-root">
    <div class="controls" role="group" aria-label="Band">
      <button
        v-for="b in present"
        :key="b"
        type="button"
        class="seg"
        :aria-pressed="band === b"
        @click="band = b"
      >
        {{ BANDS[b].label }}
      </button>
    </div>

    <svg :viewBox="`0 0 ${W} ${H}`" role="img" :aria-label="`Channel map, ${BANDS[band].label}`">
      <line :x1="PAD.l" :x2="W - PAD.r" :y1="H - PAD.b" :y2="H - PAD.b" class="axis" />
      <g v-for="t in ticks" :key="t.ch">
        <line :x1="t.x" :x2="t.x" :y1="PAD.t" :y2="H - PAD.b" class="grid" />
        <text :x="t.x" :y="H - PAD.b + 16" text-anchor="middle" class="tick">ch {{ t.ch }}</text>
      </g>
      <text :x="W / 2" :y="H - 6" text-anchor="middle" class="tick">frequency (MHz) →</text>

      <g
        v-for="s in shapes"
        :key="s.ap.name"
        class="ap"
        :class="{ dim: hovered && hovered !== s.ap.name }"
        tabindex="0"
        @mouseenter="hovered = s.ap.name"
        @mouseleave="hovered = null"
        @focus="hovered = s.ap.name"
        @blur="hovered = null"
      >
        <path :d="s.d" :fill="s.color" fill-opacity="0.28" :stroke="s.color" stroke-width="2" />
        <text :x="s.cx" :y="s.top - 6" text-anchor="middle" class="label">{{ s.ap.name }}</text>
      </g>
    </svg>

    <p class="readout" aria-live="polite">
      <template v-if="info">
        <b>{{ info.name }}</b>: channel {{ info.channel }}
        ({{ BANDS[bandOf(info.channel)].freq(info.channel) }} MHz centre, 20 MHz wide)
        <template v-if="info.ssid"> · Wi-Fi name {{ info.ssid }}</template>
        <template v-if="info.security"> · {{ info.security }}</template>
      </template>
      <template v-else>Hover or tab to an access point for its details.</template>
    </p>
    <ul v-if="overlaps.length" class="warn">
      <li v-for="o in overlaps" :key="o">⚠ {{ o }}</li>
    </ul>
    <p v-else-if="shapes.length > 1" class="ok">✓ No overlapping channels on this band.</p>
  </div>
</template>

<style scoped>
.controls { display: flex; gap: 4px; margin-bottom: 8px; }
.seg { background: var(--bg); color: var(--ink); border: 1px solid var(--line); min-height: 36px; padding: 6px 12px; }
.seg[aria-pressed='true'] { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
svg { width: 100%; height: auto; display: block; }
.axis { stroke: var(--muted); stroke-width: 1; }
.grid { stroke: var(--line); stroke-dasharray: 2 4; }
.tick { fill: var(--muted); font-size: 11px; }
.label { fill: var(--ink); font-size: 12px; font-weight: 600; }
.ap { cursor: pointer; outline: none; transition: opacity 0.15s; }
.ap.dim { opacity: 0.3; }
.ap:focus-visible path { stroke-width: 3; }
.readout { min-height: 1.5em; margin: 6px 0; font-size: 14px; }
.warn { color: var(--skip); margin: 0; padding-left: 0; list-style: none; font-size: 14px; }
.ok { color: var(--pass); margin: 0; font-size: 14px; }
</style>
