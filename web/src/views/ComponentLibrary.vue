<script setup lang="ts">
// The UI kit: every token and component the app is built from, with its states, on one page.
// Each example is the real component, so this page breaks if a component does, and the theme
// switch in the top bar shows every piece in light and dark.
import { onMounted, ref } from 'vue'
import BaseButton from '../components/ui/BaseButton.vue'
import SegmentedControl from '../components/ui/SegmentedControl.vue'
import StatusBadge from '../components/StatusBadge.vue'
import OutcomeBadge from '../components/OutcomeBadge.vue'
import CountsBar from '../components/CountsBar.vue'
import InfoTip from '../components/InfoTip.vue'

const SECTIONS = [
  { id: 'colours', label: 'Colours' }, { id: 'type', label: 'Type' }, { id: 'buttons', label: 'Buttons' },
  { id: 'controls', label: 'Controls' }, { id: 'forms', label: 'Forms' }, { id: 'status', label: 'Status' }, { id: 'data', label: 'Data' },
]

const jump = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })

// Swatches read each token's live value, so the hex codes change when the theme does.
const TOKENS = [
  { group: 'Surfaces', names: ['--bg', '--bg-soft', '--card', '--line', '--hover'] },
  { group: 'Text', names: ['--ink', '--muted'] },
  { group: 'Brand', names: ['--accent', '--accent-soft', '--nav'] },
  { group: 'Status', names: ['--pass', '--pass-bg', '--fail', '--fail-bg', '--skip', '--skip-bg'] },
  { group: 'Chart series', names: ['--series-1', '--series-2', '--series-3', '--series-4'] },
]
const values = ref<Record<string, string>>({})
function readTokens() {
  const css = getComputedStyle(document.documentElement)
  values.value = Object.fromEntries(TOKENS.flatMap((g) => g.names).map((n) => [n, css.getPropertyValue(n).trim()]))
}
onMounted(() => {
  readTokens()
  // Re-read when the theme switch changes data-theme, or the system theme changes.
  new MutationObserver(readTokens).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  window.matchMedia?.('(prefers-color-scheme: dark)').addEventListener?.('change', readTokens)
})
const copied = ref('')
async function copy(name: string) {
  try { await navigator.clipboard.writeText(`var(${name})`); copied.value = name } catch { copied.value = '' }
  window.setTimeout(() => (copied.value = ''), 1500)
}

// Live examples
const band = ref<'2.4' | '5' | '6'>('5')
const view = ref<'day' | 'week' | 'month'>('week')
const ssid = ref('')
const ssidError = ref('')
const checkSsid = () => (ssidError.value = !ssid.value.trim() ? 'Enter a network name.' : ssid.value.length > 32 ? 'Network names can be up to 32 characters.' : '')
const security = ref('wpa3')
const notify = ref(true)
const loading = ref(false)
function fakeSave() { loading.value = true; window.setTimeout(() => (loading.value = false), 1200) }
</script>

<template>
  <div class="head">
    <h1>UI kit</h1>
    <p class="muted">The tokens and components this app is built from. Switch the theme in the top bar to see every piece in dark mode.</p>
  </div>
  <nav class="toc" aria-label="Sections">
    <a v-for="s in SECTIONS" :key="s.id" :href="`#${s.id}`" @click.prevent="jump(s.id)">{{ s.label }}</a>
  </nav>

  <section id="colours" class="card">
    <div class="cardhead"><h2>Colours</h2><span class="muted small">Click a swatch to copy its token</span></div>
    <div v-for="g in TOKENS" :key="g.group" class="tokgroup">
      <h3>{{ g.group }}</h3>
      <div class="swatches">
        <button v-for="n in g.names" :key="n" type="button" class="swatch" :aria-label="`Copy ${n}`" @click="copy(n)">
          <i :style="{ background: `var(${n})` }" />
          <code>{{ copied === n ? 'Copied' : n }}</code>
          <span class="muted small">{{ values[n] }}</span>
        </button>
      </div>
    </div>
  </section>

  <section id="type" class="card">
    <h2>Type</h2>
    <div class="typerow"><span class="muted small">H1 · 24 / 700</span><span class="t-h1">Lab overview</span></div>
    <div class="typerow"><span class="muted small">H2 · 15 / 650</span><span class="t-h2">Access points</span></div>
    <div class="typerow"><span class="muted small">Body · 14 / 400</span><span>Every room has a good signal and no channels clash.</span></div>
    <div class="typerow"><span class="muted small">Label · 12 / 600 caps</span><span class="t-label">Pass rate, latest run</span></div>
    <div class="typerow"><span class="muted small">Number · 28 / 700 tabular</span><span class="t-num">97.5%</span></div>
    <div class="typerow"><span class="muted small">Mono · JetBrains Mono</span><code>wpa_cli -i wlan1 status</code></div>
  </section>

  <section id="buttons" class="card">
    <h2>Buttons</h2>
    <div class="row">
      <BaseButton>Start a run</BaseButton>
      <BaseButton variant="secondary">Undo</BaseButton>
      <BaseButton variant="ghost">View all runs</BaseButton>
      <BaseButton variant="danger">Remove AP 2</BaseButton>
      <BaseButton disabled>Disabled</BaseButton>
    </div>
    <div class="row">
      <BaseButton size="sm">Small</BaseButton>
      <BaseButton size="sm" variant="secondary">Small secondary</BaseButton>
      <BaseButton :disabled="loading" @click="fakeSave()"><span v-if="loading" class="spin" aria-hidden="true" />{{ loading ? 'Saving…' : 'Save (shows loading)' }}</BaseButton>
    </div>
    <p class="note">One component, <code>&lt;BaseButton variant size&gt;</code>. Primary is for the one main action on a screen; danger is only for removing things.</p>
  </section>

  <section id="controls" class="card">
    <h2>Controls</h2>
    <div class="row">
      <SegmentedControl v-model="band" label="Band" :options="[{ value: '2.4', label: '2.4 GHz' }, { value: '5', label: '5 GHz' }, { value: '6', label: '6 GHz', disabled: true }]" />
      <SegmentedControl v-model="view" label="Period" :options="[{ value: 'day', label: 'Day' }, { value: 'week', label: 'Week' }, { value: 'month', label: 'Month' }]" />
      <span class="muted small">Chosen: {{ band }} GHz, {{ view }}</span>
    </div>
    <div class="row">
      <span class="chip">Read-only demo</span>
      <span class="chip warn">Sample data</span>
      <span class="chip live"><i class="dot" />Running</span>
      <span class="modeltag">Model, not a measurement</span>
      <span>Help text <InfoTip text="Explanations live behind this i so pages stay short. It opens on hover and on keyboard focus." /></span>
    </div>
    <div class="row pager">
      <button type="button" class="pg" disabled>‹ Prev</button>
      <button type="button" class="pg on" aria-current="page">1</button>
      <button type="button" class="pg">2</button>
      <span class="muted">…</span>
      <button type="button" class="pg">12</button>
      <button type="button" class="pg">Next ›</button>
    </div>
    <p class="note">The segmented control is a radio group: arrow keys change the choice and only the chosen option is in the Tab order.</p>
  </section>

  <section id="forms" class="card">
    <h2>Forms</h2>
    <div class="formgrid">
      <label class="field">
        <span>Network name (SSID)</span>
        <input v-model="ssid" placeholder="Home-5G" :aria-invalid="!!ssidError" aria-describedby="ssid-help" @blur="checkSsid" />
        <small id="ssid-help" :class="ssidError ? 'fielderr' : 'muted'">{{ ssidError || 'Up to 32 characters. Leave the field to check it.' }}</small>
      </label>
      <label class="field">
        <span>Security</span>
        <select v-model="security">
          <option value="wpa3">WPA3-Personal (SAE)</option>
          <option value="wpa2">WPA2-Personal</option>
          <option value="ent">WPA2-Enterprise (802.1X)</option>
        </select>
      </label>
      <fieldset class="field">
        <legend>Access point model</legend>
        <label v-for="m in [['compact', 'Compact', '2.4 GHz only'], ['standard', 'Standard', 'Both bands']]" :key="m[0]" class="choice">
          <input type="radio" name="kit-model" :value="m[0]" :checked="m[0] === 'standard'" />
          <b>{{ m[1] }}</b><span class="muted small">{{ m[2] }}</span>
        </label>
      </fieldset>
      <label class="check"><input v-model="notify" type="checkbox" /> Email me when a run fails</label>
    </div>
    <p class="note">Errors show when a field is left, sit under the field, and are linked to it with <code>aria-describedby</code>; the field gets a red border and <code>aria-invalid</code>.</p>
  </section>

  <section id="status" class="card">
    <h2>Status</h2>
    <div class="row">
      <StatusBadge status="ok" /><StatusBadge status="warning" /><StatusBadge status="degraded" /><StatusBadge status="offline" />
    </div>
    <div class="row">
      <OutcomeBadge outcome="passed" /><OutcomeBadge outcome="failed" /><OutcomeBadge outcome="error" /><OutcomeBadge outcome="skipped" />
    </div>
    <div class="bars">
      <div><span class="muted small">All passed</span><CountsBar :counts="{ passed: 40, failed: 0, error: 0, skipped: 0 }" /></div>
      <div><span class="muted small">Some failed</span><CountsBar :counts="{ passed: 34, failed: 4, error: 1, skipped: 1 }" /></div>
      <div><span class="muted small">Mostly skipped</span><CountsBar :counts="{ passed: 3, failed: 0, error: 0, skipped: 12 }" /></div>
    </div>
    <div class="row alerts">
      <p class="alert ok">No problems found.</p>
      <p class="alert warn"><b>!</b> Bedroom 2: only 8% has a good 5 GHz signal.</p>
      <p class="alert bad">Could not load runs: the API did not answer.</p>
    </div>
    <p class="note">Status never relies on colour alone: every badge has a word, and site badges also have a symbol.</p>
  </section>

  <section id="data" class="card">
    <h2>Data</h2>
    <div class="tiles">
      <div class="tile"><span>Runs</span><b>128</b></div>
      <div class="tile"><span>Pass rate</span><b class="good">97%</b></div>
      <div class="tile"><span>Changed result</span><b class="warn">3</b></div>
      <div class="tile"><span>Join time, median</span><b>1.8 s</b></div>
    </div>
    <table class="kit">
      <thead><tr><th>Test</th><th>Result</th><th>Time</th></tr></thead>
      <tbody>
        <tr><td>WPA3 client joins with SAE</td><td><OutcomeBadge outcome="passed" /></td><td class="num">2.1 s</td></tr>
        <tr><td>Wrong password is refused</td><td><OutcomeBadge outcome="passed" /></td><td class="num">4.0 s</td></tr>
        <tr><td>Roams to the stronger AP</td><td><OutcomeBadge outcome="failed" /></td><td class="num">12.6 s</td></tr>
      </tbody>
    </table>
    <div class="row"><div class="skeleton" style="width: 40%" /><div class="skeleton" style="width: 25%" /></div>
    <p class="note">Loading placeholders keep the layout steady while data arrives.</p>
  </section>
</template>

<style scoped>
.head p { margin: 0 0 12px; }
.toc { position: sticky; top: 61px; z-index: 2; display: flex; gap: 4px; flex-wrap: wrap; padding: 8px 0; margin-bottom: 8px; background: var(--bg); }
.toc a { padding: 4px 12px; border-radius: 999px; font-size: 13px; font-weight: 600; color: var(--muted); border: 1px solid var(--line); background: var(--card); text-decoration: none; }
.toc a:hover { color: var(--accent); border-color: var(--accent); background: var(--hover); }
section { scroll-margin-top: 120px; }
h3 { font-size: 12px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; margin: 14px 0 8px; }
.swatches { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
.swatch { display: grid; gap: 2px; text-align: left; padding: 8px; background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); color: var(--ink); font-weight: 400; min-height: 0; }
.swatch:hover { border-color: var(--accent); background: var(--hover); }
.swatch i { display: block; height: 44px; border-radius: var(--radius-sm); border: 1px solid var(--line); margin-bottom: 6px; }
.swatch code { font-size: 12px; }
.typerow { display: grid; grid-template-columns: 190px 1fr; align-items: baseline; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--line); }
.t-h1 { font-size: 24px; font-weight: 700; letter-spacing: -0.02em; }
.t-h2 { font-size: 15px; font-weight: 650; }
.t-label { font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); }
.t-num { font-size: 28px; font-weight: 700; font-variant-numeric: tabular-nums; }
code { font-family: var(--mono); }
.row { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 12px; }
.note { margin: 4px 0 0; font-size: 13px; color: var(--muted); border-left: 3px solid var(--line); padding-left: 10px; }
.spin { width: 12px; height: 12px; border: 2px solid currentColor; border-right-color: transparent; border-radius: 50%; animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spin { animation-duration: 3s; } }
.chip { font-size: 12px; font-weight: 600; border-radius: 999px; padding: 4px 12px; background: var(--bg); border: 1px solid var(--line); color: var(--muted); display: inline-flex; align-items: center; gap: 6px; }
.chip.warn { color: var(--skip); background: var(--skip-bg); border-color: transparent; }
.chip.live { color: var(--ink); border-color: var(--accent); }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent); }
.modeltag { font-size: 12px; font-weight: 600; border: 1px solid var(--skip); background: var(--skip-bg); border-radius: var(--radius-sm); padding: 1px 8px; }
.pg { min-height: 32px; padding: 4px 10px; font-size: 13px; background: var(--card); color: var(--ink); border: 1px solid var(--line); }
.pg:hover:not(:disabled) { background: var(--hover); color: var(--accent); border-color: var(--accent); }
.pg.on { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
.pg:disabled { opacity: .45; }
.formgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; margin-bottom: 12px; align-items: start; }
.field { display: grid; gap: 6px; border: 0; padding: 0; margin: 0; min-width: 0; }
.field > span, .field legend { font-size: 12px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; padding: 0; margin-bottom: 6px; }
.field input { padding: 8px 10px; border-radius: var(--radius); border: 1px solid var(--line); background: var(--card); color: var(--ink); min-height: 38px; }
.field input[aria-invalid='true'] { border-color: var(--fail); box-shadow: 0 0 0 1px var(--fail) inset; }
.fielderr { color: var(--fail); font-weight: 600; }
.choice { display: grid; grid-template-columns: auto 1fr; column-gap: 8px; align-items: center; padding: 8px 10px; border: 1px solid var(--line); border-radius: var(--radius); margin-bottom: 6px; cursor: pointer; }
.choice:hover { background: var(--hover); }
.choice:has(input:checked) { border-color: var(--accent); background: var(--accent-soft); }
.choice input { grid-row: span 2; accent-color: var(--accent); }
.check { display: flex; gap: 8px; align-items: center; align-self: center; }
.check input { width: 16px; height: 16px; accent-color: var(--accent); }
.bars { display: grid; gap: 10px; max-width: 420px; margin-bottom: 14px; }
.bars > div { display: grid; gap: 4px; }
.alert { margin: 0; padding: 10px 12px; border-radius: var(--radius); font-size: 13px; flex: 1 1 220px; }
.alert.ok { background: var(--pass-bg); color: var(--pass); font-weight: 600; }
.alert.warn { background: var(--skip-bg); }
.alert.warn b { display: inline-grid; place-items: center; width: 18px; height: 18px; border-radius: 50%; background: var(--skip); color: var(--card); margin-right: 6px; font-size: 12px; }
.alert.bad { background: var(--fail-bg); color: var(--fail); }
.tile b.good { color: var(--pass); } .tile b.warn { color: var(--skip); }
.kit { width: 100%; border-collapse: collapse; margin-bottom: 14px; font-size: 14px; }
.kit th { text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); padding: 8px 12px; background: var(--bg); border-bottom: 1px solid var(--line); }
.kit td { padding: 10px 12px; border-bottom: 1px solid var(--line); }
.skeleton { height: 14px; border-radius: var(--radius-sm); background: linear-gradient(90deg, var(--line), var(--bg-soft), var(--line)); background-size: 200% 100%; animation: shimmer 1.4s ease-in-out infinite; }
@keyframes shimmer { to { background-position: -200% 0; } }
@media (prefers-reduced-motion: reduce) { .skeleton { animation: none; } }
@media (max-width: 640px) { .typerow { grid-template-columns: 1fr; gap: 2px; } }
</style>
