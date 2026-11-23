// Plain-language descriptions of tests, steps, facts and files, so a reader who has never seen the
// test code can tell what each result means. Anything not listed here falls back to a tidied-up name.

import { testName } from './api'

export interface TestInfo {
  title: string
  what: string // what the test does
  expectStop?: string // join step a deliberately broken setup should stop at ("success" = must connect)
}

export const SUITES: Record<string, string> = {
  failures: 'Failure diagnosis',
  enterprise: 'Enterprise login (802.1X)',
  decrypt: 'Capture decryption',
  roam: 'Roaming between access points',
  faults: 'Fault injection',
  smarthome: 'Smart-home behaviour',
  perf: 'Speed and delay',
  matrix: 'Connectivity matrix',
  qualify: 'Access point qualification',
  vlan: 'Network separation (VLANs)',
  home: 'Home mesh network',
  unit: 'Unit tests',
}

// The steps a device goes through to get online, in order.
export const STEPS: Record<string, { label: string; explain: string }> = {
  network_selection: { label: 'Find the network', explain: 'The device scans the air, sees the Wi-Fi name and decides it can use it.' },
  authentication: { label: 'Say hello', explain: 'The device and router introduce themselves. On WPA3 the password is checked here.' },
  association: { label: 'Join', explain: 'The router accepts the device as a member of its network.' },
  eap: { label: 'Username login (802.1X)', explain: 'On work networks the device logs in with a username and password checked by a login server.' },
  key_exchange: { label: 'Agree keys (4-way handshake)', explain: 'Both sides prove they know the Wi-Fi password and make encryption keys. On WPA2 a wrong password fails here.' },
  dhcp: { label: 'Get an address (DHCP)', explain: 'The device asks the network for an IP address, like getting a house number.' },
  dns: { label: 'Look up names (DNS)', explain: 'The device turns a name like gw.lab into an address. If this fails, "connected but no internet".' },
}
export const stepLabel = (key: string) =>
  key === 'success' ? 'Fully online' : key === 'undetermined' ? 'Could not tell' : STEPS[key]?.label ?? key

const FAILURES: Record<string, TestInfo> = {
  baseline_success: { title: 'Normal join (control test)', what: 'Correct password, nothing broken. Proves the lab works before we start breaking things.', expectStop: 'success' },
  wrong_passphrase_wpa2: { title: 'Wrong Wi-Fi password (WPA2)', what: 'The device is given the wrong password on a WPA2 network.', expectStop: 'key_exchange' },
  wrong_password_wpa3: { title: 'Wrong Wi-Fi password (WPA3)', what: 'The device is given the wrong password on a WPA3 network, which checks it earlier than WPA2.', expectStop: 'authentication' },
  wpa2_client_wpa3_ap: { title: 'Old device, new security', what: 'A device that only knows WPA2 meets a router that only allows WPA3.', expectStop: 'network_selection' },
  pmf_mismatch: { title: 'Protection setting mismatch', what: 'The router requires protected management frames (PMF); the device has them switched off.', expectStop: 'network_selection' },
  mac_blocked: { title: 'Device blocked by the router', what: "The router is told to refuse this device's hardware address.", expectStop: 'network_selection' },
  dhcp_server_down: { title: 'Address server switched off', what: 'Wi-Fi works, but the service that hands out IP addresses (DHCP) is stopped.', expectStop: 'dhcp' },
  dns_broken: { title: 'Name lookup broken', what: 'Wi-Fi and addresses work, but the name lookup service (DNS) is stopped.', expectStop: 'dns' },
}

const ENTERPRISE: Record<string, TestInfo> = {
  pwd_success: { title: 'Work login, right password (EAP-PWD)', what: 'Username and correct password on a work-style network.', expectStop: 'success' },
  pwd_wrong_password: { title: 'Work login, wrong password (EAP-PWD)', what: 'Username with the wrong password.', expectStop: 'eap' },
  peap_success: { title: 'Work login, right password (PEAP)', what: 'Username and correct password inside an encrypted tunnel (PEAP).', expectStop: 'success' },
  peap_wrong_password: { title: 'Work login, wrong password (PEAP)', what: 'Username with the wrong password inside the PEAP tunnel.', expectStop: 'eap' },
  peap_untrusted_server: { title: 'Fake login server refused', what: "The login server's certificate is not one the device trusts, so the device must refuse to send its password.", expectStop: 'eap' },
}

export function describe(nodeid: string): TestInfo {
  const name = testName(nodeid) // e.g. induced_failure[mac_blocked]
  const m = name.match(/^([^[]+)(?:\[(.+)\])?$/)
  const fn = m?.[1] ?? name
  const param = m?.[2] ?? ''
  if (fn === 'induced_failure' && FAILURES[param]) return FAILURES[param]
  if (fn === 'enterprise_join' && ENTERPRISE[param]) return ENTERPRISE[param]
  if (fn === 'roam')
    return param === 'ft'
      ? { title: 'Fast roaming (802.11r)', what: 'The device walks from one access point to another using Fast Transition, which skips most of the login. We time the switch and check the IP address is kept.' }
      : { title: 'Normal roaming (full login)', what: 'The device walks from one access point to another and logs in again from scratch. This is the baseline to compare fast roaming against.' }
  if (fn === 'wpa3_capture_needs_session_pmk')
    return { title: 'Decrypting a WPA3 capture', what: 'Checks that a WPA3 packet capture can only be read with the session key, not with the Wi-Fi password alone (WPA3 forward secrecy).' }
  const extra: Record<string, TestInfo> = {
    ap_kicks_client: { title: 'Router kicks the device off', what: 'The router disconnects the device; we check the device notices and the capture shows who did it and why.' },
    supplicant_restart: { title: 'Wi-Fi software restarts on the device', what: `The device's Wi-Fi software is ${param === 'crash' ? 'killed' : 'stopped cleanly'} and restarted; it must reconnect.` },
    ap_crash: { title: 'Router crashes', what: 'The router software is killed; the device must notice it is gone.' },
    link_interruption: { title: 'Signal drops for a moment', what: 'The radio link is cut briefly; the device must come back on its own.' },
    security_change_blocks_wpa2_only_client: { title: 'Router upgraded to WPA3-only', what: 'An old WPA2-only device must be refused once the router switches to WPA3-only.' },
    recovers_after_router_reboot: { title: 'Router reboot', what: 'The router restarts; a smart-home device must rejoin on its own.' },
    password_change: { title: 'Wi-Fi password changed', what: 'After a password change the device with the old password must be refused at the right step.' },
    '2g_only_device': { title: '2.4 GHz-only device', what: `A cheap device with only a 2.4 GHz radio meets a ${param.startsWith('5') ? '5 GHz' : '2.4 GHz'} router.` },
    throughput: { title: 'Download/upload speed', what: 'Measures TCP speed over the emulated radio with iperf3 (a software baseline, not real Wi-Fi speed).' },
    udp_jitter_loss: { title: 'Video-stream quality', what: 'Sends a camera-like UDP stream and records loss and jitter (variation in delay).' },
    latency: { title: 'Delay (ping)', what: 'Measures round-trip time to the router.' },
    everyone_joins: { title: 'Whole house joins at once', what: 'Phone, laptop, camera, plug and speaker all join together.' },
    mesh_walk: { title: 'Walk through the house', what: 'The phone moves from the router to each mesh point and back while pinging.' },
    mesh_point_down: { title: 'Mesh point unplugged', what: 'One mesh point is switched off; its devices must move to another.' },
    interop: { title: 'Device and router compatibility', what: `Every device type against a ${param} router; expected results were written before the run.` },
    busy_house: { title: 'Busy house', what: 'A download, a camera stream and a ping run at the same time.' },
    troubleshoot: { title: 'Troubleshooting case', what: 'One thing is broken on purpose; the plain-words diagnosis must name it, then it is fixed and the device rejoins.' },
    neighbor_report: { title: 'Router lists its neighbours (802.11k)', what: 'The phone asks the router for nearby access points and must get the other two with the right channels.' },
    steering: { title: 'Router suggests a better AP (802.11v)', what: 'The router asks the phone to move; we record whether and where it goes.' },
    discovery: { title: 'Finding the smart speaker (mDNS)', what: 'The phone looks for the speaker by name on the local network.' },
    matrix: { title: 'Join test', what: 'One security x channel x device combination, joined several times.' },
    qualify_ap: { title: 'Access point qualification step', what: 'One step of the baseline every new access point must pass.' },
    lease_from_correct_subnet: { title: 'Address from the right network (VLAN)', what: 'A device on this Wi-Fi name must get an IP address from its own VLAN, not another one.' },
    dns_resolves: { title: 'Name lookup works (VLAN)', what: 'A device on this Wi-Fi name can look up names through its own VLAN gateway.' },
    iot_cannot_reach_mgmt: { title: 'Smart devices cannot reach the admin network', what: 'The firewall must block the IoT VLAN from the management VLAN.' },
    mgmt_can_reach_iot: { title: 'Admin network can reach smart devices', what: 'The management VLAN is allowed to reach the IoT VLAN.' },
    test_ssid_cannot_reach_iot: { title: 'Test network cannot reach smart devices', what: 'The test VLAN must be blocked from the IoT VLAN.' },
    iot_clients_reach_each_other: { title: 'Smart devices can reach each other', what: 'Two devices on the IoT Wi-Fi can talk to each other while isolation is off.' },
    iot_client_isolation: { title: 'Client isolation keeps smart devices apart', what: 'With client isolation on, two devices on the IoT Wi-Fi must not reach each other.' },
  }
  return extra[fn] ?? { title: name.replace(/_/g, ' '), what: '' }
}

// The part of a test id that tells repeated tests apart (pytest's [parameter]), e.g. "lab-wpa3-ch36".
// Empty when the title already says it (failure cases, enterprise cases, roaming).
export function variantOf(nodeid: string) {
  const m = testName(nodeid).match(/^([^[]+)\[(.+)\]$/)
  if (!m || ['induced_failure', 'enterprise_join', 'roam'].includes(m[1])) return ''
  return m[2]
}

// Suite name for a result. Older runs recorded the home-network tests as "other" (the marker was
// missing from the dashboard's list), so those are recognised by their file.
export function suiteLabel(suite: string, nodeid: string) {
  if (suite === 'other' && nodeid.includes('test_home_network')) return SUITES.home
  return SUITES[suite] ?? suite
}

// Facts tests record, with plain labels and units. Unlisted facts keep their own name.
const FACTS: Record<string, { label: string; unit?: string; hint?: string }> = {
  roam_ms_log: { label: 'Time to switch access point', unit: 'ms', hint: "from the device's own log" },
  roam_ms_wall: { label: 'Time to switch (stopwatch)', unit: 'ms' },
  auth_alg: { label: 'Login method used' },
  key_mgmt: { label: 'Security type used' },
  moved: { label: 'Moved to the other access point' },
  join_s: { label: 'Time to get online', unit: 's' },
  rejoin_s: { label: 'Time to come back', unit: 's' },
  reconnect_s: { label: 'Time to reconnect', unit: 's' },
  recovery_s: { label: 'Time to recover', unit: 's' },
  mbps: { label: 'Speed', unit: 'Mbit/s' },
  max_clean_mbps: { label: 'Highest rate with under 5% loss', unit: 'Mbit/s' },
  jitter_ms: { label: 'Jitter (delay variation)', unit: 'ms' },
  ping_loss_percent: { label: 'Pings lost', unit: '%' },
  camera_loss_percent: { label: 'Camera stream lost', unit: '%' },
  retransmits: { label: 'Packets re-sent' },
  pass_rate: { label: 'Joins that worked', unit: '%' },
  median_join_ms: { label: 'Typical join time', unit: 'ms' },
  diagnosis: { label: 'Plain-words diagnosis' },
  connected_to: { label: 'Connected to' },
  now_on: { label: 'Now on' },
}
const HIDDEN = new Set(['stage', 'classified_stage', 'classifier_stage', 'harness_stage'])
const VALUES: Record<string, string> = { FT: 'Fast Transition (802.11r)', 'WPA-PSK': 'WPA2 password', SAE: 'WPA3 password', 'FT-PSK': 'WPA2 password + fast roaming' }

export function facts(props: Record<string, unknown>) {
  return Object.entries(props)
    .filter(([k, v]) => !HIDDEN.has(k) && (typeof v !== 'object' || v === null))
    .map(([k, v]) => {
      const f = FACTS[k]
      const value = typeof v === 'boolean' ? (v ? 'yes' : 'no') : VALUES[String(v)] ?? String(v)
      return { key: k, label: f?.label ?? k.replace(/_/g, ' '), value: f?.unit ? `${value} ${f.unit}` : value, hint: f?.hint }
    })
}

export function fileLabel(name: string) {
  if (name.endsWith('.pcap') || name.endsWith('.pcapng')) return 'Packet capture (open in Wireshark)'
  if (name === 'classification.json') return "Classifier's verdict"
  if (name.startsWith('hostapd')) return 'Router log'
  if (name.startsWith('wpa_supplicant') || name.startsWith('supplicant')) return 'Device Wi-Fi log'
  if (name.startsWith('dnsmasq')) return 'Address/name server log'
  if (name.startsWith('dhclient')) return 'Device address log'
  if (name.endsWith('.log')) return 'Log'
  return 'File'
}
