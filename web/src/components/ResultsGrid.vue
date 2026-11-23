<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { formatTime, type Outcome, type RunDetail } from '../api'
import { describe, stepLabel, suiteLabel, variantOf } from '../describe'
import { testHistories } from '../runs'

// Test history: one row per test, one square per run (oldest left), grouped by suite.
// Starts on the tests that changed result, so the page answers "what is unstable?" first.
const props = defineProps<{ runs: RunDetail[] }>()
const router = useRouter()

const cols = computed(() => [...props.runs].sort((a, b) => a.finished.localeCompare(b.finished)))
const all = computed(() =>
  testHistories(props.runs).map((h) => ({ ...h, name: describe(h.id).title, variant: variantOf(h.id), group: suiteLabel(h.suite, h.id) })),
)
const show = ref<'changed' | 'failing' | 'all'>('changed')
const counts = computed(() => ({
  changed: all.value.filter((r) => r.changes).length,
  failing: all.value.filter((r) => r.failingNow).length,
  all: all.value.length,
}))
const FILTERS = [
  { key: 'changed', label: 'Changed result' },
  { key: 'failing', label: 'Failing now' },
  { key: 'all', label: 'All tests' },
] as const

const groups = computed(() => {
  const rows = all.value.filter((r) => show.value === 'all' || (show.value === 'changed' ? r.changes : r.failingNow))
  const by = new Map<string, typeof rows>()
  rows.forEach((r) => by.set(r.group, [...(by.get(r.group) ?? []), r]))
  return [...by]
    .map(([name, rs]) => ({
      name,
      rows: rs.sort((a, b) => b.changes - a.changes || a.name.localeCompare(b.name) || a.variant.localeCompare(b.variant)),
      changed: rs.filter((r) => r.changes).length,
      failing: rs.filter((r) => r.failingNow).length,
    }))
    .sort((a, b) => b.failing - a.failing || b.changed - a.changed || a.name.localeCompare(b.name))
})

// Groups with something to look at start open; quiet groups start closed (in "All tests").
const closed = reactive(new Set<string>())
watch([show, groups], () => {
  closed.clear()
  groups.value.forEach((g) => !g.changed && !g.failing && closed.add(g.name))
}, { immediate: true })
const toggle = (name: string) => (closed.has(name) ? closed.delete(name) : closed.add(name))

const hover = ref<{ name: string; variant: string; col: number; outcome: Outcome | 'not run'; msg: string; stage: string | null } | null>(null)
const open = (col: number) => router.push({ name: 'run', params: { id: cols.value[col].id } })
const groupSummary = (g: { rows: unknown[]; changed: number; failing: number }) =>
  [`${g.rows.length} test${g.rows.length === 1 ? '' : 's'}`, g.changed && `${g.changed} changed`, g.failing && `${g.failing} failing now`]
    .filter(Boolean).join(' · ') + (!g.changed && !g.failing ? ' · steady' : '')
</script>

<template>
  <div class="history">
    <div class="bar">
      <div role="group" aria-label="Show" class="segs">
        <button v-for="f in FILTERS" :key="f.key" type="button" class="seg" :aria-pressed="show === f.key" @click="show = f.key">
          {{ f.label }} <span class="n">{{ counts[f.key] }}</span>
        </button>
      </div>
      <div class="legend" aria-hidden="true">
        <span><i class="cell passed" /> passed</span>
        <span><i class="cell failed" /> failed</span>
        <span><i class="cell skipped" /> skipped</span>
        <span><i class="cell none" /> not run</span>
      </div>
    </div>
    <p class="muted note">
      Runs go left to right, oldest first ({{ cols.length }} runs). "Changed result" means a test passed in one run and failed in another.
      That can be a real flaky test, or a known cause such as the lab not being set up or a fix landing between runs.
    </p>

    <p v-if="!groups.length" class="muted empty">
      {{ show === 'changed' ? 'No test changed result in these runs.' : show === 'failing' ? 'Nothing is failing in the latest run of each test.' : 'No tests.' }}
    </p>

    <section v-for="g in groups" :key="g.name" class="group">
      <h3>
        <button type="button" class="ghead" :aria-expanded="!closed.has(g.name)" @click="toggle(g.name)">
          <span class="chev" aria-hidden="true">›</span>{{ g.name }} <span class="muted">{{ groupSummary(g) }}</span>
        </button>
      </h3>
      <div v-if="!closed.has(g.name)" class="scroll">
        <div class="grid" role="grid" :aria-label="`${g.name}: result of each test in each run`" :style="{ '--cols': cols.length }">
          <div class="row head" role="row">
            <span role="columnheader" class="name">Test</span>
            <span v-for="(r, c) in cols" :key="r.id" role="columnheader" class="colhead">
              <button type="button" class="linkish" :title="`Open run of ${formatTime(r.finished)}`" @click="open(c)">{{ c + 1 }}</button>
            </span>
          </div>
          <div v-for="row in g.rows" :key="row.id" class="row" role="row">
            <span role="rowheader" class="name" :title="row.id">
              <span class="title">{{ row.name }}</span>
              <code v-if="row.variant" class="variant">{{ row.variant }}</code>
              <span v-if="row.changes" class="tag warn" title="Passed in some runs and failed in others">changed {{ row.changes }}×</span>
              <span v-if="row.failingNow" class="tag bad">failing now</span>
            </span>
            <span v-for="(cell, ci) in row.cells" :key="ci" role="gridcell">
              <button
                type="button"
                class="cell"
                :class="cell ? cell.outcome : 'none'"
                :aria-label="`${row.name}${row.variant ? ' ' + row.variant : ''}, run ${ci + 1}: ${cell?.outcome ?? 'not run'}`"
                @mouseenter="hover = { name: row.name, variant: row.variant, col: ci, outcome: cell?.outcome ?? 'not run', msg: cell?.message ?? '', stage: cell?.classifier_stage ? stepLabel(cell.classifier_stage) : null }"
                @focus="hover = { name: row.name, variant: row.variant, col: ci, outcome: cell?.outcome ?? 'not run', msg: cell?.message ?? '', stage: cell?.classifier_stage ? stepLabel(cell.classifier_stage) : null }"
                @mouseleave="hover = null"
                @blur="hover = null"
                @click="open(ci)"
              />
            </span>
          </div>
        </div>
      </div>
    </section>

    <p class="tip" aria-live="polite">
      <template v-if="hover">
        <b>{{ hover.name }}</b><template v-if="hover.variant"> ({{ hover.variant }})</template> · run {{ hover.col + 1 }}, {{ formatTime(cols[hover.col].finished) }} · <b>{{ hover.outcome }}</b>
        <template v-if="hover.stage"> · stopped at: {{ hover.stage }}</template>
        <span v-if="hover.msg" class="msg"> · {{ hover.msg }}</span>
      </template>
      <template v-else>Hover or tab to a square for its result; click it to open that run.</template>
    </p>
  </div>
</template>

<style scoped>
.bar { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px 16px; }
.segs { display: flex; border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; }
.seg { background: var(--card); color: var(--muted); border-radius: 0; min-height: 34px; padding: 4px 12px; font-size: 14px; font-weight: 600; }
.seg + .seg { border-left: 1px solid var(--line); }
.seg[aria-pressed='true'] { background: var(--bg); color: var(--ink); box-shadow: inset 0 -2px 0 var(--accent); }
.n { font-weight: 400; color: var(--muted); margin-left: 2px; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 13px; color: var(--muted); }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.legend .cell { width: 12px; height: 12px; display: inline-block; cursor: default; }
.note { font-size: 13px; margin: 10px 0 12px; max-width: 900px; }
.empty { padding: 16px 0; }

.group { border: 1px solid var(--line); border-radius: var(--radius); margin-bottom: 10px; }
.group h3 { margin: 0; font-size: 15px; }
.ghead { width: 100%; text-align: left; background: var(--bg); color: var(--ink); border-radius: 0; min-height: 40px; padding: 8px 12px; font-weight: 600; display: flex; gap: 8px; align-items: baseline; }
.ghead .muted { font-weight: 400; font-size: 13px; }
.chev { display: inline-block; color: var(--muted); transition: transform .15s; }
[aria-expanded='true'] .chev { transform: rotate(90deg); }
.scroll { overflow-x: auto; padding: 8px 12px 10px; }
.grid { display: grid; grid-template-columns: var(--name-w, 380px) repeat(var(--cols), 18px); gap: 3px; align-items: center; }
.row { display: contents; }
.colhead { text-align: center; font-size: 11px; }
.head .name { color: var(--muted); font-weight: 400; font-size: 12px; }
.name { padding-right: 12px; font-size: 13px; white-space: nowrap; display: flex; align-items: center; gap: 6px; min-width: 0; overflow: hidden; }
.title { overflow: hidden; text-overflow: ellipsis; }
.variant, .tag { flex: none; }
.title { font-weight: 500; }
.variant { font-size: 11px; color: var(--muted); background: var(--bg); border: 1px solid var(--line); border-radius: var(--radius-sm); padding: 0 5px; }
.tag { font-size: 11px; border-radius: var(--radius-sm); padding: 1px 6px; }
.tag.warn { color: var(--skip); background: var(--skip-bg); }
.tag.bad { color: var(--fail); background: var(--fail-bg); }
.cell { width: 18px; height: 18px; min-height: 0; padding: 0; border-radius: 2px; border: 0; display: block; cursor: pointer; }
.cell.passed { background: var(--pass); }
.cell.failed, .cell.error { background: var(--fail); }
.cell.skipped { background: var(--skip); }
.cell.none { background: var(--line); }
.cell:hover, .cell:focus-visible { outline: 2px solid var(--ink); outline-offset: 1px; }
.linkish { background: none; color: var(--accent); padding: 0; min-height: 0; text-decoration: underline; font-size: 11px; }
.tip { min-height: 1.5em; font-size: 14px; margin: 8px 0 0; }
.tip .msg { color: var(--fail); }
@media (max-width: 640px) { .grid { --name-w: 190px; } .tag.warn { display: none; } .scroll { padding: 8px; } }
</style>
