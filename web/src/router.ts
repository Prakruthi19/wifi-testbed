import { createRouter, createWebHashHistory } from 'vue-router'
import LabOverview from './views/LabOverview.vue'
import TestRuns from './views/TestRuns.vue'
import RunDetail from './views/RunDetail.vue'
import StartRun from './views/StartRun.vue'
import CoveragePlanner from './views/CoveragePlanner.vue'
import SitesOverview from './views/SitesOverview.vue'
import NetworkBuilder from './views/NetworkBuilder.vue'
import LoginPage from './views/LoginPage.vue'
import PacketCapture from './views/PacketCapture.vue'

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
    { path: '/builder', name: 'builder', component: NetworkBuilder, meta: { title: 'Network builder' } },
    { path: '/capture', name: 'capture', component: PacketCapture, meta: { title: 'Packet capture' } },
    { path: '/start', name: 'start', component: StartRun, meta: { title: 'Start a run' } },
    { path: '/login', name: 'login', component: LoginPage, meta: { title: 'Log in' } },
  ],
})
