import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { MAX_APS, emptyPlan, homeOf, newAp, type HomeId, type Plan, type PlanAp } from '../builder'

// The network builder's state, kept outside the page so leaving and coming back keeps the plan.
// Undo and redo keep whole copies of the plan: it is small (a home and up to 4 APs), so copies
// are simpler and safer than recording each change and its inverse.
const HISTORY = 50
const copy = (p: Plan): Plan => JSON.parse(JSON.stringify(p))

export const useBuilder = defineStore('builder', () => {
  const plan = ref<Plan>(emptyPlan())
  const step = ref(1)
  const selected = ref<string | null>(null)
  const past = ref<Plan[]>([])
  const future = ref<Plan[]>([])
  const savedAs = ref<string | null>(null) // the name it was last saved or opened under, to prefill Save

  // Every change goes through here so it can be undone.
  function change(fn: (p: Plan) => void) {
    past.value = [...past.value.slice(-(HISTORY - 1)), copy(plan.value)]
    future.value = []
    fn(plan.value)
  }
  // A drag is one change: remember the plan when it starts, then move freely without new entries.
  const beginDrag = () => change(() => {})
  function moveLive(id: string, x: number, y: number) {
    const ap = plan.value.aps.find((a) => a.id === id)
    if (ap) { ap.x = Math.round(x); ap.y = Math.round(y) }
  }

  function undo() {
    const prev = past.value.at(-1)
    if (!prev) return
    future.value = [copy(plan.value), ...future.value]
    past.value = past.value.slice(0, -1)
    plan.value = prev
    if (selected.value && !prev.aps.some((a) => a.id === selected.value)) selected.value = null
  }
  function redo() {
    const next = future.value[0]
    if (!next) return
    past.value = [...past.value, copy(plan.value)]
    future.value = future.value.slice(1)
    plan.value = next
  }

  // Changing the home keeps the APs but moves any that fall outside the new home's walls inside.
  function setHome(id: HomeId) {
    if (plan.value.home === id) return
    change((p) => {
      p.home = id
      const b = homeOf(id).bounds
      for (const ap of p.aps) { ap.x = Math.min(b.x1 - 10, Math.max(b.x0 + 10, ap.x)); ap.y = Math.min(b.y1 - 10, Math.max(b.y0 + 10, ap.y)) }
    })
  }
  function addAp() {
    if (plan.value.aps.length >= MAX_APS) return
    const ap = newAp(plan.value)
    change((p) => p.aps.push(ap))
    selected.value = ap.id
  }
  function removeAp(id: string) {
    change((p) => { p.aps = p.aps.filter((a) => a.id !== id) })
    if (selected.value === id) selected.value = plan.value.aps[0]?.id ?? null
  }
  function updateAp(id: string, patch: Partial<PlanAp>) {
    change((p) => { const ap = p.aps.find((a) => a.id === id); if (ap) Object.assign(ap, patch) })
  }
  function load(p: Plan) {
    change((cur) => { cur.home = p.home; cur.aps = p.aps })
    selected.value = p.aps[0]?.id ?? null
  }
  function reset() {
    change((p) => { p.home = 'house'; p.aps = [] })
    step.value = 1
    selected.value = null
    savedAs.value = null
  }

  const canUndo = computed(() => past.value.length > 0)
  const canRedo = computed(() => future.value.length > 0)
  return { plan, step, selected, savedAs, canUndo, canRedo, change, beginDrag, moveLive, undo, redo, setHome, addAp, removeAp, updateAp, load, reset }
})
