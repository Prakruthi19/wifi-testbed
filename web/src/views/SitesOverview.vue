<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import SiteMiniMap from '../components/SiteMiniMap.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { useSites, type Status } from '../stores/sites'

// The portal's dashboard: every home it watches on one screen, worst first, with what is wrong and
// what just changed. The list, problems and activity scroll inside their own cards.
const store = useSites()
const router = useRouter()
onMounted(store.load)

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'attention', label: 'Needs attention' },
  { key: 'offline', label: 'Offline' },
] as const
const filter = ref<(typeof FILTERS)[number]['key']>('all')
const q = ref('')
const RANK: Record<Status, number> = { offline: 0, degraded: 1, warning: 2, ok: 3 }

let saved: string | null = null
try { saved = localStorage.getItem('sites-view') } catch { /* storage blocked */ }
// Phones start on cards (a table squeezed into a phone is long); a saved choice wins.
const narrow = typeof matchMedia === 'function' && matchMedia('(max-width: 640px)').matches
const view = ref<'table' | 'cards'>(saved === 'cards' || saved === 'table' ? saved : narrow ? 'cards' : 'table')
watch(view, (v) => { try { localStorage.setItem('sites-view', v) } catch { /* not saved */ } })

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
const open = (id: string) => router.push({ name: 'site', params: { id } })
</script>

<template>
  <div class="head">
    <div class="title">
      <h1>Sites</h1>
      <span class="muted small">{{ totals.sites }} homes, worst first</span>
    </div>
    <details class="about">
      <summary>About this data</summary>
      <p>
        Only "Lab home" comes from the test bed's inventory; <b>the other homes are simulated</b> to show how a portal for
        many homes would work. Health is worked out from the same signal model as the floor plans, not from real radios.
      </p>
    </details>
    <label class="switch">
      <input v-model="store.live" type="checkbox" role="switch" />
      <span class="track" aria-hidden="true"><span /></span>
      Live simulation
    </label>
  </div>

  <div class="kpis">
    <div class="kpi"><span class="k">Healthy homes</span><b>{{ totals.healthy }}<small> / {{ totals.sites }}</small></b></div>
    <div class="kpi" :class="{ red: totals.offline }"><span class="k">Offline homes</span><b>{{ totals.offline }}</b></div>
    <div class="kpi"><span class="k">Devices online</span><b>{{ totals.online }}<small> / {{ totals.devices }}</small></b></div>
    <div class="kpi" :class="{ amber: totals.problems }"><span class="k">Open problems</span><b>{{ totals.problems }}</b></div>
  </div>

  <div class="dash">
    <section class="panel homes" aria-labelledby="homes-h">
      <div class="toolbar">
        <h2 id="homes-h">Homes</h2>
        <input v-model="q" type="search" placeholder="Search name or city" aria-label="Search sites" />
        <div role="group" aria-label="Show" class="segs">
          <button v-for="f in FILTERS" :key="f.key" type="button" class="seg" :aria-pressed="filter === f.key" @click="filter = f.key">{{ f.label }}</button>
        </div>
        <div role="group" aria-label="View" class="segs">
          <button type="button" class="seg" :aria-pressed="view === 'table'" @click="view = 'table'">Table</button>
          <button type="button" class="seg" :aria-pressed="view === 'cards'" @click="view = 'cards'">Cards</button>
        </div>
      </div>
      <p v-if="store.live" class="livehint muted small" aria-live="polite">
        <span class="pulse" aria-hidden="true" /> Every 3 seconds something changes in one simulated home.
      </p>

      <div class="scroller">
        <table v-if="view === 'table'" class="stack sites" aria-label="Homes">
          <thead>
            <tr><th>Status</th><th>Home</th><th class="mapcol">Plan</th><th>APs on</th><th>Devices</th><th>Top problem</th></tr>
          </thead>
          <tbody>
            <tr v-for="{ site, h } in rows" :key="site.id" :class="h.status" @click="open(site.id)">
              <td data-label="Status"><StatusBadge :status="h.status" /></td>
              <td data-label="Home">
                <RouterLink :to="{ name: 'site', params: { id: site.id } }" class="name" @click.stop>{{ site.name }}</RouterLink>
                <div class="muted small">{{ site.area }}<span v-if="site.simulated"> · simulated</span></div>
              </td>
              <td class="mapcol"><SiteMiniMap :site="site" :health="h" class="thumb" /></td>
              <td data-label="APs on" class="num">{{ h.apsOn }}/{{ site.aps.length }}</td>
              <td data-label="Devices online" class="num">{{ h.connected }}/{{ site.devices.length }}</td>
              <td data-label="Top problem" class="issue" :class="{ none: !h.issues.length }">
                {{ h.issues[0]?.text ?? 'No problems' }}<span v-if="h.issues.length > 1" class="muted"> +{{ h.issues.length - 1 }}</span>
              </td>
            </tr>
          </tbody>
        </table>

        <template v-else>
          <ul class="key muted small" aria-label="Map key">
            <li><i class="dot big" style="background: var(--series-1)" /> access point on</li>
            <li><i class="dot big hollow" /> access point off</li>
            <li><i class="dot" style="background: var(--pass)" /> good signal</li>
            <li><i class="dot" style="background: var(--skip)" /> weak</li>
            <li><i class="dot" style="background: var(--fail)" /> unusable or no internet</li>
            <li><i class="dot hollow" /> not seen</li>
          </ul>
          <ul class="cards" aria-label="Homes">
            <li v-for="{ site, h } in rows" :key="site.id">
              <RouterLink :to="{ name: 'site', params: { id: site.id } }" class="sitecard" :class="h.status">
                <div class="chead"><b>{{ site.name }}</b><StatusBadge :status="h.status" /></div>
                <div class="muted small">{{ site.area }}<span v-if="site.simulated"> · simulated</span></div>
                <SiteMiniMap :site="site" :health="h" />
                <div class="small">APs on <b>{{ h.apsOn }}/{{ site.aps.length }}</b> · devices online <b>{{ h.connected }}/{{ site.devices.length }}</b></div>
                <p class="issue small" :class="{ none: !h.issues.length }">{{ h.issues[0]?.text ?? 'No problems' }}</p>
              </RouterLink>
            </li>
          </ul>
        </template>
        <p v-if="!rows.length" class="muted">No homes match.</p>
      </div>
    </section>

    <div class="rail">
      <section class="panel" aria-labelledby="prob-h">
        <h2 id="prob-h">Open problems <span class="count">{{ openIssues.length }}</span></h2>
        <div class="scroller">
          <p v-if="!openIssues.length" class="muted small">None.</p>
          <ul class="feed">
            <li v-for="i in openIssues" :key="i.key" :class="i.severity">
              <RouterLink :to="{ name: 'site', params: { id: i.siteId } }">{{ nameOf(i.siteId) }}</RouterLink>: {{ i.text }}
            </li>
          </ul>
        </div>
      </section>
      <section class="panel" aria-labelledby="act-h">
        <h2 id="act-h">Activity</h2>
        <div class="scroller">
          <p v-if="!store.activity.length" class="muted small">
            Changes show up here as they happen. Turn on the live simulation, or switch a box off on any home's floor plan.
          </p>
          <ol class="feed" aria-label="Recent changes, newest first">
            <li v-for="(a, i) in store.activity" :key="store.activity.length - i" :class="a.kind === 'clear' ? 'clear' : a.severity">
              <span class="ts">{{ clock(a.at) }}</span>
              <RouterLink :to="{ name: 'site', params: { id: a.siteId } }">{{ nameOf(a.siteId) }}</RouterLink>: {{ a.text }}
            </li>
          </ol>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.sites th { white-space: nowrap; }
.head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 20px; margin-bottom: 14px; }
.title { display: flex; align-items: baseline; gap: 10px; flex: 1; min-width: 200px; }
.title h1 { margin: 0; }
.small { font-size: 12px; }
.about { font-size: 13px; position: relative; }
.about summary { cursor: pointer; color: var(--accent); list-style: none; }
.about summary::before { content: 'ⓘ '; }
.about p { position: absolute; right: 0; z-index: 4; width: min(360px, 80vw); margin: 6px 0 0; padding: 12px; background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: 0 6px 24px rgb(0 0 0 / 0.12); }
.switch { display: inline-flex; align-items: center; gap: 8px; font-size: 14px; cursor: pointer; }
.switch input { position: absolute; opacity: 0; width: 1px; height: 1px; }
.track { width: 36px; height: 20px; border-radius: var(--radius-sm); background: var(--line); position: relative; transition: background 0.15s; }
.track span { position: absolute; top: 2px; left: 2px; width: 16px; height: 16px; border-radius: 50%; background: var(--card); transition: transform 0.15s; box-shadow: 0 1px 2px rgb(0 0 0 / 0.3); }
.switch input:checked + .track { background: var(--pass); }
.switch input:checked + .track span { transform: translateX(16px); }
.switch input:focus-visible + .track { outline: 2px solid var(--accent); outline-offset: 2px; }

.kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 12px; }
.kpi { background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); padding: 12px 16px; display: grid; gap: 2px; }
.kpi .k { font-size: 12px; color: var(--muted); }
.kpi b { font-size: 28px; line-height: 1.1; font-variant-numeric: tabular-nums; }
.kpi small { font-size: 14px; font-weight: 400; color: var(--muted); }
.kpi.red b { color: var(--fail); }
.kpi.amber b { color: var(--skip); }

/* One screen: the three panels fill the rest of the window and scroll inside. */
.dash { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 12px; height: calc(100vh - 250px); min-height: 440px; }
.rail { display: grid; grid-template-rows: 1fr 1fr; gap: 12px; min-height: 0; }
.panel { background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); padding: 14px 16px; display: flex; flex-direction: column; min-height: 0; }
.panel h2 { font-size: 15px; margin: 0 0 8px; }
.count { font-size: 12px; font-weight: 600; background: var(--bg); border-radius: var(--radius-sm); padding: 1px 8px; margin-left: 4px; }
.scroller { overflow: auto; min-height: 0; flex: 1; }
.toolbar { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; margin-bottom: 10px; }
.toolbar h2 { margin: 0 8px 0 0; }
.toolbar input[type='search'] { flex: 1; min-width: 160px; min-height: 36px; padding: 6px 10px; border-radius: var(--radius); border: 1px solid var(--line); background: var(--bg); color: var(--ink); }
.segs { display: flex; gap: 2px; background: var(--bg); border-radius: var(--radius); padding: 2px; }
.seg { background: none; color: var(--muted); border: 0; min-height: 32px; padding: 4px 10px; font-size: 13px; border-radius: var(--radius); }
.seg[aria-pressed='true'] { background: var(--card); color: var(--ink); font-weight: 600; box-shadow: 0 1px 2px rgb(0 0 0 / 0.12); }
.livehint { margin: -4px 0 8px; display: flex; align-items: center; gap: 8px; }
.pulse { width: 8px; height: 8px; border-radius: 50%; background: var(--pass); animation: pulse 1.6s ease-in-out infinite; flex: none; }
@keyframes pulse { 50% { opacity: 0.25; } }
@media (prefers-reduced-motion: reduce) { .pulse { animation: none; } }

.sites th { position: sticky; top: 0; background: var(--card); z-index: 1; }
.sites td { vertical-align: middle; padding: 8px; font-size: 14px; }
.sites tbody tr { cursor: pointer; }
.sites tbody tr:hover { background: var(--bg); }
.sites tbody tr td:first-child { border-left: 3px solid var(--pass); }
.sites tbody tr.warning td:first-child { border-left-color: var(--skip); }
.sites tbody tr.degraded td:first-child, .sites tbody tr.offline td:first-child { border-left-color: var(--fail); }
.name { font-weight: 600; color: var(--ink); text-decoration: none; }
.name:hover, .name:focus-visible { text-decoration: underline; }
.thumb { width: 84px; }
.issue { color: var(--fail); font-size: 13px; }
.issue.none { color: var(--pass); }
.num { font-variant-numeric: tabular-nums; white-space: nowrap; }

.key { list-style: none; padding: 0; margin: 0 0 10px; display: flex; flex-wrap: wrap; gap: 4px 14px; }
.key li { display: inline-flex; align-items: center; gap: 5px; }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.dot.big { width: 12px; height: 12px; }
.dot.hollow { border: 1.5px dashed var(--fail); }
.dot.hollow:not(.big) { border-color: var(--muted); }
.cards { list-style: none; padding: 0; margin: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; }
.sitecard { display: grid; gap: 6px; padding: 10px; border-radius: var(--radius); background: var(--bg); border: 1px solid var(--line); border-top: 3px solid var(--pass); color: var(--ink); text-decoration: none; height: 100%; }
.sitecard.warning { border-top-color: var(--skip); }
.sitecard.degraded, .sitecard.offline { border-top-color: var(--fail); }
.sitecard:hover, .sitecard:focus-visible { outline: 2px solid var(--accent); }
.chead { display: flex; justify-content: space-between; align-items: center; gap: 8px; font-size: 14px; }
.sitecard .issue { margin: 0; font-size: 12px; }

.feed { list-style: none; padding: 0; margin: 0; display: grid; gap: 6px; font-size: 13px; }
.feed li { padding: 6px 8px; border-radius: var(--radius); border-left: 3px solid var(--skip); background: var(--bg); }
.feed li.offline, .feed li.problem { border-left-color: var(--fail); }
.feed li.clear { border-left-color: var(--pass); }
.ts { color: var(--muted); font-variant-numeric: tabular-nums; margin-right: 6px; }

/* Smaller screens: panels stack and the page scrolls normally. */
@media (max-width: 1100px) {
  .dash { grid-template-columns: 1fr; height: auto; }
  .homes .scroller { max-height: 70vh; }
  .rail { grid-template-rows: auto; }
  .rail .scroller { max-height: 320px; }
}
@media (max-width: 640px) {
  .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .mapcol { display: none; }
  .sites tbody tr td:first-child { border-left: 0; }
  .sites tbody tr { border-left: 3px solid var(--pass); padding-left: 8px; }
  .sites tbody tr.warning { border-left-color: var(--skip); }
  .sites tbody tr.degraded, .sites tbody tr.offline { border-left-color: var(--fail); }
}
</style>
