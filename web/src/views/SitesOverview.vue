<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import SiteMiniMap from '../components/SiteMiniMap.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { useSites, type Status } from '../stores/sites'

// The portal's front page: every home it watches, worst first, with what is wrong and what just changed.
const store = useSites()
onMounted(store.load)

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'attention', label: 'Needs attention' },
  { key: 'offline', label: 'Offline' },
] as const
const filter = ref<(typeof FILTERS)[number]['key']>('all')
const q = ref('')
const RANK: Record<Status, number> = { offline: 0, degraded: 1, warning: 2, ok: 3 }

const rows = computed(() =>
  store.sites
    .map((site) => ({ site, h: store.health[site.id] }))
    .filter(({ site, h }) =>
      (filter.value === 'all' || (filter.value === 'offline' ? h.status === 'offline' : h.status !== 'ok')) &&
      `${site.name} ${site.area}`.toLowerCase().includes(q.value.trim().toLowerCase()))
    .sort((a, b) => RANK[a.h.status] - RANK[b.h.status] || a.site.name.localeCompare(b.site.name)),
)

const totals = computed(() => {
  const hs = Object.values(store.health)
  return {
    sites: hs.length,
    healthy: hs.filter((h) => h.status === 'ok').length,
    offline: hs.filter((h) => h.status === 'offline').length,
    devices: store.sites.reduce((n, s) => n + s.devices.length, 0),
    online: hs.reduce((n, h) => n + h.connected, 0),
    problems: store.issues.length,
  }
})
const SEV = { offline: 0, problem: 1, warning: 2 }
const openIssues = computed(() => [...store.issues].sort((a, b) => SEV[a.severity] - SEV[b.severity]))
const nameOf = (id: string) => store.byId(id)?.name ?? id
const clock = (t: number) => new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
</script>

<template>
  <h1>Sites</h1>
  <p class="sub">
    Every home this portal watches, worst first. Open a home to see its live floor plan.
    <b>Only "Lab home" comes from the test bed's inventory; the other homes are simulated</b> to show how a portal for many
    homes would work. Health is worked out from the same signal model as the floor plans.
  </p>

  <div class="tiles">
    <div class="tile"><div class="k">Healthy homes</div><div class="v">{{ totals.healthy }} <small>of {{ totals.sites }}</small></div></div>
    <div class="tile"><div class="k">Offline homes</div><div class="v" :class="{ red: totals.offline }">{{ totals.offline }}</div></div>
    <div class="tile"><div class="k">Devices online</div><div class="v">{{ totals.online }} <small>of {{ totals.devices }}</small></div></div>
    <div class="tile"><div class="k">Open problems</div><div class="v" :class="{ amber: totals.problems }">{{ totals.problems }}</div></div>
  </div>

  <div class="layout">
    <section>
      <div class="toolbar">
        <input v-model="q" type="search" placeholder="Search by name or city" aria-label="Search sites" />
        <div role="group" aria-label="Show" class="segs">
          <button v-for="f in FILTERS" :key="f.key" type="button" class="seg" :aria-pressed="filter === f.key" @click="filter = f.key">{{ f.label }}</button>
        </div>
        <label class="check">
          <input v-model="store.live" type="checkbox" />
          Live simulation
        </label>
      </div>
      <p v-if="store.live" class="muted small livehint" aria-live="polite">
        <span class="pulse" aria-hidden="true" /> Every 3 seconds something changes in one simulated home: a box goes off or comes back, or a device moves.
      </p>

      <ul class="key muted small" aria-label="Map key">
        <li><i class="dot big" style="background: var(--series-1)" /> access point on</li>
        <li><i class="dot big hollow" /> access point off</li>
        <li><i class="dot" style="background: var(--pass)" /> device, good signal</li>
        <li><i class="dot" style="background: var(--skip)" /> weak signal</li>
        <li><i class="dot" style="background: var(--fail)" /> unusable or no internet</li>
        <li><i class="dot hollow" /> not seen</li>
      </ul>

      <ul class="cards" aria-label="Sites">
        <li v-for="{ site, h } in rows" :key="site.id">
          <RouterLink :to="{ name: 'site', params: { id: site.id } }" class="sitecard" :class="h.status">
            <div class="head">
              <b class="name">{{ site.name }}</b>
              <StatusBadge :status="h.status" />
            </div>
            <div class="muted small">{{ site.area }}<span v-if="site.simulated"> · simulated</span></div>
            <SiteMiniMap :site="site" :health="h" />
            <div class="stats small">
              <span>Access points on <b>{{ h.apsOn }}/{{ site.aps.length }}</b></span>
              <span>Devices online <b>{{ h.connected }}/{{ site.devices.length }}</b></span>
            </div>
            <p class="issue small" :class="{ none: !h.issues.length }">
              {{ h.issues[0]?.text ?? 'No problems' }}<template v-if="h.issues.length > 1"> (+{{ h.issues.length - 1 }} more)</template>
            </p>
          </RouterLink>
        </li>
      </ul>
      <p v-if="!rows.length" class="muted">No homes match.</p>
    </section>

    <aside>
      <section class="card">
        <h2>Open problems</h2>
        <p v-if="!openIssues.length" class="muted">None.</p>
        <ul class="feed">
          <li v-for="i in openIssues" :key="i.key" :class="i.severity">
            <RouterLink :to="{ name: 'site', params: { id: i.siteId } }">{{ nameOf(i.siteId) }}</RouterLink>: {{ i.text }}
          </li>
        </ul>
      </section>
      <section class="card">
        <h2>Activity</h2>
        <p v-if="!store.activity.length" class="muted small">
          Changes show up here as they happen. Turn on the live simulation, or switch a box off on any home's floor plan.
        </p>
        <ol class="feed" aria-label="Recent changes, newest first">
          <li v-for="(a, i) in store.activity" :key="store.activity.length - i" :class="a.kind === 'clear' ? 'clear' : a.severity">
            <span class="ts">{{ clock(a.at) }}</span>
            <RouterLink :to="{ name: 'site', params: { id: a.siteId } }">{{ nameOf(a.siteId) }}</RouterLink>: {{ a.text }}
          </li>
        </ol>
      </section>
    </aside>
  </div>
</template>

<style scoped>
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 16px; }
.k { font-size: 13px; color: var(--muted); }
.v { font-size: 26px; font-weight: 700; font-variant-numeric: tabular-nums; }
.v small { font-size: 14px; font-weight: 400; color: var(--muted); }
.v.red { color: var(--fail); }
.v.amber { color: var(--skip); }
.layout { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 16px; align-items: start; }
@media (max-width: 960px) { .layout { grid-template-columns: 1fr; } }
.toolbar { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center; margin-bottom: 10px; }
.toolbar input[type='search'] { flex: 1; min-width: 180px; min-height: 40px; padding: 8px 10px; border-radius: 8px; border: 1px solid var(--line); background: var(--card); color: var(--ink); }
.segs { display: flex; gap: 4px; flex-wrap: wrap; }
.seg { background: var(--bg); color: var(--ink); border: 1px solid var(--line); min-height: 36px; padding: 6px 12px; }
.seg[aria-pressed='true'] { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
.check { display: inline-flex; align-items: center; gap: 6px; font-size: 14px; }
.check input { width: 18px; height: 18px; }
.livehint { margin: -2px 0 10px; display: flex; align-items: center; gap: 8px; }
.pulse { width: 10px; height: 10px; border-radius: 50%; background: var(--pass); animation: pulse 1.6s ease-in-out infinite; flex: none; }
@keyframes pulse { 50% { opacity: 0.25; } }
@media (prefers-reduced-motion: reduce) { .pulse { animation: none; } }
.key { list-style: none; padding: 0; margin: 0 0 10px; display: flex; flex-wrap: wrap; gap: 4px 14px; }
.key li { display: inline-flex; align-items: center; gap: 5px; }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.dot.big { width: 12px; height: 12px; }
.dot.hollow { border: 1.5px dashed var(--fail); }
.dot.hollow:not(.big) { border-color: var(--muted); }
.cards { list-style: none; padding: 0; margin: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 12px; }
.sitecard { display: grid; gap: 6px; padding: 12px; border-radius: 10px; background: var(--card); border: 1px solid var(--line); border-top: 4px solid var(--pass); color: var(--ink); text-decoration: none; height: 100%; }
.sitecard.warning { border-top-color: var(--skip); }
.sitecard.degraded, .sitecard.offline { border-top-color: var(--fail); }
.sitecard:hover, .sitecard:focus-visible { border-color: var(--accent); outline: none; box-shadow: 0 0 0 2px var(--accent); }
.head { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.name { font-size: 15px; }
.stats { display: flex; flex-wrap: wrap; gap: 2px 14px; }
.small { font-size: 12px; }
.issue { margin: 0; color: var(--fail); }
.issue.none { color: var(--pass); }
.feed { list-style: none; padding: 0; margin: 0; display: grid; gap: 6px; font-size: 13px; }
.feed li { padding: 6px 8px; border-radius: 6px; border-left: 4px solid var(--skip); background: var(--bg); }
.feed li.offline, .feed li.problem { border-left-color: var(--fail); }
.feed li.clear { border-left-color: var(--pass); }
.ts { color: var(--muted); font-variant-numeric: tabular-nums; margin-right: 6px; }
</style>
