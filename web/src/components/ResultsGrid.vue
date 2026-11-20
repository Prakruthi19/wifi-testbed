<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { formatTime, testName, type Outcome, type RunDetail } from '../api'

// Tests down the side, runs across the top (oldest left), one cell per result.
// A test that flips between pass and fail across runs shows up as a striped row.
const props = defineProps<{ runs: RunDetail[] }>()
const router = useRouter()

const cols = computed(() => [...props.runs].sort((a, b) => a.finished.localeCompare(b.finished)))
const rows = computed(() => {
  const ids = new Set<string>()
  cols.value.forEach((r) => r.results.forEach((t) => ids.add(t.nodeid)))
  return [...ids]
    .map((id) => {
      const cells = cols.value.map((r) => r.results.find((t) => t.nodeid === id) ?? null)
      const seen = cells.filter(Boolean).map((c) => c!.outcome)
      const flips = seen.slice(1).filter((o, i) => (o === 'passed') !== (seen[i] === 'passed')).length
      return { id, name: testName(id), suite: cells.find(Boolean)!.suite, cells, flips }
    })
    .sort((a, b) => b.flips - a.flips || a.suite.localeCompare(b.suite) || a.name.localeCompare(b.name))
})

const hover = ref<{ row: number; col: number } | null>(null)
const tip = computed(() => {
  if (!hover.value) return null
  const row = rows.value[hover.value.row]
  const run = cols.value[hover.value.col]
  const cell = row.cells[hover.value.col]
  return { name: row.name, when: formatTime(run.finished), outcome: (cell?.outcome ?? 'not run') as Outcome | 'not run', msg: cell?.message ?? '', stage: cell?.classifier_stage }
})

const open = (col: number) => router.push({ name: 'run', params: { id: cols.value[col].id } })
</script>

<template>
  <div class="wrap">
    <div class="legend" aria-hidden="true">
      <span><i class="cell passed" /> passed</span>
      <span><i class="cell failed" /> failed / error</span>
      <span><i class="cell skipped" /> skipped</span>
      <span><i class="cell none" /> not in that run</span>
    </div>

    <div class="scroll">
      <div class="grid" role="grid" aria-label="Result of every test in every run" :style="{ '--cols': cols.length }">
        <div class="row head" role="row">
          <span role="columnheader" class="name">Test · run →</span>
          <span v-for="(r, c) in cols" :key="r.id" role="columnheader" class="colhead">
            <button type="button" class="linkish" :title="`Open run of ${formatTime(r.finished)}`" @click="open(c)">{{ c + 1 }}</button>
          </span>
        </div>
        <div v-for="(row, ri) in rows" :key="row.id" class="row" role="row">
          <span role="rowheader" class="name">
            {{ row.name }}
            <span class="muted">{{ row.suite }}</span>
            <span v-if="row.flips" class="flip">flipped {{ row.flips }}×</span>
          </span>
          <span v-for="(cell, ci) in row.cells" :key="ci" role="gridcell">
            <button
              type="button"
              class="cell"
              :class="cell ? cell.outcome : 'none'"
              :aria-label="`${row.name}, run ${ci + 1}: ${cell?.outcome ?? 'not run'}`"
              @mouseenter="hover = { row: ri, col: ci }"
              @focus="hover = { row: ri, col: ci }"
              @mouseleave="hover = null"
              @blur="hover = null"
              @click="open(ci)"
            />
          </span>
        </div>
      </div>
    </div>

    <p class="tip" aria-live="polite">
      <template v-if="tip">
        <b>{{ tip.name }}</b> · run of {{ tip.when }} · <b>{{ tip.outcome }}</b>
        <template v-if="tip.stage"> · stopped at {{ tip.stage }}</template>
        <span v-if="tip.msg" class="msg"> · {{ tip.msg }}</span>
      </template>
      <template v-else>Hover or tab to a square for the result; click it to open that run. Runs are numbered oldest first.</template>
    </p>
  </div>
</template>

<style scoped>
.legend { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 13px; color: var(--muted); margin-bottom: 8px; }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.legend .cell { width: 12px; height: 12px; display: inline-block; }
.scroll { overflow-x: auto; }
.grid { display: grid; grid-template-columns: max-content repeat(var(--cols), 24px); gap: 3px; align-items: center; }
.row { display: contents; }
.colhead { text-align: center; font-size: 12px; }
.head .name { color: var(--muted); font-weight: 400; }
.name { font-weight: 500; padding-right: 12px; font-size: 13px; white-space: nowrap; }
.name .muted { margin-left: 6px; font-size: 12px; }
.flip { margin-left: 6px; font-size: 11px; color: var(--skip); background: var(--skip-bg); border-radius: 999px; padding: 1px 6px; }
.cell { width: 24px; height: 24px; min-height: 0; padding: 0; border-radius: 4px; border: 0; display: block; cursor: pointer; }
.cell.passed { background: var(--pass); }
.cell.failed, .cell.error { background: var(--fail); }
.cell.skipped { background: var(--skip); }
.cell.none { background: var(--line); }
.cell:hover, .cell:focus-visible { outline: 2px solid var(--ink); outline-offset: 1px; }
.linkish { background: none; color: var(--accent); padding: 0; min-height: 0; text-decoration: underline; font-size: 12px; }
.tip { min-height: 1.5em; font-size: 14px; margin: 8px 0 0; }
.tip .msg { color: var(--fail); }
</style>
