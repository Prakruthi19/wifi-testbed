<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import InfoTip from '../components/InfoTip.vue'
import { BaseButton, SegmentedControl, ToastMessage } from '../components/ui'
import { api, DEMO, formatTime, type CaptureDevice } from '../api'
import { useCapture } from '../stores/capture'

// Packet capture: record N seconds of frames on hwsim0 (or upload a pcap), then show the analysis.
// The store starts the job and polls the API every second until it is done; this page only draws it.
const cap = useCapture()
const mode = ref<'live' | 'upload'>('live')
const seconds = ref(30)
const decrypt = ref('')
const file = ref<File | null>(null)
const networks = ref<{ ssid: string; security: string }[]>([])
const toast = ref<string | null>(null)

// The store itself is resumed by App.vue on load, so a capture is picked up on any page.
onMounted(async () => {
  if (!DEMO) {
    try { networks.value = await api.captures.networks() } catch { /* no API: the form is disabled below */ }
  }
})

const job = computed(() => cap.job)
const r = computed(() => (job.value?.status === 'done' ? job.value.result : null))
const pct = computed(() => {
  const j = job.value
  return j?.status === 'capturing' && j.seconds ? Math.min(100, Math.round((100 * (j.elapsed_s ?? 0)) / j.seconds)) : null
})
const busy = computed(() => DEMO || cap.active)

async function submit() {
  const key = decrypt.value || null
  if (mode.value === 'live') await cap.start(seconds.value, key)
  else if (file.value) await cap.upload(file.value, key)
  if (!cap.error) toast.value = mode.value === 'live' ? `Capturing for ${seconds.value} s…` : `Analysing ${file.value?.name}…`
}
function pick(e: Event) {
  file.value = (e.target as HTMLInputElement).files?.[0] ?? null
}

const kb = (n: number) => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`)
const tone = (d: CaptureDevice) => (d.stage === 'success' ? 'ok' : d.stage === 'undetermined' ? 'neutral' : 'bad')
const maxKind = computed(() => Math.max(1, ...(r.value?.by_kind.map((k) => k.count) ?? [1])))
const sourceText = computed(() => {
  const j = job.value
  if (!j) return ''
  if (j.source === 'sample') return 'Made-up example capture (synthetic frames, not from the lab)'
  if (j.source === 'upload') return `Uploaded file ${j.filename}`
  return `${j.seconds} s on ${j.iface} (emulated radios)`
})
</script>

<template>
  <h1>Packet capture <InfoTip text="Records the frames every emulated radio sends (hwsim0 hears them all), then reads them: who tried to join, where each join stopped, and why devices were disconnected." /></h1>
  <p class="sub">Capture the lab's Wi-Fi traffic for a set time, then see what happened. Frames come from the emulated radios in the VM, not from real hardware.</p>

  <p v-if="DEMO" class="error">This is the read-only demo, so it cannot capture. Below is the analysis of a made-up example capture.</p>

  <form class="card form" aria-label="New capture" @submit.prevent="submit">
    <div class="field">
      <span id="src-label" class="lbl">Source</span>
      <SegmentedControl v-model="mode" labelledby="src-label" :options="[{ value: 'live', label: 'Capture live' }, { value: 'upload', label: 'Upload a file' }]" />
    </div>
    <div v-if="mode === 'live'" class="field">
      <span id="dur-label" class="lbl">How long</span>
      <SegmentedControl v-model="seconds" labelledby="dur-label" :options="[10, 30, 60, 120].map((s) => ({ value: s, label: `${s} s` }))" />
    </div>
    <label v-else class="field">
      <span class="lbl">Capture file (.pcap or .pcapng, up to 50 MB)</span>
      <input type="file" accept=".pcap,.pcapng,.cap" :disabled="busy" @change="pick" />
    </label>
    <label class="field">
      <span class="lbl">Decrypt with <InfoTip text="WPA2 networks encrypt data frames, which hides DHCP and DNS. Pick the lab network and the API decrypts with its password (the password never reaches this page). Works for WPA2-Personal only, and only if the device's 4-way handshake is in the capture." /></span>
      <select v-model="decrypt" :disabled="busy">
        <option value="">Don't decrypt</option>
        <option v-for="n in networks" :key="n.ssid" :value="n.ssid">{{ n.ssid }} ({{ n.security }})</option>
      </select>
    </label>
    <BaseButton type="submit" :disabled="busy || (mode === 'upload' && !file)">
      {{ cap.active ? 'Working…' : mode === 'live' ? 'Start capture' : 'Analyse file' }}
    </BaseButton>
  </form>
  <p v-if="mode === 'live' && !DEMO" class="muted small hint">hwsim0 only carries frames while the lab's radios are in use. For a busy capture, <RouterLink to="/start">start a run</RouterLink> first and capture during it.</p>

  <p v-if="cap.error" class="error" role="alert">{{ cap.error }}</p>

  <section v-if="job && job.status !== 'done'" class="card" aria-live="polite" aria-label="Capture progress">
    <div class="cardhead">
      <h2>{{ job.status === 'capturing' ? 'Capturing' : job.status === 'analysing' ? 'Analysing' : 'Capture failed' }}</h2>
      <span class="muted small">{{ sourceText }}</span>
    </div>
    <template v-if="job.status === 'capturing'">
      <progress :value="job.elapsed_s ?? 0" :max="job.seconds ?? 1" :aria-label="`${pct}% of the capture time`" />
      <p class="muted small">{{ Math.floor(job.elapsed_s ?? 0) }} of {{ job.seconds }} s · {{ kb(job.bytes) }} recorded · checking every second</p>
    </template>
    <p v-else-if="job.status === 'analysing'" class="muted"><span class="spin" aria-hidden="true" /> Reading {{ kb(job.bytes) }} of frames with tshark…</p>
    <p v-else class="error">{{ job.error }}</p>
  </section>

  <template v-if="job && r">
    <div class="cardhead result-head">
      <h2>Result <span class="muted small">· {{ sourceText }} · {{ formatTime(job.finished) }}</span></h2>
      <a v-if="api.captures.pcapUrl(job.id)" :href="api.captures.pcapUrl(job.id)!" download>Download pcap</a>
    </div>
    <div class="tiles">
      <div class="tile"><span>Frames</span><b>{{ r.frames.toLocaleString() }}</b></div>
      <div class="tile"><span>Length</span><b>{{ r.duration_s.toFixed(1) }} s</b></div>
      <div class="tile"><span>Devices</span><b>{{ r.devices.length }}</b></div>
      <div class="tile"><span>Disconnects</span><b :class="{ bad: r.disconnects.length }">{{ r.disconnects.length }}</b></div>
      <div class="tile"><span>Retries</span><b>{{ r.retry_pct }}%</b></div>
    </div>
    <ul v-if="r.notes.length" class="notes card">
      <li v-for="n in r.notes" :key="n">{{ n }}</li>
    </ul>

    <section class="card">
      <h2>Devices <InfoTip text="One row per device that tried to join. The verdict names the first stage that did not finish (the same classifier the lab tests use): scan, authentication, association, 4-way handshake, DHCP, DNS." /></h2>
      <p v-if="!r.devices.length" class="muted">No device tried to join during this capture.</p>
      <table v-else class="stack" aria-label="Devices">
        <thead><tr><th>Device</th><th>Network</th><th>Verdict</th><th>Signal</th><th>Address</th><th>Frames</th></tr></thead>
        <tbody>
          <tr v-for="d in r.devices" :key="d.mac">
            <td data-label="Device" class="mono">{{ d.mac }}</td>
            <td data-label="Network">{{ d.ssid ?? '—' }}</td>
            <td data-label="Verdict"><span class="pill" :class="tone(d)">{{ d.stage_label }}</span><span class="why">{{ d.summary }}</span></td>
            <td data-label="Signal" class="num">{{ d.signal_dbm !== null ? `${d.signal_dbm} dBm` : '—' }}</td>
            <td data-label="Address" class="mono">{{ d.ip ?? '—' }}</td>
            <td data-label="Frames" class="num">{{ d.frames_sent }} sent · {{ d.frames_received }} received</td>
          </tr>
        </tbody>
      </table>
    </section>

    <div class="two">
      <section class="card">
        <h2>Disconnects <InfoTip text="Deauthentication and disassociation frames. The reason code says why the sender ended the connection." /></h2>
        <p v-if="!r.disconnects.length" class="muted">None. No device was kicked off or left.</p>
        <ul v-else class="list">
          <li v-for="d in r.disconnects" :key="d.no">
            <b>Reason {{ d.reason ?? '?' }}: {{ d.meaning }}</b>
            <span class="muted small">{{ d.kind === 'deauth' ? 'Deauth' : 'Disassoc' }} from the {{ d.sender === 'ap' ? 'AP' : d.sender }} <span class="mono">{{ d.from }}</span> to <span class="mono">{{ d.to }}</span> at {{ d.t }} s (frame #{{ d.no }})</span>
          </li>
        </ul>
      </section>
      <section class="card">
        <h2>4-way handshakes <InfoTip text="The four EAPOL-Key messages that turn the Wi-Fi password into this session's keys. M1 and M3 come from the AP, M2 and M4 from the device. A repeated message is a resend." /></h2>
        <p v-if="!r.handshakes.length" class="muted">No handshakes (open networks have none).</p>
        <ul v-else class="list">
          <li v-for="h in r.handshakes" :key="h.client + h.bssid">
            <span class="msgs">
              <span v-for="(m, i) in h.messages" :key="i" class="msg" :class="{ ap: m === 1 || m === 3 }">M{{ m }}</span>
              <span class="pill" :class="h.complete ? 'ok' : 'bad'">{{ h.complete ? 'Complete' : 'Incomplete' }}</span>
            </span>
            <span class="muted small"><span class="mono">{{ h.client }}</span> with AP <span class="mono">{{ h.bssid }}</span> · {{ h.duration_ms }} ms<template v-if="h.retries"> · {{ h.retries }} resent</template></span>
          </li>
        </ul>
      </section>
    </div>

    <div class="two">
      <section class="card">
        <h2>Frame types</h2>
        <ul class="bars" aria-label="Frames by type">
          <li v-for="k in r.by_kind" :key="k.kind">
            <span class="name">{{ k.label }}</span>
            <span class="track"><span class="fill" :style="{ width: `${(100 * k.count) / maxKind}%` }" /></span>
            <span class="count">{{ k.count }}</span>
          </li>
        </ul>
      </section>
      <section class="card">
        <h2>Networks heard</h2>
        <p v-if="!r.networks.length" class="muted">No beacons in this capture.</p>
        <table v-else class="stack" aria-label="Networks">
          <thead><tr><th>Name</th><th>AP</th><th>Security</th><th>Beacons</th></tr></thead>
          <tbody>
            <tr v-for="n in r.networks" :key="n.bssid">
              <td data-label="Name">{{ n.ssid || '(hidden)' }}</td>
              <td data-label="AP" class="mono">{{ n.bssid }}</td>
              <td data-label="Security">{{ n.secured ? 'WPA2/WPA3' : 'Open' }}</td>
              <td data-label="Beacons" class="num">{{ n.beacons }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>

    <section v-if="r.dhcp.length || r.dns.length" class="card">
      <h2>Addresses and names <InfoTip text="DHCP hands the device an IP address (Discover, Offer, Request, ACK). DNS turns names into addresses." /></h2>
      <div class="two inner">
        <ul class="list" aria-label="DHCP">
          <li v-for="d in r.dhcp" :key="d.no"><b>DHCP {{ d.type }}</b> <span class="muted small">{{ d.t }} s · <span class="mono">{{ d.client }}</span><template v-if="d.ip"> · {{ d.ip }}</template></span></li>
        </ul>
        <ul class="list" aria-label="DNS">
          <li v-for="d in r.dns" :key="d.no"><b>DNS {{ d.response ? 'answer' : 'query' }}</b> <span class="muted small">{{ d.t }} s · {{ d.name }}<template v-if="d.answer"> → {{ d.answer }}</template><template v-if="d.response && d.rcode"> (error {{ d.rcode }})</template></span></li>
        </ul>
      </div>
    </section>

    <details class="card">
      <summary>Key frames ({{ r.events_total }}<template v-if="r.events_total > r.events.length">, first {{ r.events.length }} shown</template>)</summary>
      <table class="stack frames" aria-label="Key frames">
        <thead><tr><th>#</th><th>Time</th><th>Frame</th><th>Details</th></tr></thead>
        <tbody>
          <tr v-for="e in r.events" :key="e.no">
            <td data-label="#" class="num">{{ e.no }}</td>
            <td data-label="Time" class="num">{{ e.t.toFixed(3) }} s</td>
            <td data-label="Frame">{{ e.label }}</td>
            <td data-label="Details" class="mono small">{{ e.text.replace(/^#\d+ \S+ ?/, '') }}</td>
          </tr>
        </tbody>
      </table>
    </details>
  </template>

  <section v-if="cap.recent.length" class="card">
    <h2>Recent captures</h2>
    <table class="stack" aria-label="Recent captures">
      <thead><tr><th>When</th><th>Source</th><th>Frames</th><th>Devices</th><th>Disconnects</th><th></th></tr></thead>
      <tbody>
        <tr v-for="c in cap.recent" :key="c.id" :class="{ current: c.id === job?.id }">
          <td data-label="When">{{ formatTime(c.started) }}</td>
          <td data-label="Source">{{ c.source === 'live' ? `${c.seconds} s live` : c.filename }}</td>
          <td data-label="Frames" class="num">{{ c.status === 'failed' ? 'failed' : c.frames }}</td>
          <td data-label="Devices" class="num">{{ c.devices }}</td>
          <td data-label="Disconnects" class="num">{{ c.disconnects }}</td>
          <td><BaseButton variant="secondary" size="sm" :disabled="c.id === job?.id" @click="cap.open(c.id)">Open</BaseButton></td>
        </tr>
      </tbody>
    </table>
  </section>

  <ToastMessage v-if="toast" :text="toast" @close="toast = null" />
</template>

<style scoped>
.form { display: flex; flex-wrap: wrap; gap: 16px; align-items: end; }
.field { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.lbl { font-size: 12px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
input[type='file'] { max-width: 100%; }
.hint { margin: -8px 0 16px; }
.small { font-size: 13px; }
progress { width: 100%; height: 10px; accent-color: var(--accent); }
.spin { display: inline-block; width: 12px; height: 12px; border: 2px solid var(--line); border-top-color: var(--accent); border-radius: 50%; animation: spin .8s linear infinite; vertical-align: -1px; margin-right: 6px; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
.result-head { margin-top: 8px; }
.tile b.bad { color: var(--fail); }
.notes { margin: 0 0 16px; padding: 12px 18px 12px 34px; color: var(--muted); }
.pill { display: inline-block; font-size: 12px; font-weight: 600; padding: 2px 10px; border-radius: 999px; white-space: nowrap; }
.pill.ok { color: var(--pass); background: var(--pass-bg); }
.pill.bad { color: var(--fail); background: var(--fail-bg); }
.pill.neutral { color: var(--muted); background: var(--bg); }
.why { display: block; color: var(--muted); font-size: 12px; margin-top: 2px; }
.two { display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }
.two > .card { margin-bottom: 0; }
.two + * { margin-top: 16px; }
.two.inner { gap: 8px 24px; }
.list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
.list li { display: flex; flex-direction: column; gap: 2px; }
.msgs { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.msg { font: 600 12px var(--mono); padding: 2px 6px; border-radius: var(--radius-sm); background: var(--accent-soft); color: var(--accent); }
.msg.ap { background: var(--bg); color: var(--ink); border: 1px solid var(--line); }
.msgs .pill { margin-left: 6px; }
.bars { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.bars li { display: grid; grid-template-columns: minmax(110px, 40%) 1fr 40px; gap: 10px; align-items: center; font-size: 13px; }
.track { height: 8px; background: var(--bg); border-radius: 999px; overflow: hidden; }
.fill { display: block; height: 100%; background: var(--series-1); border-radius: 999px; }
.count { text-align: right; font-variant-numeric: tabular-nums; color: var(--muted); }
details summary { cursor: pointer; font-weight: 650; }
details[open] summary { margin-bottom: 12px; }
.frames td { padding: 6px 10px; }
tr.current { background: var(--accent-soft); }
td.mono, .mono { word-break: break-all; }
@media (max-width: 640px) {
  .form > * { width: 100%; }
  .bars li { grid-template-columns: 1fr 70px 32px; }
}
</style>
