<script setup lang="ts">
import { STATUS_LABEL, type Status } from '../stores/sites'

// A site's overall state as a coloured pill with a word, so it never relies on colour alone.
defineProps<{ status: Status }>()
const ICON: Record<Status, string> = { ok: '✓', warning: '!', degraded: '▲', offline: '✕' }
</script>

<template>
  <span class="badge" :class="status"><span aria-hidden="true">{{ ICON[status] }}</span> {{ STATUS_LABEL[status] }}</span>
</template>

<style scoped>
.badge { display: inline-flex; align-items: center; gap: 4px; border-radius: var(--radius-sm); padding: 2px 10px; font-size: 13px; font-weight: 600; white-space: nowrap; }
.ok { color: var(--pass); background: var(--pass-bg); }
.warning { color: var(--skip); background: var(--skip-bg); }
.degraded, .offline { color: var(--fail); background: var(--fail-bg); }
.offline { outline: 1px solid var(--fail); }
</style>
