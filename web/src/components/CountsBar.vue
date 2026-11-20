<script setup lang="ts">
import { computed } from 'vue'
import type { Counts } from '../api'

// One horizontal bar split by outcome, with the numbers written out for screen readers and print.
const props = defineProps<{ counts: Counts }>()
const total = computed(() => Object.values(props.counts).reduce((a, b) => a + b, 0))
const parts = computed(() =>
  (['passed', 'failed', 'error', 'skipped'] as const)
    .filter((k) => props.counts[k] > 0)
    .map((k) => ({ k, n: props.counts[k], pct: (100 * props.counts[k]) / (total.value || 1) })),
)
const label = computed(() => parts.value.map((p) => `${p.n} ${p.k}`).join(', ') || 'no tests')
</script>

<template>
  <div class="bar" role="img" :aria-label="label" :title="label">
    <span v-for="p in parts" :key="p.k" :class="p.k" :style="{ width: p.pct + '%' }" />
  </div>
</template>

<style scoped>
.bar { display: flex; height: 8px; border-radius: 4px; overflow: hidden; background: var(--line); min-width: 80px; gap: 2px; }
.passed { background: var(--pass); }
.failed, .error { background: var(--fail); }
.skipped { background: var(--skip); }
</style>
