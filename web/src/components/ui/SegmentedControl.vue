<script setup lang="ts" generic="T extends string | number">
// A row of mutually exclusive choices (a radio group that looks like tabs). Arrow keys move the choice,
// as in a native radio group; only the chosen option is in the Tab order.
// label names the group for screen readers; or pass labelledby with the id of a visible label instead.
const props = defineProps<{ options: { value: T; label: string; disabled?: boolean }[]; label?: string; labelledby?: string }>()
const model = defineModel<T>({ required: true })

function key(e: KeyboardEvent, i: number) {
  const step = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0
  if (!step) return
  e.preventDefault()
  const n = props.options.length
  for (let k = 1; k <= n; k++) {
    const o = props.options[(i + step * k + n * k) % n]
    if (!o.disabled) {
      model.value = o.value
      ;((e.currentTarget as HTMLElement).parentElement?.children[props.options.indexOf(o)] as HTMLElement)?.focus()
      return
    }
  }
}
</script>

<template>
  <div class="segs" role="radiogroup" :aria-label="labelledby ? undefined : label" :aria-labelledby="labelledby">
    <button
      v-for="(o, i) in options" :key="o.value" type="button" role="radio" class="seg"
      :aria-checked="model === o.value" :tabindex="model === o.value ? 0 : -1" :disabled="o.disabled"
      @click="model = o.value" @keydown="key($event, i)"
    >
      <!-- The option slot lets a caller add to the label, for example a count. -->
      <slot name="option" :option="o">{{ o.label }}</slot>
    </button>
  </div>
</template>

<style scoped>
.segs { display: inline-flex; gap: 2px; background: var(--bg); border: 1px solid var(--line); border-radius: var(--radius); padding: 2px; }
.seg { background: none; color: var(--muted); border: 0; min-height: 30px; padding: 4px 12px; font-size: 13px; font-weight: 600; border-radius: var(--radius-sm); cursor: pointer; }
.seg:hover:not(:disabled) { color: var(--ink); }
.seg[aria-checked='true'] { background: var(--card); color: var(--ink); box-shadow: 0 1px 2px rgb(15 23 42 / 0.15); }
.seg:disabled { opacity: .4; cursor: not-allowed; }
</style>
