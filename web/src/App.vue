<script setup lang="ts">
import { onMounted } from 'vue'
import { DEMO, formatTime } from './api'
import { useSummary } from './stores/summary'

const summary = useSummary()
onMounted(summary.load)
</script>

<template>
  <header class="top">
    <div class="wrap bar">
      <RouterLink to="/" class="brand">Wi-Fi Test Lab</RouterLink>
      <nav aria-label="Main">
        <RouterLink to="/">Lab</RouterLink>
        <RouterLink to="/runs">Test runs</RouterLink>
        <RouterLink to="/sites">Sites</RouterLink>
        <RouterLink to="/coverage">Coverage</RouterLink>
        <RouterLink to="/start">Start a run</RouterLink>
      </nav>
    </div>
  </header>

  <div v-if="summary.data?.sample" class="banner sample wrap" role="note">
    Placeholder data for layout only. These are not results from a real lab run.
  </div>
  <div v-else-if="DEMO" class="banner wrap" role="note">
    Read-only demo: results saved from an emulated lab (virtual radios in a Linux VM), last run
    {{ formatTime(summary.data?.last_finished ?? null) }}.
  </div>

  <main class="wrap">
    <RouterView />
  </main>
</template>

<style scoped>
.wrap { max-width: 1440px; margin: 0 auto; padding-left: clamp(16px, 3vw, 32px); padding-right: clamp(16px, 3vw, 32px); }
.top { background: var(--card); border-bottom: 1px solid var(--line); }
.bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 56px; flex-wrap: wrap; }
.brand { font-weight: 700; color: var(--ink); text-decoration: none; }
nav { display: flex; gap: 4px; overflow-x: auto; }
nav a { color: var(--muted); text-decoration: none; padding: 8px 10px; border-radius: 8px; white-space: nowrap; }
nav a.router-link-exact-active { color: var(--ink); background: var(--bg); font-weight: 600; }
.banner { margin-top: 12px; padding-top: 8px; padding-bottom: 8px; border-radius: 8px; font-size: 13px; color: var(--muted); background: var(--card); border: 1px solid var(--line); }
.banner.sample { color: var(--skip); background: var(--skip-bg); border-color: transparent; }
main { padding-top: 20px; padding-bottom: 48px; }
</style>
