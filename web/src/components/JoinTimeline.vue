<script setup lang="ts">
import { computed } from 'vue'
import { STEPS, stepLabel } from '../describe'

// The steps a device goes through to get online, in order. The capture classifier names the step
// where the join stopped (or "success"): steps before it passed, that one failed, later ones never ran.
const ORDER = ['network_selection', 'authentication', 'association', 'eap', 'key_exchange', 'dhcp', 'dns']

const props = defineProps<{ stage: string; enterprise?: boolean; expectStop?: string }>()

const steps = computed(() => {
  const shown = ORDER.filter((k) => k !== 'eap' || props.enterprise || props.stage === 'eap' || props.expectStop === 'eap')
  const stopAt = shown.indexOf(props.stage)
  return shown.map((key, i) => ({
    key,
    ...STEPS[key],
    state: props.stage === 'success' || (stopAt !== -1 && i < stopAt) ? 'ok' : i === stopAt ? 'fail' : 'todo',
    expected: props.expectStop === key,
  }))
})
const stopped = computed(() => steps.value.find((s) => s.state === 'fail'))
</script>

<template>
  <div class="tl">
    <p v-if="stage === 'undetermined'" class="muted">The capture did not show clearly where this join stopped.</p>
    <template v-else>
      <ol>
        <li v-for="(s, i) in steps" :key="s.key" :class="s.state" :title="s.explain">
          <span class="dot" aria-hidden="true">{{ s.state === 'ok' ? '✓' : s.state === 'fail' ? '✕' : i + 1 }}</span>
          <span>{{ s.label }}</span>
          <span class="sr">: {{ s.state === 'ok' ? 'done' : s.state === 'fail' ? 'stopped here' : 'never reached' }}</span>
          <span v-if="s.expected && s.state === 'fail'" class="tag">expected</span>
        </li>
      </ol>
      <p v-if="stage === 'success'" class="note ok">The device got all the way online.</p>
      <p v-else-if="stopped" class="note">
        <b>Stopped at "{{ stopped.label }}".</b> {{ stopped.explain }}
        <template v-if="expectStop && expectStop !== 'success'">
          {{ expectStop === stage ? 'That is exactly where this broken setup should stop.' : `It should have stopped at "${stepLabel(expectStop)}".` }}
        </template>
      </p>
    </template>
  </div>
</template>

<style scoped>
ol { list-style: none; padding: 0; margin: 4px 0 0; display: flex; flex-wrap: wrap; gap: 6px; }
li { display: flex; align-items: center; gap: 6px; font-size: 13px; padding: 4px 10px 4px 4px; border-radius: 999px; border: 1px solid var(--line); cursor: help; }
.dot { width: 20px; height: 20px; border-radius: 50%; display: grid; place-items: center; font-size: 11px; font-weight: 700; background: var(--line); color: var(--muted); }
.ok .dot { background: var(--pass); color: var(--card); }
.fail { border-color: var(--fail); color: var(--fail); font-weight: 600; }
.fail .dot { background: var(--fail); color: var(--card); }
.todo { color: var(--muted); border-style: dashed; }
.tag { font-size: 11px; font-weight: 600; border-radius: 999px; padding: 0 6px; background: var(--skip-bg); color: var(--skip); }
.note { margin: 8px 0 0; font-size: 14px; }
.note.ok { color: var(--pass); }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
</style>
