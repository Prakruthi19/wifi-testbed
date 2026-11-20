<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, formatTime, type Lab } from '../api'
import { useSummary } from '../stores/summary'
import CountsBar from '../components/CountsBar.vue'

const summary = useSummary()
const lab = ref<Lab | null>(null)
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    lab.value = await api.lab()
  } catch (e) {
    error.value = (e as Error).message
  }
})

const securityLabel: Record<string, string> = { wpa2: 'WPA2-Personal', wpa3: 'WPA3-Personal (SAE)', transition: 'WPA2/WPA3 mixed' }
const band = (channel: number) => (channel > 14 ? '5 GHz' : '2.4 GHz')
</script>

<template>
  <h1>Lab overview</h1>
  <p class="sub">Access points, client radios and networks in the emulated lab, and how the latest tests went.</p>

  <p v-if="error || summary.error" class="error">Could not load lab data: {{ error ?? summary.error }}</p>

  <div v-if="summary.data" class="tiles">
    <div class="tile"><b>{{ summary.data.tests }}</b><span>tests tracked</span></div>
    <div class="tile"><b>{{ summary.data.counts.passed }}</b><span>passing now</span></div>
    <div class="tile"><b>{{ summary.data.counts.failed + summary.data.counts.error }}</b><span>failing now</span></div>
    <div class="tile"><b>{{ summary.data.runs }}</b><span>runs recorded</span></div>
  </div>
  <div v-if="summary.data" class="card">
    <h2>Latest result of every test</h2>
    <CountsBar :counts="summary.data.counts" />
    <p class="muted">Last run finished {{ formatTime(summary.data.last_finished) }}. <RouterLink to="/runs">See all runs</RouterLink></p>
  </div>

  <section v-if="lab?.aps?.length" class="card">
    <h2>Access points</h2>
    <table class="stack">
      <thead><tr><th>Name</th><th>Wi-Fi name</th><th>Security</th><th>Band / channel</th><th>PMF</th></tr></thead>
      <tbody>
        <tr v-for="ap in lab.aps" :key="ap.name">
          <td data-label="Name"><b>{{ ap.name }}</b></td>
          <td data-label="Wi-Fi name">{{ ap.ssid }}</td>
          <td data-label="Security">{{ securityLabel[ap.security] ?? ap.security }}</td>
          <td data-label="Band / channel">{{ band(ap.channel) }} · ch {{ ap.channel }}</td>
          <td data-label="PMF">{{ ap.pmf === 2 ? 'required' : ap.pmf === 1 ? 'optional' : 'off' }}</td>
        </tr>
      </tbody>
    </table>
  </section>

  <div class="grid">
    <section v-if="lab?.client_radios?.length" class="card">
      <h2>Client radios</h2>
      <ul>
        <li v-for="c in lab.client_radios" :key="c.name"><b>{{ c.name }}</b> <span class="muted">{{ c.iface }} in {{ c.namespace }}</span></li>
      </ul>
    </section>
    <section v-if="lab?.vlans?.length" class="card">
      <h2>Networks (VLANs)</h2>
      <ul>
        <li v-for="v in lab.vlans" :key="v.vlan"><b>{{ v.ssid }}</b> <span class="muted">VLAN {{ v.vlan }} · {{ v.subnet }}</span></li>
      </ul>
    </section>
  </div>
</template>
