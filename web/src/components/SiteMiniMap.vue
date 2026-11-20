<script setup lang="ts">
import { FLOORS, H, W, WALLS } from '../rfmodel'
import type { Health, Site } from '../stores/sites'

// A small floor plan for a site card: access points as coloured dots (hollow when off) and devices
// coloured by how good their connection is.
defineProps<{ site: Site; health: Health }>()
const SERIES = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)']
const DEV: Record<string, string> = { good: 'var(--pass)', weak: 'var(--skip)', unusable: 'var(--fail)', 'no internet': 'var(--fail)', 'not seen': 'none' }
</script>

<template>
  <svg :viewBox="`0 0 ${W} ${H}`" role="img" :aria-label="`Floor plan of ${site.name}: ${health.apsOn} of ${site.aps.length} access points on, ${health.connected} of ${site.devices.length} devices online`">
    <rect v-for="f in FLOORS" :key="f.name" :x="f.x" :y="f.y" :width="f.w" :height="f.h" class="floor" />
    <line v-for="(w, i) in WALLS" :key="i" :x1="w[0]" :y1="w[1]" :x2="w[2]" :y2="w[3]" class="wall" />
    <circle v-for="s in health.devices" :key="s.d.name" :cx="s.d.x" :cy="s.d.y" r="13" :fill="DEV[s.state]" class="dev" :class="{ gone: s.state === 'not seen' }" />
    <g v-for="(a, i) in site.aps" :key="a.name" :transform="`translate(${a.x},${a.y})`">
      <circle r="22" :fill="a.on ? SERIES[i] : 'var(--card)'" :stroke="a.on ? 'var(--card)' : 'var(--fail)'" class="ap" :class="{ off: !a.on }" />
      <path v-if="!a.on" d="M-9,-9 L9,9 M9,-9 L-9,9" class="x" />
    </g>
  </svg>
</template>

<style scoped>
svg { width: 100%; height: auto; display: block; border-radius: 6px; background: var(--bg); }
.floor { fill: var(--card); }
.wall { stroke: var(--muted); stroke-width: 7; stroke-linecap: square; }
.dev { stroke: var(--card); stroke-width: 3; }
.dev.gone { stroke: var(--muted); stroke-width: 4; stroke-dasharray: 6 5; fill: none; }
.ap { stroke-width: 4; }
.ap.off { stroke-dasharray: 7 5; }
.x { stroke: var(--fail); stroke-width: 4; stroke-linecap: round; }
</style>
