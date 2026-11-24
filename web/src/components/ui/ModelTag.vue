<script setup lang="ts">
// The honesty label for anything estimated rather than measured. title explains the model on hover.
defineProps<{ title?: string }>()
</script>

<template>
  <span class="modeltag" :title="title"><slot>Model, not a measurement</slot></span>
</template>

<style scoped>
.modeltag { font-size: 12px; font-weight: 600; letter-spacing: 0; border: 1px solid var(--skip); background: var(--skip-bg); border-radius: var(--radius-sm); padding: 1px 8px; cursor: help; white-space: nowrap; }
</style>
