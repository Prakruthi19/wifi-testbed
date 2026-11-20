<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, formatTime, testName, type RunDetail } from '../api'
import OutcomeBadge from '../components/OutcomeBadge.vue'
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
const results = computed(() => [...(run.value?.results ?? [])].sort((a, b) => order[a.outcome] - order[b.outcome]))
const facts = (p: Record<string, unknown>) =>
  Object.entries(p).filter(([, v]) => typeof v !== 'object' || v === null)
</script>

<template>
  <p><RouterLink to="/runs">← All runs</RouterLink></p>
  <p v-if="error" class="error">Could not load this run: {{ error }}</p>
  <template v-else-if="run">
    <h1>Run of {{ formatTime(run.finished) }}</h1>
    <p class="sub">{{ run.counts.passed }} passed · {{ run.counts.failed + run.counts.error }} failed · {{ run.counts.skipped }} skipped</p>

    <article v-for="r in results" :key="r.nodeid" class="card">
      <header class="head">
        <OutcomeBadge :outcome="r.outcome" />
        <h2>{{ testName(r.nodeid) }}</h2>
        <span class="muted">{{ r.suite }} · {{ r.duration_s }} s</span>
      </header>
      <p v-if="r.message" :class="r.outcome === 'skipped' ? 'muted' : 'msg'">{{ r.message }}</p>
      <JoinTimeline v-if="r.classifier_stage" :stage="r.classifier_stage" :enterprise="r.suite === 'enterprise'" />
      <dl v-if="facts(r.properties).length" class="facts">
        <template v-for="[k, v] in facts(r.properties)" :key="k">
          <dt>{{ k }}</dt><dd>{{ v }}</dd>
        </template>
      </dl>
      <p v-if="r.files.length" class="files">
        <template v-for="f in r.files" :key="f">
          <a v-if="api.artifactUrl(r.artifact_dir, f)" :href="api.artifactUrl(r.artifact_dir, f)!">{{ f }}</a>
          <span v-else class="muted">{{ f }}</span>
        </template>
      </p>
    </article>
  </template>
  <p v-else class="muted">Loading…</p>
</template>

<style scoped>
.head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 10px; }
.head h2 { margin: 0; font-size: 16px; overflow-wrap: anywhere; }
.msg { color: var(--fail); overflow-wrap: anywhere; }
.facts { display: grid; grid-template-columns: max-content 1fr; gap: 2px 12px; font-size: 13px; margin: 8px 0 0; }
.facts dt { color: var(--muted); }
.facts dd { margin: 0; overflow-wrap: anywhere; }
.files { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 13px; }
</style>
