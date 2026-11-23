<script setup lang="ts">
// A small "i" next to a heading. The explanation shows on hover or keyboard focus, so pages stay short.
defineProps<{ text: string }>()
</script>

<template>
  <span class="info" tabindex="0" role="note" :aria-label="text">
    <span aria-hidden="true">i</span>
    <span class="pop" aria-hidden="true">{{ text }}</span>
  </span>
</template>

<style scoped>
.info { position: relative; display: inline-grid; place-items: center; width: 18px; height: 18px; margin-left: 6px; border-radius: 50%; border: 1px solid var(--line); color: var(--muted); font: italic 600 11px/1 Georgia, serif; vertical-align: 2px; cursor: help; text-transform: none; letter-spacing: 0; }
.pop { display: none; position: absolute; z-index: 20; top: calc(100% + 8px); left: 50%; transform: translateX(-50%); width: max-content; max-width: 280px; padding: 10px 12px; border-radius: var(--radius); background: var(--ink); color: var(--card); font: 500 12px/1.5 var(--font); box-shadow: 0 8px 24px rgba(0, 0, 0, .2); white-space: normal; text-align: left; }
.info:hover .pop, .info:focus .pop { display: block; }
@media (max-width: 640px) { .pop { left: auto; right: -8px; transform: none; max-width: 240px; } }
</style>
