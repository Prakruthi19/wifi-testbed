import { createRouter, createWebHashHistory } from 'vue-router'
import LabOverview from './views/LabOverview.vue'
import TestRuns from './views/TestRuns.vue'
import RunDetail from './views/RunDetail.vue'
import StartRun from './views/StartRun.vue'
import CoveragePlanner from './views/CoveragePlanner.vue'
import SitesOverview from './views/SitesOverview.vue'

// Hash URLs (#/runs) so the static GitHub Pages build works without server-side routing.
export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'lab', component: LabOverview, meta: { title: 'Lab' } },
    { path: '/runs', name: 'runs', component: TestRuns, meta: { title: 'Test runs' } },
    { path: '/runs/:id', name: 'run', component: RunDetail, props: true, meta: { title: 'Run' } },
    { path: '/coverage', name: 'coverage', component: CoveragePlanner, meta: { title: 'Coverage planner' } },
    { path: '/sites', name: 'sites', component: SitesOverview, meta: { title: 'Sites' } },
    { path: '/sites/:id', name: 'site', component: CoveragePlanner, props: true, meta: { title: 'Site' } },
    { path: '/start', name: 'start', component: StartRun, meta: { title: 'Start a run' } },
  ],
})

router.afterEach((to) => {
  document.title = `${to.meta.title ?? 'Lab'} · Wi-Fi Test Lab`
})
