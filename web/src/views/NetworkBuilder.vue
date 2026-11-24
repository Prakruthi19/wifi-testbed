<script setup lang="ts">
// The network builder: pick a home, place up to 4 access points, check the plan, then share it.
// Four steps, one plan (stores/builder.ts), and the same signal model as the coverage planner.
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import InfoTip from '../components/InfoTip.vue'
import { useBuilder } from '../stores/builder'
import { BAND_MODEL, H, LEVELS, W, levelOf, type Band } from '../rfmodel'
import {
  CHANNELS, HOMES, MAX_APS, MODELS, NAME_MAX, bandsOf, bestAt, channelOf, decodePlan, encodePlan, fieldErrors,
  homeOf, planValid, roomCoverage, warnings, type BandChoice, type ModelId, type PlanAp,
} from '../builder'

const b = useBuilder()
const route = useRoute()
const router = useRouter()

// A shared link (#/builder?plan=...) opens that plan on the Check step.
onMounted(() => {
  const text = route.query.plan
  if (typeof text !== 'string') return
  const p = decodePlan(text)
  if (p) { b.load(p); b.step = 3 } else linkError.value = true
  router.replace({ query: {} })
})
const linkError = ref(false)

const STEPS = ['Home', 'Access points', 'Check', 'Review']
const home = computed(() => homeOf(b.plan.home))
const valid = computed(() => planValid(b.plan))
const warns = computed(() => warnings(b.plan))
const showErrors = ref(false)
const errs = (ap: PlanAp) => (showErrors.value ? fieldErrors(b.plan, ap) : {})
const COLORS = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)']
const colorOf = (ap: PlanAp) => COLORS[b.plan.aps.indexOf(ap) % COLORS.length]

// Steps 3 and 4 need a valid plan. Trying to move on shows every error and puts focus on the first.
async function goTo(n: number) {
  if (n > 2 && !valid.value) {
    showErrors.value = true
    b.step = 2
    if (!b.plan.aps.length) return
    const bad = b.plan.aps.find((a) => Object.keys(fieldErrors(b.plan, a)).length)
    if (bad) { b.selected = bad.id; await nextTick(); document.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus() }
    return
  }
  b.step = n
}
const stepState = (n: number) => (n === b.step ? 'current' : n < b.step ? 'done' : 'todo')

// -- the plan drawing ------------------------------------------------------------------------
const svg = ref<SVGSVGElement | null>(null)
const dragging = ref<string | null>(null)
function toPlan(e: PointerEvent) {
  const m = svg.value?.getScreenCTM()
  if (!m) return null
  const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(m.inverse())
  const r = home.value.bounds
  return { x: Math.min(r.x1 - 10, Math.max(r.x0 + 10, p.x)), y: Math.min(r.y1 - 10, Math.max(r.y0 + 10, p.y)) }
}
function grab(ap: PlanAp, e: PointerEvent) {
  b.selected = ap.id
  if (b.step !== 2) b.step = 2
  b.beginDrag()
  dragging.value = ap.id
  ;(e.currentTarget as Element).setPointerCapture?.(e.pointerId)
}
function drag(e: PointerEvent) {
  if (!dragging.value) return
  const p = toPlan(e)
  if (p) b.moveLive(dragging.value, p.x, p.y)
}
// Arrow keys move the focused AP (Shift for bigger steps); Delete removes it.
function key(ap: PlanAp, e: KeyboardEvent) {
  const step = e.shiftKey ? 40 : 10
  const d: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }
  if (d[e.key]) {
    e.preventDefault()
    const r = home.value.bounds
    b.updateAp(ap.id, { x: Math.min(r.x1 - 10, Math.max(r.x0 + 10, ap.x + d[e.key][0])), y: Math.min(r.y1 - 10, Math.max(r.y0 + 10, ap.y + d[e.key][1])) })
  } else if (e.key === 'Delete' || e.key === 'Backspace') {
    e.preventDefault()
    b.removeAp(ap.id)
  }
}

// Signal colours under the plan, for one band at a time.
const band = ref<Band>('5')
const hasBand = (x: Band) => b.plan.aps.some((a) => bandsOf(a).includes(x))
watch(() => hasBand('5'), (yes) => { band.value = yes ? '5' : '2.4' }, { immediate: true })
const showHeat = computed(() => b.step >= 2 && b.plan.aps.length > 0)
const canvas = ref<HTMLCanvasElement | null>(null)
const CELL = 8
function paint() {
  const el = canvas.value
  if (!el) return
  const cols = W / CELL, rows = H / CELL
  el.width = cols
  el.height = rows
  const ctx = el.getContext('2d')!
  const img = ctx.createImageData(cols, rows)
  const r = home.value.bounds
  for (let j = 0; j < rows; j++)
    for (let i = 0; i < cols; i++) {
      const x = i * CELL + CELL / 2, y = j * CELL + CELL / 2
      if (x < r.x0 || x > r.x1 || y < r.y0 || y > r.y1) continue
      const best = bestAt(b.plan, x, y, band.value)
      const c = best ? LEVELS[levelOf(best.dbm)].color : null
      if (!c) continue
      const k = 4 * (j * cols + i)
      img.data[k] = c[0]; img.data[k + 1] = c[1]; img.data[k + 2] = c[2]; img.data[k + 3] = 90
    }
  ctx.putImageData(img, 0, 0)
}
// Repaint at most once per frame while dragging.
let frame = 0
watch([() => JSON.stringify(b.plan), band, canvas], () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(paint) })

// -- step 2: the AP form -----------------------------------------------------------------------
const bandChoices: { v: BandChoice; label: string }[] = [{ v: 'both', label: 'Both' }, { v: '2.4', label: '2.4 GHz' }, { v: '5', label: '5 GHz' }]
const modelHas5 = (m: ModelId) => (MODELS[m].bands as readonly Band[]).includes('5')
function setModel(ap: PlanAp, m: ModelId) {
  // A 2.4 GHz-only model cannot keep a 5 GHz setting: switch it to 2.4 GHz rather than leave an error.
  b.updateAp(ap.id, modelHas5(m) ? { model: m } : { model: m, band: '2.4' })
}
function setChannel(ap: PlanAp, x: Band, v: string) {
  b.updateAp(ap.id, { ch: { ...ap.ch, [x]: v === 'auto' ? 'auto' : Number(v) } })
}
const nameDraft = ref<Record<string, string>>({})
// The name is saved when the field is left (one undo step), not on every key press.
function saveName(ap: PlanAp) {
  const v = nameDraft.value[ap.id]
  if (v !== undefined && v !== ap.name) b.updateAp(ap.id, { name: v })
  delete nameDraft.value[ap.id]
}

// -- step 3 and 4 ---------------------------------------------------------------------------
const rooms = computed(() => roomCoverage(b.plan, band.value))
const overall = (x: Band) => {
  const r = roomCoverage(b.plan, x)
  return r.length ? Math.round((100 * r.reduce((s, c) => s + c.good, 0)) / r.length) : 0
}
const shareUrl = computed(() => `${location.origin}${location.pathname}#/builder?plan=${encodePlan(b.plan)}`)
const copied = ref(false)
async function copyLink() {
  try { await navigator.clipboard.writeText(shareUrl.value); copied.value = true } catch { copied.value = false; (document.getElementById('share') as HTMLInputElement)?.select() }
  window.setTimeout(() => (copied.value = false), 2000)
}

// Ctrl+Z / Ctrl+Shift+Z (or Ctrl+Y) undo and redo, except while typing in a field.
function onKey(e: KeyboardEvent) {
  if (!(e.ctrlKey || e.metaKey) || (e.target as HTMLElement).closest('input, select, textarea')) return
  const k = e.key.toLowerCase()
  if (k === 'z' && !e.shiftKey) { e.preventDefault(); b.undo() }
  else if ((k === 'z' && e.shiftKey) || k === 'y') { e.preventDefault(); b.redo() }
}
onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => { window.removeEventListener('keydown', onKey); cancelAnimationFrame(frame) })
</script>

<template>
  <div class="head">
    <h1>Network builder <span class="modeltag" title="Signal is estimated with a textbook indoor path-loss model; access point models are made up.">Model, not a measurement</span></h1>
    <div class="tools">
      <button type="button" class="tool" :disabled="!b.canUndo" title="Undo (Ctrl+Z)" @click="b.undo()">Undo</button>
      <button type="button" class="tool" :disabled="!b.canRedo" title="Redo (Ctrl+Shift+Z)" @click="b.redo()">Redo</button>
    </div>
  </div>
  <p v-if="linkError" class="error" role="alert">That plan link is damaged, so a new plan was started.</p>

  <ol class="stepper" aria-label="Steps">
    <li v-for="(s, i) in STEPS" :key="s" :class="stepState(i + 1)">
      <button type="button" :aria-current="b.step === i + 1 ? 'step' : undefined" @click="goTo(i + 1)">
        <span class="num" aria-hidden="true">{{ stepState(i + 1) === 'done' ? '✓' : i + 1 }}</span>{{ s }}
      </button>
    </li>
  </ol>

  <div class="layout">
    <section class="card planbox" aria-label="Floor plan">
      <div class="planhead">
        <b>{{ home.name }}</b><span class="muted small">{{ home.size }}</span>
        <div v-if="showHeat" class="segs" role="group" aria-label="Signal band">
          <button v-for="x in (['2.4', '5'] as Band[])" :key="x" type="button" class="seg" :aria-pressed="band === x" :disabled="!hasBand(x)" @click="band = x">{{ BAND_MODEL[x].label }}</button>
        </div>
      </div>
      <div class="stage">
        <svg :viewBox="`0 0 ${W} ${H}`" aria-hidden="true" class="floor">
          <defs>
            <pattern id="nb-wood" width="60" height="14" patternUnits="userSpaceOnUse"><rect width="60" height="14" fill="var(--floor-wood)" /><path d="M0,13.5 H60 M38,0 V14" stroke="var(--floor-wood-line)" /></pattern>
            <pattern id="nb-tile" width="20" height="20" patternUnits="userSpaceOnUse"><rect width="20" height="20" fill="var(--floor-tile)" /><path d="M0,19.5 H20 M19.5,0 V20" stroke="var(--floor-tile-line)" /></pattern>
          </defs>
          <rect :width="W" :height="H" class="yard" />
          <rect v-for="r in home.rooms" :key="r.name" :x="r.x" :y="r.y" :width="r.w" :height="r.h" :fill="r.floor === 'carpet' ? 'var(--floor-carpet)' : `url(#nb-${r.floor})`" />
        </svg>
        <canvas v-show="showHeat" ref="canvas" aria-hidden="true" />
        <svg ref="svg" :viewBox="`0 0 ${W} ${H}`" role="group" aria-label="Access points on the plan. Tab to one and use the arrow keys to move it." @pointermove="drag" @pointerup="dragging = null" @pointercancel="dragging = null">
          <line v-for="(w, i) in home.walls" :key="i" :x1="w[0]" :y1="w[1]" :x2="w[2]" :y2="w[3]" class="wall" />
          <text v-for="r in home.rooms" :key="r.name" :x="r.lx" :y="r.ly" class="roomname">{{ r.name }}</text>
          <g
            v-for="ap in b.plan.aps" :key="ap.id" class="ap" :class="{ sel: b.selected === ap.id, dragging: dragging === ap.id }"
            :transform="`translate(${ap.x} ${ap.y})`" :style="{ color: colorOf(ap) }"
            tabindex="0" role="button" :aria-label="`${ap.name}, ${MODELS[ap.model].name}. Arrow keys move it, Delete removes it.`" :aria-pressed="b.selected === ap.id"
            @pointerdown.prevent="grab(ap, $event)" @keydown="key(ap, $event)" @focus="b.selected = ap.id"
          >
            <circle r="26" class="halo" />
            <circle r="13" class="dot" />
            <path d="M-6,-1 a8,8 0 0 1 12,0 M-3.5,2.5 a4,4 0 0 1 7,0" class="waves" />
            <text y="-20" class="aplabel">{{ ap.name || '(no name)' }}</text>
          </g>
        </svg>
        <p v-if="b.step === 2 && !b.plan.aps.length" class="hint">Add an access point, then drag it into place.</p>
      </div>
      <ul v-if="showHeat" class="legend" aria-label="Signal levels">
        <li v-for="l in LEVELS.slice(0, 4)" :key="l.label"><i :style="{ background: `rgb(${l.color!.join(',')})` }" />{{ l.label.split(' (')[0].split(':')[0] }}</li>
      </ul>
    </section>

    <aside class="card panel">
      <!-- Step 1: choose a home -->
      <template v-if="b.step === 1">
        <h2>Choose a home</h2>
        <div class="homes" role="radiogroup" aria-label="Home">
          <button
            v-for="h in HOMES" :key="h.id" type="button" role="radio" class="homecard" :aria-checked="b.plan.home === h.id"
            @click="b.setHome(h.id)"
          >
            <svg :viewBox="`0 0 ${W} ${H}`" aria-hidden="true"><line v-for="(w, i) in h.walls" :key="i" :x1="w[0]" :y1="w[1]" :x2="w[2]" :y2="w[3]" /></svg>
            <span><b>{{ h.name }}</b><span class="muted small">{{ h.size }}</span></span>
          </button>
        </div>
      </template>

      <!-- Step 2: access points -->
      <template v-else-if="b.step === 2">
        <div class="cardhead">
          <h2>Access points <span class="muted">{{ b.plan.aps.length }}/{{ MAX_APS }}</span></h2>
          <InfoTip text="Drag an access point on the plan, or select it and use the arrow keys (Shift moves further)." />
        </div>
        <p v-if="showErrors && !b.plan.aps.length" class="fielderr" role="alert">Add at least one access point.</p>
        <div v-for="ap in b.plan.aps" :key="ap.id" class="apcard" :class="{ open: b.selected === ap.id }" :style="{ '--ap': colorOf(ap) }">
          <button type="button" class="aphead" :aria-expanded="b.selected === ap.id" @click="b.selected = b.selected === ap.id ? null : ap.id">
            <i class="swatch" aria-hidden="true" /><b>{{ ap.name || '(no name)' }}</b>
            <span class="muted small">{{ MODELS[ap.model].name }} · {{ bandsOf(ap).map((x) => BAND_MODEL[x].label).join(' + ') || 'no band' }}</span>
            <span v-if="Object.keys(errs(ap)).length" class="badge bad">Fix</span>
          </button>
          <div v-if="b.selected === ap.id" class="form">
            <label class="field">
              <span>Name</span>
              <input
                :value="nameDraft[ap.id] ?? ap.name" :maxlength="NAME_MAX + 10" :aria-invalid="!!errs(ap).name" :aria-describedby="errs(ap).name ? `${ap.id}-name-err` : undefined"
                @input="nameDraft[ap.id] = ($event.target as HTMLInputElement).value" @blur="saveName(ap)" @keydown.enter="saveName(ap)"
              />
              <small v-if="errs(ap).name" :id="`${ap.id}-name-err`" class="fielderr">{{ errs(ap).name }}</small>
            </label>
            <fieldset class="field">
              <legend>Model</legend>
              <div class="choices">
                <label v-for="(m, id) in MODELS" :key="id" class="choice" :class="{ on: ap.model === id }">
                  <input type="radio" :name="`${ap.id}-model`" :checked="ap.model === id" @change="setModel(ap, id)" />
                  <b>{{ m.name }}</b><span class="muted small">{{ m.blurb }}</span>
                </label>
              </div>
            </fieldset>
            <fieldset class="field">
              <legend>Band</legend>
              <div class="segs" role="radiogroup" :aria-describedby="errs(ap).band ? `${ap.id}-band-err` : undefined">
                <button
                  v-for="c in bandChoices" :key="c.v" type="button" role="radio" class="seg" :aria-checked="ap.band === c.v"
                  :disabled="c.v !== '2.4' && !modelHas5(ap.model)" :title="c.v !== '2.4' && !modelHas5(ap.model) ? `${MODELS[ap.model].name} has no 5 GHz radio` : undefined"
                  @click="b.updateAp(ap.id, { band: c.v })"
                >{{ c.label }}</button>
              </div>
              <small v-if="errs(ap).band" :id="`${ap.id}-band-err`" class="fielderr">{{ errs(ap).band }}</small>
            </fieldset>
            <div class="chans">
              <label v-for="x in bandsOf(ap)" :key="x" class="field">
                <span>{{ BAND_MODEL[x].label }} channel</span>
                <select :value="String(ap.ch[x])" @change="setChannel(ap, x, ($event.target as HTMLSelectElement).value)">
                  <option value="auto">Auto ({{ channelOf(b.plan, ap, x) }})</option>
                  <option v-for="c in CHANNELS[x]" :key="c" :value="String(c)">{{ c }}</option>
                </select>
              </label>
            </div>
            <button type="button" class="remove" @click="b.removeAp(ap.id)">Remove {{ ap.name || 'this access point' }}</button>
          </div>
        </div>
        <button type="button" class="add" :disabled="b.plan.aps.length >= MAX_APS" @click="b.addAp()">
          + Add access point<span v-if="b.plan.aps.length >= MAX_APS" class="small"> (up to {{ MAX_APS }})</span>
        </button>
      </template>

      <!-- Step 3: check -->
      <template v-else-if="b.step === 3">
        <h2>Check the plan</h2>
        <ul v-if="warns.length" class="warns">
          <li v-for="(w, i) in warns" :key="i" :class="w.kind"><span class="icon" aria-hidden="true">!</span>{{ w.text }}</li>
        </ul>
        <p v-else class="allgood">No problems found: every room has a good signal and no channels clash.</p>
        <table class="rooms">
          <caption class="muted small">Good signal (video calls work) on {{ BAND_MODEL[band].label }}</caption>
          <thead><tr><th>Room</th><th>Good</th><th>Mostly from</th></tr></thead>
          <tbody>
            <tr v-for="r in rooms" :key="r.room">
              <td>{{ r.room }}</td>
              <td><span class="meter"><i :style="{ width: Math.round(r.good * 100) + '%' }" :class="{ low: r.good < 0.8 }" /></span><span class="pct">{{ Math.round(r.good * 100) }}%</span></td>
              <td>{{ r.by ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
      </template>

      <!-- Step 4: review and share -->
      <template v-else>
        <h2>Review and share</h2>
        <div class="kpis">
          <div><span>Home</span><b>{{ home.name }}</b></div>
          <div><span>Access points</span><b>{{ b.plan.aps.length }}</b></div>
          <div v-for="x in (['2.4', '5'] as Band[]).filter(hasBand)" :key="x"><span>Good on {{ BAND_MODEL[x].label }}</span><b>{{ overall(x) }}%</b></div>
        </div>
        <table class="rooms">
          <thead><tr><th>Name</th><th>Model</th><th>Channels</th></tr></thead>
          <tbody>
            <tr v-for="ap in b.plan.aps" :key="ap.id">
              <td><i class="swatch" :style="{ '--ap': colorOf(ap) }" aria-hidden="true" />{{ ap.name }}</td>
              <td>{{ MODELS[ap.model].name }}</td>
              <td>{{ bandsOf(ap).map((x) => `${x}: ${channelOf(b.plan, ap, x)}`).join(', ') }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="warns.length" class="muted small">{{ warns.length }} warning{{ warns.length > 1 ? 's' : '' }} on the Check step.</p>
        <label class="field">
          <span>Share link</span>
          <div class="share"><input id="share" :value="shareUrl" readonly @focus="($event.target as HTMLInputElement).select()" /><button type="button" @click="copyLink()">{{ copied ? 'Copied' : 'Copy' }}</button></div>
        </label>
        <p class="sr" aria-live="polite">{{ copied ? 'Link copied' : '' }}</p>
        <button type="button" class="remove" @click="b.reset()">Start a new plan</button>
      </template>
    </aside>
  </div>

  <div class="footer">
    <button type="button" class="tool" :disabled="b.step === 1" @click="goTo(b.step - 1)">Back</button>
    <button v-if="b.step < 4" type="button" @click="goTo(b.step + 1)">Next: {{ STEPS[b.step] }}</button>
  </div>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.modeltag { font-size: 12px; font-weight: 600; border: 1px solid var(--skip); background: var(--skip-bg); border-radius: var(--radius-sm); padding: 1px 8px; cursor: help; letter-spacing: 0; }
.tools { display: flex; gap: 6px; }
.tool { background: var(--card); color: var(--ink); border: 1px solid var(--line); min-height: 34px; padding: 4px 12px; font-size: 13px; }
.tool:hover:not(:disabled) { background: var(--hover); color: var(--accent); border-color: var(--accent); }
.error { color: var(--fail); background: var(--fail-bg); padding: 8px 12px; border-radius: var(--radius); }

.stepper { display: flex; gap: 8px; list-style: none; padding: 0; margin: 12px 0 16px; counter-reset: s; }
.stepper li { flex: 1; position: relative; }
.stepper button { width: 100%; display: flex; align-items: center; gap: 10px; background: var(--card); color: var(--muted); border: 1px solid var(--line); min-height: 44px; padding: 6px 12px; font-size: 13px; text-align: left; }
.stepper button:hover { background: var(--hover); }
.num { display: inline-grid; place-items: center; width: 24px; height: 24px; flex: none; border-radius: 50%; border: 1px solid var(--line); font-size: 12px; background: var(--bg); }
.stepper .current button { color: var(--ink); border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent) inset; }
.stepper .current .num { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
.stepper .done button { color: var(--ink); }
.stepper .done .num { background: var(--pass-bg); color: var(--pass); border-color: var(--pass); }

.layout { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(320px, 1fr); gap: 16px; align-items: start; }
.planbox { padding: 14px; }
.planhead { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
.planhead .segs { margin-left: auto; }
.segs { display: inline-flex; gap: 2px; background: var(--bg); border: 1px solid var(--line); border-radius: var(--radius); padding: 2px; }
.seg { background: none; color: var(--muted); border: 0; min-height: 30px; padding: 4px 12px; font-size: 13px; font-weight: 600; border-radius: var(--radius-sm); }
.seg[aria-pressed='true'], .seg[aria-checked='true'] { background: var(--card); color: var(--ink); box-shadow: 0 1px 2px rgb(15 23 42 / 0.15); }
.seg:disabled { opacity: .4; }
.stage { position: relative; width: 100%; aspect-ratio: 720 / 480; border-radius: var(--radius); overflow: hidden; }
.stage canvas, .stage svg { position: absolute; inset: 0; width: 100%; height: 100%; }
.stage svg { touch-action: none; }
.yard { fill: var(--bg); }
.wall { stroke: var(--ink); stroke-width: 6; stroke-linecap: square; opacity: .8; }
.roomname { font-size: 13px; font-weight: 600; fill: var(--muted); pointer-events: none; }
.ap { cursor: grab; outline: none; }
.ap.dragging { cursor: grabbing; }
.ap .halo { fill: currentColor; opacity: 0; }
.ap.sel .halo, .ap:focus-visible .halo { opacity: .22; }
.ap:focus-visible .halo { stroke: var(--accent); stroke-width: 2; }
.ap .dot { fill: currentColor; stroke: var(--card); stroke-width: 3; }
.ap .waves { fill: none; stroke: #fff; stroke-width: 2; stroke-linecap: round; }
.aplabel { font-size: 13px; font-weight: 700; text-anchor: middle; fill: var(--ink); paint-order: stroke; stroke: var(--card); stroke-width: 4px; }
.hint { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); margin: 0; background: var(--card); border: 1px solid var(--line); padding: 8px 14px; border-radius: var(--radius); box-shadow: var(--shadow); }
.legend { display: flex; flex-wrap: wrap; gap: 4px 14px; list-style: none; padding: 0; margin: 10px 0 0; font-size: 12px; color: var(--muted); }
.legend i { display: inline-block; width: 12px; height: 12px; border-radius: 3px; margin-right: 6px; vertical-align: -2px; opacity: .8; }

.panel { position: sticky; top: 76px; }
.panel h2 { display: flex; gap: 8px; }
.homes { display: grid; gap: 10px; }
.homecard { display: flex; align-items: center; gap: 14px; background: var(--card); color: var(--ink); border: 1px solid var(--line); padding: 10px 12px; text-align: left; font-weight: 500; }
.homecard:hover { background: var(--hover); border-color: var(--accent); }
.homecard[aria-checked='true'] { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent) inset; background: var(--accent-soft); }
.homecard svg { width: 96px; flex: none; }
.homecard svg line { stroke: var(--ink); stroke-width: 12; opacity: .7; }
.homecard > span { display: grid; }

.apcard { border: 1px solid var(--line); border-radius: var(--radius); margin-bottom: 8px; overflow: hidden; }
.apcard.open { border-color: var(--ap); }
.aphead { width: 100%; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; background: var(--card); color: var(--ink); border: 0; border-radius: 0; padding: 10px 12px; text-align: left; font-weight: 500; min-height: 44px; }
.aphead:hover { background: var(--hover); }
.swatch { display: inline-block; width: 12px; height: 12px; border-radius: 50%; background: var(--ap); margin-right: 6px; vertical-align: -1px; }
.badge { margin-left: auto; font-size: 11px; font-weight: 700; padding: 1px 8px; border-radius: var(--radius-sm); }
.badge.bad { color: var(--fail); background: var(--fail-bg); }
.form { display: grid; gap: 12px; padding: 4px 12px 12px; }
.field { display: grid; gap: 6px; border: 0; padding: 0; margin: 0; min-width: 0; }
.field > span, .field legend { font-size: 12px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; padding: 0; margin-bottom: 6px; }
.field input { padding: 8px 10px; border-radius: var(--radius); border: 1px solid var(--line); background: var(--card); color: var(--ink); min-height: 38px; width: 100%; }
.field input[aria-invalid='true'] { border-color: var(--fail); box-shadow: 0 0 0 1px var(--fail) inset; }
.fielderr { color: var(--fail); font-size: 12px; font-weight: 600; margin: 0; }
.choices { display: grid; gap: 6px; }
.choice { display: grid; grid-template-columns: auto 1fr; column-gap: 8px; align-items: center; padding: 8px 10px; border: 1px solid var(--line); border-radius: var(--radius); cursor: pointer; }
.choice:hover { background: var(--hover); }
.choice.on { border-color: var(--accent); background: var(--accent-soft); }
.choice input { grid-row: span 2; accent-color: var(--accent); }
.chans { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; }
.remove { background: none; color: var(--fail); border: 1px solid var(--line); min-height: 34px; padding: 4px 12px; font-size: 13px; justify-self: start; margin-top: 8px; }
.remove:hover { background: var(--fail-bg); border-color: var(--fail); }
.add { width: 100%; background: var(--card); color: var(--accent); border: 1px dashed var(--accent); margin-top: 4px; }
.add:hover:not(:disabled) { background: var(--hover); }

.warns { list-style: none; padding: 0; margin: 0 0 14px; display: grid; gap: 8px; }
.warns li { display: flex; gap: 10px; align-items: flex-start; padding: 10px 12px; border-radius: var(--radius); background: var(--skip-bg); font-size: 13px; }
.warns .icon { flex: none; display: grid; place-items: center; width: 18px; height: 18px; border-radius: 50%; background: var(--skip); color: var(--card); font-weight: 800; font-size: 12px; }
.allgood { padding: 10px 12px; border-radius: var(--radius); background: var(--pass-bg); color: var(--pass); font-weight: 600; }
.rooms { width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 12px; }
.rooms caption { text-align: left; padding-bottom: 6px; }
.rooms th { text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); padding: 6px 8px; border-bottom: 1px solid var(--line); }
.rooms td { padding: 8px; border-bottom: 1px solid var(--line); }
.meter { display: inline-block; width: 70px; height: 6px; background: var(--line); border-radius: 3px; overflow: hidden; margin-right: 8px; vertical-align: middle; }
.meter i { display: block; height: 100%; background: var(--pass); }
.meter i.low { background: var(--skip); }
.kpis { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin-bottom: 14px; }
.kpis div { border: 1px solid var(--line); border-radius: var(--radius); padding: 10px 12px; }
.kpis span { display: block; font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; font-weight: 600; }
.kpis b { font-size: 18px; }
.share { display: flex; gap: 6px; }
.share input { font-family: var(--mono); font-size: 12px; }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); margin: 0; }

.footer { display: flex; justify-content: space-between; gap: 8px; margin-top: 4px; }
@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
  .panel { position: static; }
}
@media (max-width: 640px) {
  .stepper { gap: 4px; }
  .stepper button { flex-direction: column; gap: 4px; padding: 6px 2px; font-size: 11px; text-align: center; justify-content: center; }
}
</style>
