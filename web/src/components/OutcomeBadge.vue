<script setup lang="ts">
import type { Outcome } from '../api'
defineProps<{ outcome: Outcome }>()
</script>

<template>
  <span class="badge" :class="outcome">{{ outcome }}</span>
</template>

<style scoped>
.badge { display: inline-block; padding: 2px 8px; border-radius: var(--radius-sm); font-size: 12px; font-weight: 600; }
.passed { color: var(--pass); background: var(--pass-bg); }
.failed, .error { color: var(--fail); background: var(--fail-bg); }
.skipped { color: var(--skip); background: var(--skip-bg); }
</style>
