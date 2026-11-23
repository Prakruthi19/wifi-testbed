<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { DEMO, formatTime } from './api'
import { useSummary } from './stores/summary'
import { useJobs } from './stores/jobs'

// The dashboard shell: a fixed sidebar (a bottom tab bar on phones), a top bar with the data source
// and the theme switch, and the page in the remaining space.
const summary = useSummary()
const jobs = useJobs()
onMounted(() => { summary.load(); jobs.resume() })
const route = useRoute()

const NAV = [
  { to: '/sites', label: 'Sites', icon: 'sites' },
  { to: '/', label: 'Lab', icon: 'lab' },
  { to: '/runs', label: 'Test runs', icon: 'runs' },
  { to: '/coverage', label: 'Coverage', icon: 'coverage' },
  { to: '/start', label: 'Start a run', icon: 'start' },
] as const
// One stroke path per icon, drawn on a 24 x 24 grid.
const ICON: Record<string, string> = {
  sites: 'M3 11l5-4 5 4v8H3zM11 9l5-4 5 4v10h-8M6 19v-4h4v4',
  lab: 'M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3M7 15h10',
  runs: 'M4 5h4v4H4zM4 15h4v4H4zM11 7h9M11 17h9M5 7l1 1 2-2',
  coverage: 'M2 9a15 15 0 0 1 20 0M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0M12 19.5h.01',
  start: 'M7 4l12 8-12 8z',
  collapse: 'M15 6l-6 6 6 6',
  sun: 'M12 4V2M12 22v-2M4 12H2M22 12h-2M5.6 5.6 4.2 4.2M19.8 19.8l-1.4-1.4M5.6 18.4l-1.4 1.4M19.8 4.2l-1.4 1.4M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z',
  moon: 'M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z',
  auto: 'M12 3a9 9 0 1 0 0 18zM12 3a9 9 0 0 1 0 18',
}
const active = (to: string) => (to === '/' ? route.path === '/' : route.path.startsWith(to))

// Remembered per browser; storage can be blocked, so every access is guarded.
const store = {
  get: (k: string) => { try { return localStorage.getItem(k) } catch { return null } },
  set: (k: string, v: string) => { try { localStorage.setItem(k, v) } catch { /* not saved */ } },
}
const collapsed = ref(store.get('nav-collapsed') === '1')
watch(collapsed, (v) => store.set('nav-collapsed', v ? '1' : '0'))

type Theme = 'auto' | 'light' | 'dark'
const theme = ref<Theme>((store.get('theme') as Theme) || 'auto')
const NEXT: Record<Theme, Theme> = { auto: 'light', light: 'dark', dark: 'auto' }
const THEME_LABEL: Record<Theme, string> = { auto: 'Theme: match system', light: 'Theme: light', dark: 'Theme: dark' }
watch(theme, (t) => {
  store.set('theme', t)
  if (t === 'auto') document.documentElement.removeAttribute('data-theme')
  else document.documentElement.setAttribute('data-theme', t)
}, { immediate: true })

const crumb = computed(() => (route.meta.title as string) ?? '')
</script>

<template>
  <div class="shell" :class="{ collapsed }">
    <aside class="side" aria-label="Main">
      <RouterLink to="/sites" class="brand" title="Wi-Fi Test Lab">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path :d="ICON.coverage" /></svg>
        <span class="label">Wi-Fi Test Lab</span>
      </RouterLink>
      <nav>
        <RouterLink v-for="n in NAV" :key="n.to" :to="n.to" class="navitem" :class="{ on: active(n.to) }" :aria-current="active(n.to) ? 'page' : undefined" :title="n.label">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path :d="ICON[n.icon]" /></svg>
          <span class="label">{{ n.label }}</span>
        </RouterLink>
      </nav>
      <button type="button" class="navitem collapse" :aria-label="collapsed ? 'Expand menu' : 'Collapse menu'" :aria-expanded="!collapsed" @click="collapsed = !collapsed">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path :d="ICON.collapse" /></svg>
        <span class="label">Collapse</span>
      </button>
    </aside>

    <div class="main">
      <header class="topbar">
        <span class="crumb"><span class="muted">Wi-Fi Test Lab</span> <span aria-hidden="true">›</span> {{ crumb }}</span>
        <RouterLink v-if="jobs.running && jobs.job" to="/start" class="chip live" :title="`Run ${jobs.job.id} is running; open it`">
          <span class="dot" aria-hidden="true"></span>
          Running: {{ jobs.job.suite }}<template v-if="jobs.job.progress?.total">, {{ jobs.job.progress.done }}/{{ jobs.job.progress.total }}</template>
        </RouterLink>
        <span v-if="summary.data?.sample" class="chip warn" title="Placeholder data for layout only. These are not results from a real lab run.">Sample data</span>
        <span v-else-if="DEMO" class="chip" :title="`Results saved from an emulated lab (virtual radios in a Linux VM), last run ${formatTime(summary.data?.last_finished ?? null)}`">Read-only demo</span>
        <button type="button" class="iconbtn" :aria-label="THEME_LABEL[theme]" :title="THEME_LABEL[theme]" @click="theme = NEXT[theme]">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path :d="ICON[theme === 'auto' ? 'auto' : theme === 'light' ? 'sun' : 'moon']" /></svg>
        </button>
      </header>
      <main>
        <RouterView />
      </main>
    </div>
  </div>
</template>

<style scoped>
.shell { display: grid; grid-template-columns: 232px minmax(0, 1fr); min-height: 100vh; }
.shell.collapsed { grid-template-columns: 64px minmax(0, 1fr); }
.side { position: sticky; top: 0; height: 100vh; display: flex; flex-direction: column; gap: 4px; padding: 12px 10px; background: var(--card); border-right: 1px solid var(--line); }
.brand { display: flex; align-items: center; gap: 10px; padding: 6px 8px 14px; font-weight: 700; color: var(--ink); text-decoration: none; white-space: nowrap; }
.brand svg { width: 26px; height: 26px; flex: none; stroke: var(--accent); stroke-width: 2.2; }
nav { display: grid; gap: 2px; }
.navitem { display: flex; align-items: center; gap: 12px; min-height: 40px; padding: 8px 10px; border-radius: var(--radius); color: var(--muted); text-decoration: none; white-space: nowrap; font-size: 14px; background: none; border: 0; width: 100%; text-align: left; }
.navitem:hover { background: var(--bg); color: var(--ink); }
.navitem.on { background: color-mix(in srgb, var(--accent) 12%, transparent); color: var(--ink); font-weight: 600; }
.navitem.on svg { stroke: var(--accent); }
svg { width: 20px; height: 20px; flex: none; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.collapse { margin-top: auto; }
.collapsed .label { display: none; }
.collapsed .navitem, .collapsed .brand { justify-content: center; padding-left: 0; padding-right: 0; }
.collapsed .collapse svg { transform: rotate(180deg); }
.main { min-width: 0; display: flex; flex-direction: column; }
.topbar { position: sticky; top: 0; z-index: 5; display: flex; align-items: center; gap: 10px; min-height: 56px; padding: 0 24px; background: var(--card); border-bottom: 1px solid var(--line); }
.crumb { flex: 1; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.chip { font-size: 12px; border-radius: var(--radius-sm); padding: 3px 10px; background: var(--bg); border: 1px solid var(--line); color: var(--muted); white-space: nowrap; }
.chip.live { color: var(--ink); text-decoration: none; display: inline-flex; align-items: center; gap: 6px; border-color: var(--accent); }
.chip.live .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent); animation: pulse 1.4s ease-in-out infinite; }
@keyframes pulse { 50% { opacity: .3; } }
@media (prefers-reduced-motion: reduce) { .chip.live .dot { animation: none; } }
.chip.warn { color: var(--skip); background: var(--skip-bg); border-color: transparent; }
.iconbtn { background: none; color: var(--ink); border: 1px solid var(--line); min-height: 36px; width: 36px; padding: 0; display: grid; place-items: center; }
.iconbtn:hover { background: var(--bg); }
main { padding: 20px 24px 40px; max-width: 1600px; width: 100%; }

/* Phones: the sidebar becomes a bottom tab bar. */
@media (max-width: 760px) {
  .shell, .shell.collapsed { grid-template-columns: minmax(0, 1fr); }
  .side { position: fixed; z-index: 10; inset: auto 0 0 0; height: auto; flex-direction: row; padding: 4px; border-right: 0; border-top: 1px solid var(--line); }
  .brand, .collapse { display: none; }
  nav { grid-auto-flow: column; grid-auto-columns: 1fr; width: 100%; }
  .navitem, .collapsed .navitem { flex-direction: column; gap: 2px; font-size: 11px; padding: 6px 2px; justify-content: center; text-align: center; min-height: 52px; }
  .collapsed .label { display: inline; }
  .topbar { padding: 0 16px; }
  main { padding: 16px 16px 88px; }
}
</style>
