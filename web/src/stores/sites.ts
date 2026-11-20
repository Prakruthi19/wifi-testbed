import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { api, type Lab } from '../api'
import { best, iconOf, rssi, GOOD_DBM, USABLE_DBM, type Band, type Node } from '../rfmodel'

// The homes the portal monitors. "Lab home" is built from the test bed's own inventory (its access
// points and devices); every other site is SIMULATED, to show how a portal for many homes would work.
// Each site's health is worked out from the signal model and from which boxes are switched on, so
// changing a site (on its map, or with the live simulation) changes its status everywhere.

export interface Site { id: string; name: string; area: string; simulated: boolean; aps: Node[]; devices: Node[] }
export type Status = 'ok' | 'warning' | 'degraded' | 'offline'
export interface Issue { key: string; siteId: string; severity: 'offline' | 'problem' | 'warning'; text: string }
export interface DeviceState { d: Node; band: Band | null; dbm: number | null; ap: string | null; state: 'good' | 'weak' | 'unusable' | 'not seen' | 'no internet' }
export interface Health { status: Status; issues: Issue[]; devices: DeviceState[]; connected: number; apsOn: number }
export interface Activity { at: number; siteId: string; text: string; kind: 'open' | 'clear'; severity: Issue['severity'] }

type Spot = [number, number]
type DevSpec = [name: string, bands: string, at: Spot, on?: boolean]

const ap = (name: string, at: Spot, channel: number, on = true): Node => ({ name, x: at[0], y: at[1], on, detail: `channel ${channel}`, icon: 'ap' })
const dev = ([name, bands, at, on = true]: DevSpec): Node => ({
  name, x: at[0], y: at[1], on, bands: bands.split('+'), icon: iconOf(name), detail: `radios: ${bands.replace('+', ' + ')} GHz`,
})

// The lab home: the router on the office desk, one mesh point in the living room and one by the bedrooms.
const LAB_APS: Spot[] = [[70, 420], [225, 70], [625, 268]]
const LAB_SPOTS: Record<string, Spot> = { phone: [110, 170], laptop: [125, 422], camera: [420, 405], plug: [365, 140], speaker: [190, 255] }
const SPARE: Spot[] = [[150, 250], [600, 200], [400, 300]]

function labSite(lab: Lab | null): Site {
  const home = lab?.home
  const apList = home?.access_points ?? [{ name: 'router', channel: 6 }, { name: 'mesh-living', channel: 1 }, { name: 'mesh-bedroom', channel: 11 }]
  let spare = 0
  return {
    id: 'lab',
    name: 'Lab home',
    area: 'Emulated test bed',
    simulated: false,
    aps: apList.slice(0, 3).map((a, i) => ap(a.name, LAB_APS[i], a.channel)),
    devices: (home?.devices ?? []).slice(0, 6).map((d) => ({
      ...dev([d.name, d.bands.join('+'), LAB_SPOTS[iconOf(d.name)] ?? SPARE[spare++ % SPARE.length]]),
      detail: `${d.profile}, radios: ${d.bands.join(' + ')} GHz`,
    })),
  }
}

// Simulated homes. Each starts in a different state so the overview has something to show.
const SIMULATED: (() => Site)[] = [
  () => ({ id: 'maple-12', name: '12 Maple Street', area: 'Austin, TX', simulated: true,
    aps: [ap('router', [70, 420], 6), ap('mesh-1', [225, 70], 1), ap('mesh-2', [625, 268], 11)],
    devices: [['phone', '2.4+5', [110, 170]], ['laptop', '2.4+5', [125, 422]], ['tv', '2.4+5', [245, 150]], ['camera', '2.4', [420, 405]], ['plug', '2.4', [365, 140]]].map((s) => dev(s as DevSpec)) }),
  () => ({ id: 'harbor-4b', name: 'Harbor View, apt 4B', area: 'Seattle, WA', simulated: true,
    aps: [ap('router', [670, 430], 11)],
    devices: [['phone', '2.4+5', [560, 120]], ['laptop', '2.4+5', [120, 200]], ['plug', '2.4', [40, 40]], ['speaker', '2.4', [60, 420]]].map((s) => dev(s as DevSpec)) }),
  () => ({ id: 'oak-7', name: '7 Oak Lane', area: 'Denver, CO', simulated: true,
    aps: [ap('router', [360, 60], 1), ap('mesh-1', [600, 350], 6, false)],
    devices: [['phone', '2.4+5', [640, 400]], ['tablet', '2.4+5', [560, 100]], ['camera', '2.4', [600, 440]], ['tv', '2.4+5', [100, 250]]].map((s) => dev(s as DevSpec)) }),
  () => ({ id: 'river-31', name: '31 Riverside Drive', area: 'Portland, OR', simulated: true,
    aps: [ap('router', [70, 420], 6, false), ap('mesh-1', [560, 262], 11)],
    devices: [['phone', '2.4+5', [140, 150]], ['laptop', '2.4+5', [520, 380]], ['plug', '2.4', [300, 60]]].map((s) => dev(s as DevSpec)) }),
  () => ({ id: 'cedar-2', name: '2 Cedar Court', area: 'Raleigh, NC', simulated: true,
    aps: [ap('router', [360, 330], 6), ap('mesh-1', [580, 140], 11)],
    devices: [['phone', '2.4+5', [200, 200]], ['laptop', '2.4+5', [120, 420]], ['speaker', '2.4', [600, 400]]].map((s) => dev(s as DevSpec)) }),
  () => ({ id: 'hilltop-18', name: '18 Hilltop Road', area: 'San Diego, CA', simulated: true,
    aps: [ap('router', [70, 420], 1), ap('mesh-1', [300, 100], 6), ap('mesh-2', [600, 300], 11)],
    devices: [['phone', '2.4+5', [150, 120]], ['camera', '2.4', [420, 440], false], ['plug', '2.4', [640, 60]], ['laptop', '2.4+5', [520, 420]]].map((s) => dev(s as DevSpec)) }),
  () => ({ id: 'elm-5', name: '5 Elm Row', area: 'Boston, MA', simulated: true,
    aps: [ap('router', [240, 280], 11), ap('mesh-1', [600, 100], 1), ap('mesh-2', [600, 380], 6)],
    devices: [['phone', '2.4+5', [100, 100]], ['laptop', '2.4+5', [650, 200]], ['tv', '2.4+5', [245, 150]], ['speaker', '2.4', [520, 420]]].map((s) => dev(s as DevSpec)) }),
]

// Dual-band devices stay on 5 GHz while it is decent and fall back to 2.4 GHz when it is not.
const STEER_DBM = -72

export function healthOf(site: Site): Health {
  const router = site.aps[0]
  const issues: Issue[] = []
  const add = (severity: Issue['severity'], key: string, text: string) => issues.push({ key: `${site.id}:${key}`, siteId: site.id, severity, text })
  if (!router?.on) add('offline', 'router', `${router?.name ?? 'router'} is offline, so the whole home has no internet`)
  site.aps.slice(1).forEach((a) => !a.on && add('problem', `ap:${a.name}`, `${a.name} is offline; its rooms rely on the other access points`))

  const devices: DeviceState[] = site.devices.map((d) => {
    if (!d.on) return { d, band: null, dbm: null, ap: null, state: 'not seen' }
    let pick: { b: ReturnType<typeof best>; band: Band } = { b: null, band: '2.4' }
    if (d.bands?.includes('5')) {
      const b5 = best(site.aps, d.x, d.y, '5')
      if (b5 && b5.dbm >= STEER_DBM) pick = { b: b5, band: '5' }
    }
    if (!pick.b) pick = { b: best(site.aps, d.x, d.y, '2.4'), band: '2.4' }
    const { b, band } = pick
    if (!b) return { d, band: null, dbm: null, ap: null, state: 'no internet' }
    const state = b.dbm < USABLE_DBM ? 'unusable' : b.dbm < GOOD_DBM ? 'weak' : 'good'
    return { d, band, dbm: b.dbm, ap: b.ap.name, state: router?.on ? state : 'no internet' }
  })
  devices.forEach(({ d, dbm, state }) => {
    if (state === 'not seen') add('warning', `seen:${d.name}`, `${d.name} has not been seen on the network`)
    if (state === 'unusable') add('problem', `sig:${d.name}`, `${d.name} has an unusable signal (${Math.round(dbm!)} dBm)`)
    if (state === 'weak') add('warning', `sig:${d.name}`, `${d.name} has a weak signal (${Math.round(dbm!)} dBm)`)
  })
  const status: Status = issues.some((i) => i.severity === 'offline') ? 'offline'
    : issues.some((i) => i.severity === 'problem') ? 'degraded'
    : issues.length ? 'warning' : 'ok'
  return {
    status,
    issues,
    devices,
    connected: devices.filter((x) => x.ap && x.state !== 'no internet').length,
    apsOn: site.aps.filter((a) => a.on).length,
  }
}

export const STATUS_LABEL: Record<Status, string> = { ok: 'Healthy', warning: 'Needs a look', degraded: 'Degraded', offline: 'Offline' }

export const useSites = defineStore('sites', () => {
  const sites = ref<Site[]>([])
  const activity = ref<Activity[]>([])
  const live = ref(false)
  let lab: Lab | null = null
  let loading: Promise<void> | null = null

  function load() {
    loading ??= (async () => {
      try {
        lab = await api.lab()
      } catch {
        lab = null
      }
      sites.value = [labSite(lab), ...SIMULATED.map((f) => f())]
    })()
    return loading
  }

  const byId = (id: string) => sites.value.find((s) => s.id === id) ?? null
  const health = computed(() => Object.fromEntries(sites.value.map((s) => [s.id, healthOf(s)])) as Record<string, Health>)
  const issues = computed(() => Object.values(health.value).flatMap((h) => h.issues))

  function resetSite(id: string) {
    const i = sites.value.findIndex((s) => s.id === id)
    if (i < 0) return
    sites.value[i] = id === 'lab' ? labSite(lab) : SIMULATED.find((f) => f().id === id)!()
  }

  // The activity feed: every problem that appears or clears, newest first.
  let seen: Map<string, Issue> | null = null
  watch(issues, (now) => {
    const next = new Map(now.map((i) => [i.key, i]))
    if (seen) {
      const at = Date.now()
      for (const [k, i] of next) if (!seen.has(k)) activity.value.unshift({ at, siteId: i.siteId, text: i.text, kind: 'open', severity: i.severity })
      for (const [k, i] of seen) if (!next.has(k)) activity.value.unshift({ at, siteId: i.siteId, text: i.text.replace(/ (is|has).*/, '') + ': back to normal', kind: 'clear', severity: i.severity })
      activity.value.splice(30)
    }
    seen = next
  })

  // Live simulation: every few seconds something happens in one simulated home, the way a real
  // fleet keeps changing. Off by default; nothing here touches the lab home.
  let timer: number | undefined
  function tick() {
    const pool = sites.value.filter((s) => s.simulated)
    const s = pool[Math.floor(Math.random() * pool.length)]
    if (!s) return
    const pick = <T,>(xs: T[]) => xs[Math.floor(Math.random() * xs.length)]
    // Half the time something broken gets fixed, so the fleet does not drift into all-red.
    const broken = [...s.aps, ...s.devices].filter((n) => !n.on)
    if (broken.length && Math.random() < 0.5) {
      pick(broken).on = true
      return
    }
    const r = Math.random()
    if (r < 0.08) s.aps[0].on = false
    else if (r < 0.33 && s.aps.length > 1) pick(s.aps.slice(1)).on = false
    else if (r < 0.55) pick(s.devices).on = false
    else {
      const d = pick(s.devices)
      d.x = 40 + Math.random() * 640
      d.y = 40 + Math.random() * 400
    }
  }
  watch(live, (on) => {
    clearInterval(timer)
    if (on) timer = window.setInterval(tick, 3000)
  })

  return { sites, activity, live, load, byId, health, issues, resetSite, tick }
})
