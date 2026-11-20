<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, formatTime, testName, type RunDetail, type TestResult } from '../api'
import { describe, facts, fileLabel, stepLabel, SUITES } from '../describe'
import JoinTimeline from '../components/JoinTimeline.vue'

const props = defineProps<{ id: string }>()
const run = ref<RunDetail | null>(null)
const error = ref<string | null>(null)

watch(
  () => props.id,
  async (id) => {
    run.value = null
    error.value = null
    try {
      run.value = await api.run(id)
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
  <p><RouterLink to="/runs">← All runs</RouterLink></p>
  <p v-if="error" class="error">Could not load this run: {{ error }}</p>
  <template v-else-if="run">
    <h1>Test run of {{ formatTime(run.finished) }}</h1>
    <p class="sub">
      {{ run.counts.passed }} passed · {{ run.counts.failed + run.counts.error }} failed · {{ run.counts.skipped }} skipped.
      Each card is one automated test. Many tests break the network on purpose: they <b>pass</b> when the device
      fails to connect <b>at the step the test expects</b>, because that proves the lab can find where a real failure happens.
    </p>

    <article v-for="{ r, info, facts: fs } in results" :key="r.nodeid" class="card">
      <header>
        <h2>{{ info.title }}</h2>
        <span class="muted small">{{ SUITES[r.suite] ?? r.suite }} · took {{ r.duration_s }} s · <code>{{ testName(r.nodeid) }}</code></span>
      </header>

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
    </article>
  </template>
  <p v-else class="muted">Loading…</p>
</template>

<style scoped>
header { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 12px; }
header h2 { margin: 0; font-size: 17px; }
.small { font-size: 12px; }
code { font-size: 12px; }
.verdict { display: flex; gap: 8px; align-items: flex-start; margin: 10px 0; padding: 8px 12px; border-radius: 8px; font-weight: 500; }
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
@media (max-width: 640px) { .facts { grid-template-columns: 1fr; gap: 0 0; } .facts dd { margin-bottom: 6px; } }
</style>
