# wifi-testbed

An emulated Wi-Fi lab that costs nothing to run. It runs automated connectivity tests across
WPA2/WPA3, PMF, bands and channels, and it names the stage where a join failed by reading
802.11 captures.

> **This lab is emulated.** Radios come from the Linux `mac80211_hwsim` module. The AP
> (hostapd) and clients (wpa_supplicant) are the real production software; only the RF layer
> is simulated. The lab does **not** show RF effects (interference, multipath, attenuation,
> signal strength), vendor chipset or driver differences, consumer router firmware, or work with
> RF test equipment. A real lab closes these gaps with physical APs from several vendors,
> shielded enclosures for repeatability, and programmable attenuators to control signal level.

| Module | What it does | Run with |
|---|---|---|
| 1. Connectivity harness | 100-case matrix (security x PMF x channel x client), 5 joins each, pass rate + timings | `-m matrix` |
| &nbsp;&nbsp;qualify_ap | 6-step baseline for each AP in `lab/inventory.yaml` | `-m qualify` |
| 2. Capture diagnosis | induces 7 failure types, classifies each pcap by failure stage | `-m failures` |
| 3. VLAN segmentation | 3 SSIDs -> 3 VLANs, nftables isolation tests | `-m vlan` |
| 4. Android (ADB) | reconnect, airplane mode, dumpsys parsing, degraded network; join a named network by command, wrong password named by stage from logcat, bugreport on failure | `-m android` (host) |
| Performance | iperf3 TCP uplink/downlink (WPA2 ch6, WPA3 ch36), UDP jitter/loss, ping latency | `-m perf` |
| Fault injection | AP kicks the client (deauth), wpa_supplicant crash + restart, link drop, AP switches to WPA3-only under a WPA2-only client | `-m faults` |
| Smart-home behaviours | recovery after router reboot, old password after a password change, 2.4 GHz-only device vs 5 GHz AP | `-m smarthome` |
| Range vs rate (designed only) | attenuator sweep recording RSSI, link rate, throughput; needs real radios + attenuator | `-m rf --attenuator http://<ip>` |

Designed, not run (no hardware yet): `testbed/openwrt.py` (configure a real OpenWrt AP from the
same `ApConfig`), `testbed/attenuator.py` + `tests/test_rvr.py`, `lab/monitor_capture.sh`
(over-the-air capture with a monitor-mode USB adapter). Bug reports: `python -m testbed.bug_draft
reports/artifacts/<test>` drafts one from a failed test's artifacts.

See [docs/test-plan.md](docs/test-plan.md) for the matrix and expected results,
[docs/failure-signatures.md](docs/failure-signatures.md) for the failure catalog, and
[docs/architecture.md](docs/architecture.md) for the topology.

## Layout

```
lab/          setup/teardown scripts, inventory.yaml, nftables policy, package installer
configs/      Jinja2 templates: hostapd, wpa_supplicant, dnsmasq
testbed/      Python package: ap, client, capture, network, android, matrix, report
classifier/   classify_join.py: pcap -> failure stage + evidence frames
tests/        lab tests (Modules 1-4) and tests/unit (run anywhere)
reports/      generated JUnit XML, HTML report, matrix.html, per-test artifacts (gitignored)
```

## Setup (from a clean VM)

1. Create an **Ubuntu 24.04** VM (VirtualBox, or UTM on a Mac) with ~4 GB RAM and 25 GB disk.
   WSL2 won't work, because its kernel is built without `mac80211_hwsim`.
2. Clone this repo into the VM, then install packages and the Python venv:
   ```bash
   bash lab/install_packages.sh
   ```
3. Bring the lab up (loads hwsim, sets `iw reg set US`, stops NetworkManager from managing the
   radios, creates `ns-client1..3`, brings up `hwsim0`):
   ```bash
   sudo bash lab/setup_lab.sh
   sudo bash lab/setup_lab.sh --versions   # copy into lab/inventory.yaml `software:`
   ```
4. **Checkpoint: do this by hand before running any automation.**
   ```bash
   # AP: WPA2 on ap0
   cat > /tmp/ap.conf <<'EOF'
   interface=ap0
   driver=nl80211
   ssid=lab-wpa2
   hw_mode=g
   channel=6
   wpa=2
   wpa_key_mgmt=WPA-PSK
   rsn_pairwise=CCMP
   wpa_passphrase=labpassword123
   EOF
   sudo hostapd -B /tmp/ap.conf
   sudo dnsmasq --interface=ap0 --bind-dynamic --dhcp-range=192.168.50.100,192.168.50.199,5m \
        --address=/gw.lab/192.168.50.1 --no-resolv

   # Client in ns-client1
   wpa_passphrase lab-wpa2 labpassword123 > /tmp/sta.conf
   sudo ip netns exec ns-client1 wpa_supplicant -B -i sta1 -c /tmp/sta.conf
   sudo ip netns exec ns-client1 dhclient -1 -v sta1
   sudo ip netns exec ns-client1 dig +short @192.168.50.1 gw.lab    # -> 192.168.50.1

   # Watch it in Wireshark on hwsim0, then clean up:
   sudo pkill hostapd; sudo pkill dnsmasq; sudo pkill wpa_supplicant
   ```
   After this checkpoint passes, `sudo bash lab/setup_lab.sh` resets the lab to a clean state.

## Running

Lab tests need root (they manage namespaces, hostapd and captures):

```bash
PYTEST="sudo -E .venv/bin/pytest"

.venv/bin/pytest tests/unit              # no lab needed
$PYTEST -m qualify                       # gate: every inventory AP passes the baseline
$PYTEST -m matrix                        # full Module 1 matrix (100 cases x 5 joins)
$PYTEST -m matrix --channels 6,36 --repeats 2   # quick subset
$PYTEST -m failures                      # Module 2
$PYTEST -m vlan                          # Module 3
$PYTEST -m perf                          # iperf3 throughput
$PYTEST -m smarthome                     # IoT device behaviours
$PYTEST -m faults                        # fault injection while connected

sudo .venv/bin/python -m testbed.preflight --clean   # environment check, stop stray daemons
.venv/bin/python -m testbed.compare reports/baseline/junit.xml reports/junit.xml  # regressions
```

Every run writes `reports/junit.xml`, `reports/report.html` (with the connectivity matrix in the
summary and logs/pcaps linked per test), `reports/matrix.html`, and
`reports/artifacts/<test>/`.

Classify any capture directly:

```bash
.venv/bin/python -m classifier.classify_join reports/artifacts/<test>/capture.pcap \
    --wpa-pwd labpassword123:lab-diag
```

### Android (host, not the VM)

Install Android Studio, create a Pixel AVD (API 34+), start it, and put `adb` on your PATH. Then,
on the host:

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/pytest -m android [--android-serial emulator-5554] [--android-ping-host 8.8.8.8]

# Join tests: the phone joins a named network by command; the wrong-password test needs a
# secured network, so use a real phone over USB (not ADB over Wi-Fi: forgetting the network
# would cut the ADB link).
.venv/bin/pytest -m android --android-ssid HomeNet --android-security wpa2 \
    --android-psk '<password>' [--android-bugreport]
```

Android tests are deselected unless you pass `-m android`, so they stay out of VM runs.

## Bug tracking

Track bugs in GitHub Issues the way a lab would. Each issue gets repro steps, expected vs actual
results, the triggering config (`reports/artifacts/<test>/results.json` has it), the pcap and logs, and
labels for severity (`sev:1`-`sev:4`) and status (`new`, `confirmed`, `fixed`, `regressed`).
When a bug is fixed, add a regression test and link it from the issue. Many bugs will be in the
harness or configs, and those count too.

## Limitations

* The RF layer is emulated, so the lab has no signal level, interference, or roaming under
  fading.
* It covers one driver (`mac80211_hwsim`) and one AP/client software stack
  (hostapd/wpa_supplicant).
* The Android emulator can only join its built-in `AndroidWifi` network, and it runs on the
  host while the emulated radios live in the VM, so no phone ever joins the lab AP. The join
  tests run against whatever network the phone can see (e.g. home Wi-Fi), not the lab matrix.
* Throughput over emulated radios measures the software path, not air speed; it is a smoke
  test and a regression baseline only.
* Expected failure stages in Module 2 stay hypotheses until they're confirmed against captures
  (see the status field in `docs/failure-signatures.md`).
