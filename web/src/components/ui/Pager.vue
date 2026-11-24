<script setup lang="ts">
import { computed } from 'vue'

// Page buttons for a list: Prev, page numbers, Next. Every number shows up to 10 pages; beyond that the
// first, the last and two either side of the current page, with … for the gaps.
const props = withDefaults(defineProps<{ page: number; pages: number; busy?: boolean; hasMore?: boolean }>(), { busy: false, hasMore: false })
const emit = defineEmits<{ go: [page: number] }>()

const list = computed<(number | '…')[]>(() => {
  const n = props.pages, p = props.page
  if (n <= 10) return Array.from({ length: n }, (_, i) => i + 1)
  const mid = [p - 2, p - 1, p, p + 1, p + 2].filter((x) => x > 1 && x < n)
  return [1, ...(mid[0] > 2 ? ['…' as const] : []), ...mid, ...(mid[mid.length - 1] < n - 1 ? ['…' as const] : []), n]
})
// hasMore lets Next go past the known pages when more can still load from the server.
const nextOk = computed(() => props.page < props.pages || props.hasMore)
</script>

<template>
  <nav class="pager" aria-label="Pages">
    <span class="info"><slot /></span>
    <div class="pages">
      <button type="button" class="pg" :disabled="page === 1" aria-label="Previous page" @click="emit('go', page - 1)">‹ Prev</button>
      <template v-for="(n, i) in list" :key="i">
        <span v-if="n === '…'" class="gap" aria-hidden="true">…</span>
        <button v-else type="button" class="pg num" :aria-label="`Page ${n}`" :aria-current="n === page ? 'page' : undefined" :disabled="busy" @click="emit('go', n)">{{ n }}</button>
      </template>
      <button type="button" class="pg" :disabled="!nextOk || busy" aria-label="Next page" @click="emit('go', page + 1)">{{ busy ? 'Loading…' : 'Next ›' }}</button>
    </div>
  </nav>
</template>

<style scoped>
.pager { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px 12px; padding: 12px 16px; border-top: 1px solid var(--line); }
.info { color: var(--muted); font-size: 12px; }
.pages { display: flex; flex-wrap: wrap; gap: 4px; }
.pg { min-height: 32px; padding: 4px 10px; font-size: 13px; background: var(--card); color: var(--ink); border: 1px solid var(--line); }
.pg.num { min-width: 34px; }
.pg:hover:not(:disabled) { background: var(--hover); color: var(--accent); border-color: var(--accent); }
.pg[aria-current='page'], .pg[aria-current='page']:hover { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
.pg:disabled:not([aria-current]) { opacity: .45; cursor: default; }
.gap { align-self: center; padding: 0 4px; color: var(--muted); }
</style>
