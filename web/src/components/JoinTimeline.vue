<script setup lang="ts">
import { computed } from 'vue'

// The steps a device goes through to get online, in order. The classifier names the step where a
// join broke (or "success"); steps before it passed, that step failed, steps after were never reached.
const STEPS = [
  { key: 'network_selection', label: 'Find network' },
  { key: 'authentication', label: 'Authenticate' },
  { key: 'association', label: 'Associate' },
  { key: 'eap', label: '802.1X login' },
  { key: 'key_exchange', label: '4-way handshake' },
  { key: 'dhcp', label: 'Get IP (DHCP)' },
  { key: 'dns', label: 'DNS lookup' },
]

const props = defineProps<{ stage: string; enterprise?: boolean }>()

const steps = computed(() => {
  const shown = STEPS.filter((s) => s.key !== 'eap' || props.enterprise || props.stage === 'eap')
  const failedAt = shown.findIndex((s) => s.key === props.stage)
  return shown.map((s, i) => ({
    ...s,
    state: props.stage === 'success' || (failedAt !== -1 && i < failedAt) ? 'ok' : i === failedAt ? 'fail' : 'todo',
  }))
})
</script>

<template>
  <p v-if="stage === 'undetermined'" class="muted">The classifier could not tell where this join stopped.</p>
  <ol v-else class="timeline">
    <li v-for="s in steps" :key="s.key" :class="s.state">
      <span class="dot" aria-hidden="true" />
      <span>{{ s.label }}</span>
      <span class="sr">{{ s.state === 'ok' ? 'passed' : s.state === 'fail' ? 'failed here' : 'not reached' }}</span>
    </li>
  </ol>
</template>

<style scoped>
.timeline { list-style: none; padding: 0; margin: 8px 0; display: flex; flex-wrap: wrap; gap: 6px 4px; }
li { display: flex; align-items: center; gap: 6px; font-size: 13px; padding: 4px 10px 4px 6px; border-radius: 999px; border: 1px solid var(--line); }
.dot { width: 10px; height: 10px; border-radius: 50%; background: var(--todo); }
.ok .dot { background: var(--pass); }
.fail { border-color: var(--fail); color: var(--fail); font-weight: 600; }
.fail .dot { background: var(--fail); }
.todo { color: var(--muted); }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
</style>
