<script setup lang="ts">
// The one button style set. variant picks the look; everything else (type, disabled, @click) passes through.
withDefaults(defineProps<{ variant?: 'primary' | 'secondary' | 'danger' | 'ghost'; size?: 'md' | 'sm' }>(), { variant: 'primary', size: 'md' })
</script>

<template>
  <button type="button" class="btn" :class="[variant, size]"><slot /></button>
</template>

<style scoped>
.btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; border-radius: var(--radius); font-weight: 600; cursor: pointer; border: 1px solid transparent; transition: background .12s, border-color .12s, color .12s; }
.md { min-height: 38px; padding: 8px 16px; font-size: 14px; }
.sm { min-height: 30px; padding: 4px 10px; font-size: 13px; }
.primary { background: var(--accent); color: var(--accent-ink); }
.primary:hover:not(:disabled) { filter: brightness(1.08); }
.secondary { background: var(--card); color: var(--ink); border-color: var(--line); }
.secondary:hover:not(:disabled) { background: var(--hover); color: var(--accent); border-color: var(--accent); }
.danger { background: none; color: var(--fail); border-color: var(--line); }
.danger:hover:not(:disabled) { background: var(--fail-bg); border-color: var(--fail); }
.ghost { background: none; color: var(--accent); }
.ghost:hover:not(:disabled) { background: var(--hover); }
.btn:disabled { opacity: .45; cursor: not-allowed; }
</style>
