<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { api, formatTime, testName, type RunDetail, type TestResult } from '../api'
import { useRuns } from '../stores/runs'
import { describe, facts, fileLabel, stepLabel, suiteLabel, variantOf } from '../describe'
import JoinTimeline from '../components/JoinTimeline.vue'
import { failedCount, formatDuration, runSentence, testTime, tone } from '../runs'

const props = defineProps<{ id: string }>()
const store = useRuns()
const run = ref<RunDetail | null>(null)
const error = ref<string | null>(null)

watch(
  () => props.id,
  async (id) => {
    error.value = null
    // Shown at once if the Test runs page already loaded it; fetched (and kept) otherwise.
    run.value = store.details[id] ?? null
    try {
      run.value = await store.run(id)
    } catch (e) {
      error.value = (e as Error).message
    }
  },
  { immediate: true },
)

// Failures first, so the thing to look at is at the top.
const order = { failed: 0, error: 1, skipped: 2, passed: 3 }
const results = computed(() =>
  [...(run.value?.results ?? [])]
    .sort((a, b) => order[a.outcome] - order[b.outcome])
    .map((r) => ({ r, info: describe(r.nodeid), facts: facts(r.properties) })),
)

// Which rows are open: failed and crashed tests start open, so the problem is the first thing seen.
const openRows = reactive(new Set<string>())
// immediate: a run from the cache is already set before this watcher exists.
watch(run, (r) => {
  openRows.clear()
  r?.results.forEach((t) => (t.outcome === 'failed' || t.outcome === 'error') && openRows.add(t.nodeid))
}, { immediate: true })
const toggle = (id: string) => (openRows.has(id) ? openRows.delete(id) : openRows.add(id))
const allOpen = computed(() => results.value.length > 0 && results.value.every(({ r }) => openRows.has(r.nodeid)))
const toggleAll = () => {
  const open = !allOpen.value
  results.value.forEach(({ r }) => (open ? openRows.add(r.nodeid) : openRows.delete(r.nodeid)))
}

const show = ref<'all' | 'failed' | 'passed' | 'skipped'>('all')
const visible = computed(() => results.value.filter(({ r }) =>
  show.value === 'all' || (show.value === 'failed' ? r.outcome === 'failed' || r.outcome === 'error' : r.outcome === show.value)))
const RESULT_LABEL = { passed: 'Passed', failed: 'Failed', error: 'Crashed', skipped: 'Skipped' } as const

// One sentence saying what the result means, in words.
function verdict(r: TestResult, expectStop?: string) {
  const stage = r.classifier_stage
  if (r.outcome === 'skipped') return { cls: 'skip', icon: '–', text: `Skipped: ${r.message || 'not run this time'}` }
  if (r.outcome === 'error') return { cls: 'bad', icon: '✕', text: 'The test itself crashed before it could check anything.' }
  if (r.outcome === 'failed') {
    if (expectStop && stage && expectStop !== stage)
      return { cls: 'bad', icon: '✕', text: `Test failed: expected the join to stop at "${stepLabel(expectStop)}", but it stopped at "${stepLabel(stage)}".` }
    return { cls: 'bad', icon: '✕', text: 'Test failed.' }
  }
  if (expectStop && expectStop !== 'success')
    return { cls: 'good', icon: '✓', text: `Test passed: the connection failed on purpose, and the lab correctly found where ("${stepLabel(expectStop)}").` }
  return { cls: 'good', icon: '✓', text: 'Test passed.' }
}
</script>

<template>
  <p class="crumbs"><RouterLink to="/runs">Test runs</RouterLink> <span aria-hidden="true">/</span> {{ run ? formatTime(run.finished) : '…' }}</p>
  <p v-if="error" class="error">Could not load this run: {{ error }}</p>
  <template v-else-if="run">
    <div class="head">
      <h1>Test run of {{ formatTime(run.finished) }}</h1>
      <span class="status big" :class="tone(run.counts)">{{ runSentence(run.counts, run.results) }}</span>
    </div>

    <div class="tiles kpis">
      <div class="tile"><span>Passed</span><b class="good">{{ run.counts.passed }}</b></div>
      <div class="tile"><span>Failed</span><b :class="{ bad: failedCount(run.counts) }">{{ failedCount(run.counts) }}</b></div>
      <div class="tile"><span>Skipped</span><b :class="{ skip: run.counts.skipped }">{{ run.counts.skipped }}</b></div>
      <div class="tile"><span>Test time</span><b>{{ formatDuration(testTime(run)) }}</b></div>
    </div>

    <details class="howto">
      <summary>How to read this</summary>
      Each row is one automated test; open a row for what it does, how far the device got and the saved evidence.
      Many tests break the network on purpose: they <b>pass</b> when the device fails to connect <b>at the step the test expects</b>,
      because that proves the lab can find where a real failure happens.
    </details>

    <div class="panel">
      <div class="toolbar">
        <div role="group" aria-label="Show" class="tabs">
          <button v-for="k in (['all', 'failed', 'passed', 'skipped'] as const)" :key="k" type="button" :aria-pressed="show === k" @click="show = k">
            {{ k === 'all' ? 'All' : RESULT_LABEL[k] }}
            <span class="count">{{ k === 'all' ? run.results.length : k === 'failed' ? failedCount(run.counts) : run.counts[k] }}</span>
          </button>
        </div>
        <button type="button" class="ghost" @click="toggleAll">{{ allOpen ? 'Collapse all' : 'Expand all' }}</button>
      </div>

      <p v-if="!visible.length" class="muted pad">No tests with this result.</p>
      <table v-else class="stack tests" aria-label="Tests in this run">
        <thead><tr><th>Result</th><th>Test</th><th>Suite</th><th>Device stopped at</th><th>Time</th></tr></thead>
        <tbody>
          <template v-for="{ r, info, facts: fs } in visible" :key="r.nodeid">
            <tr class="row" :class="{ open: openRows.has(r.nodeid) }" @click="toggle(r.nodeid)">
              <td data-label="Result"><span class="status" :class="r.outcome === 'passed' ? 'good' : r.outcome === 'skipped' ? 'skip' : 'bad'">{{ RESULT_LABEL[r.outcome] }}</span></td>
              <td data-label="Test">
                <button type="button" class="name" :aria-expanded="openRows.has(r.nodeid)" @click.stop="toggle(r.nodeid)">
                  <span class="chev" aria-hidden="true">›</span>{{ info.title }}
                </button>
                <code v-if="variantOf(r.nodeid)" class="variant">{{ variantOf(r.nodeid) }}</code>
              </td>
              <td data-label="Suite" class="muted hide-sm">{{ suiteLabel(r.suite, r.nodeid) }}</td>
              <td data-label="Device stopped at">{{ r.classifier_stage ? stepLabel(r.classifier_stage) : '—' }}</td>
              <td data-label="Time" class="num hide-sm">{{ formatDuration(r.duration_s) }}</td>
            </tr>
            <tr v-if="openRows.has(r.nodeid)" class="detail">
              <td colspan="5">
                <article :aria-label="info.title">
                  <p class="verdict" :class="verdict(r, info.expectStop).cls">
                    <span class="icon" aria-hidden="true">{{ verdict(r, info.expectStop).icon }}</span>
                    {{ verdict(r, info.expectStop).text }}
                  </p>
                  <p v-if="info.what" class="what"><span class="label">What it does:</span> {{ info.what }}</p>
                  <p v-if="r.message && r.outcome !== 'skipped'" class="msg"><span class="label">Error message:</span> {{ r.message }}</p>

                  <div v-if="r.classifier_stage" class="block">
                    <span class="label">How far the device got (read from the packet capture):</span>
                    <JoinTimeline :stage="r.classifier_stage" :enterprise="r.suite === 'enterprise'" :expect-stop="info.expectStop" />
                  </div>

                  <div class="cols">
                    <div v-if="fs.length" class="block">
                      <span class="label">Measured:</span>
                      <dl class="facts">
                        <template v-for="f in fs" :key="f.key">
                          <dt>{{ f.label }}</dt>
                          <dd>{{ f.value }} <span v-if="f.hint" class="muted">({{ f.hint }})</span></dd>
                        </template>
                      </dl>
                    </div>
                    <div v-if="r.files.length" class="block">
                      <span class="label">Evidence saved:</span>
                      <ul class="files">
                        <li v-for="f in r.files" :key="f">
                          <a v-if="api.artifactUrl(r.artifact_dir, f)" :href="api.artifactUrl(r.artifact_dir, f)!">{{ fileLabel(f) }}</a>
                          <span v-else>{{ fileLabel(f) }}</span>
                          <span class="muted"> · {{ f }}</span>
                        </li>
                      </ul>
                    </div>
                  </div>
                  <p class="muted small">Test id: <code>{{ testName(r.nodeid) }}</code></p>
                </article>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </template>
  <p v-else class="muted">Loading…</p>
</template>

<style scoped>
.crumbs { font-size: 14px; color: var(--muted); margin: 0 0 8px; }
.head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 16px; margin-bottom: 16px; }
.head h1 { margin: 0; }
.kpis { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.tile b.good { color: var(--pass); } .tile b.bad { color: var(--fail); } .tile b.skip { color: var(--skip); }
.howto { margin: 0 0 16px; font-size: 14px; color: var(--muted); }
.howto summary { cursor: pointer; color: var(--accent); }
.status { display: inline-block; padding: 2px 8px; font-size: 12px; font-weight: 600; border-radius: var(--radius-sm); white-space: nowrap; }
.status.big { font-size: 14px; padding: 4px 10px; white-space: normal; }
.status.good { color: var(--pass); background: var(--pass-bg); }
.status.bad { color: var(--fail); background: var(--fail-bg); }
.status.skip { color: var(--skip); background: var(--skip-bg); }

.panel { background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); overflow: hidden; }
.toolbar { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px; padding: 0 16px; border-bottom: 1px solid var(--line); }
.tabs { display: flex; gap: 4px; flex-wrap: wrap; }
.tabs button { background: none; color: var(--muted); border-radius: 0; padding: 14px 10px 12px; border-bottom: 2px solid transparent; font-weight: 600; min-height: 0; }
.tabs button[aria-pressed='true'] { color: var(--ink); border-bottom-color: var(--accent); }
.count { display: inline-block; min-width: 20px; margin-left: 4px; padding: 0 6px; font-size: 12px; background: var(--bg); border: 1px solid var(--line); border-radius: var(--radius-sm); color: var(--muted); }
.ghost { background: none; color: var(--accent); border: 1px solid var(--line); min-height: 32px; padding: 4px 10px; font-size: 14px; }
.pad { padding: 16px; margin: 0; }

.tests th { white-space: nowrap; padding: 10px 16px; background: var(--bg); border-bottom: 1px solid var(--line); font-size: 12px; text-transform: uppercase; letter-spacing: .03em; }
.tests td { padding: 10px 16px; vertical-align: middle; }
.row { cursor: pointer; }
.row:hover, .row.open { background: var(--bg); }
.name { background: none; color: var(--ink); padding: 0; min-height: 0; font-weight: 600; text-align: left; display: inline-flex; gap: 8px; align-items: baseline; }
.variant { margin-left: 6px; font-size: 11px; color: var(--muted); background: var(--bg); border: 1px solid var(--line); border-radius: var(--radius-sm); padding: 0 5px; }
.chev { display: inline-block; color: var(--muted); transition: transform .15s; }
.open .chev { transform: rotate(90deg); }
.detail td { border-top: 0; padding: 4px 16px 16px 16px; background: var(--bg); }
.detail article { background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); padding: 12px 16px; }
.cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 0 24px; }
.small { font-size: 12px; margin: 12px 0 0; }
code { font-size: 12px; }
.verdict { display: flex; gap: 8px; align-items: flex-start; margin: 0 0 10px; padding: 8px 12px; border-radius: var(--radius-sm); font-weight: 500; }
.verdict .icon { font-weight: 700; }
.verdict.good { background: var(--pass-bg); color: var(--pass); }
.verdict.bad { background: var(--fail-bg); color: var(--fail); }
.verdict.skip { background: var(--skip-bg); color: var(--skip); }
.label { color: var(--muted); font-size: 13px; font-weight: 600; }
.what, .msg { margin: 6px 0; }
.msg { overflow-wrap: anywhere; }
.block { margin-top: 12px; }
.facts { display: grid; grid-template-columns: max-content 1fr; gap: 4px 16px; font-size: 14px; margin: 6px 0 0; }
.facts dt { color: var(--muted); }
.facts dd { margin: 0; overflow-wrap: anywhere; }
.files { list-style: none; padding: 0; margin: 6px 0 0; font-size: 14px; display: grid; gap: 2px; }
@media (max-width: 900px) { .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 640px) {
  .tests td { padding: 4px 16px; }
  .hide-sm { display: none !important; }
  .tabs { flex-wrap: nowrap; overflow-x: auto; }
  .tabs button { padding: 12px 6px 10px; white-space: nowrap; }
  .toolbar .ghost { display: none; }
  .detail td { display: block; padding: 8px; }
  .detail td::before { display: none; }
  .facts { grid-template-columns: 1fr; gap: 0 0; } .facts dd { margin-bottom: 6px; }
}
</style>
