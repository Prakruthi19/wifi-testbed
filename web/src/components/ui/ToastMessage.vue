<script setup lang="ts">
// A small popup in the corner for "it worked" and "it failed" messages, instead of a banner that pushes
// the page down. Success closes itself after a few seconds (the timer waits while the pointer or focus
// is on it, so nobody loses a message they are reading). Errors stay until closed.
import { onUnmounted, ref, watch } from 'vue'

const props = withDefaults(defineProps<{ kind?: 'ok' | 'error'; text: string; timeout?: number }>(), { kind: 'ok', timeout: 4000 })
const emit = defineEmits<{ close: [] }>()

let timer: ReturnType<typeof setTimeout> | undefined
const held = ref(false)
function arm() {
  clearTimeout(timer)
  if (props.kind === 'ok' && !held.value) timer = setTimeout(() => emit('close'), props.timeout)
}
watch(() => [props.text, props.kind], arm, { immediate: true })
watch(held, arm)
onUnmounted(() => clearTimeout(timer))
</script>

<template>
  <Teleport to="body">
    <div
      class="toast" :class="kind" :role="kind === 'error' ? 'alert' : 'status'"
      @pointerenter="held = true" @pointerleave="held = false" @focusin="held = true" @focusout="held = false"
    >
      <svg viewBox="0 0 24 24" aria-hidden="true"><path :d="kind === 'error' ? 'M12 8v5M12 16.5h.01M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z' : 'M8 12.5l3 3 5-6M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z'" /></svg>
      <span class="text">{{ text }}</span>
      <button type="button" class="x" aria-label="Dismiss" @click="emit('close')">×</button>
    </div>
  </Teleport>
</template>

<style scoped>
.toast {
  position: fixed; z-index: 50; right: 24px; bottom: 24px; max-width: min(420px, calc(100vw - 32px));
  display: flex; align-items: center; gap: 10px; padding: 12px 12px 12px 14px;
  background: var(--card); color: var(--ink); border: 1px solid var(--line); border-left: 4px solid var(--pass);
  border-radius: var(--radius); box-shadow: 0 10px 30px rgba(15, 23, 42, .18); font-size: 14px;
  animation: in .2s ease-out;
}
.toast.error { border-left-color: var(--fail); }
svg { width: 20px; height: 20px; flex: none; fill: none; stroke: var(--pass); stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.error svg { stroke: var(--fail); }
.text { flex: 1; }
.x { background: none; color: var(--muted); border: 0; min-height: 0; padding: 0 4px; font-size: 20px; line-height: 1; }
.x:hover { color: var(--ink); }
@keyframes in { from { opacity: 0; transform: translateY(8px); } }
@media (prefers-reduced-motion: reduce) { .toast { animation: none; } }
/* Phones: above the bottom tab bar, full width. */
@media (max-width: 760px) { .toast { left: 16px; right: 16px; bottom: 76px; max-width: none; } }
</style>
