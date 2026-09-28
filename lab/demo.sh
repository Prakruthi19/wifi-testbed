#!/usr/bin/env bash
# Five-minute live demo of the test bed. Run inside the Ubuntu VM from the repo root:
#
#   sudo lab/demo.sh            # pauses before each part so you can talk (press Enter)
#   sudo DEMO_PAUSE=0 lab/demo.sh   # no pauses, e.g. to record a backup video
#
# Parts: 1 lab up, 2 good join vs wrong password (and the classifier's verdict), 3 two real
# bugs the first run found, 4 throughput, 5 smart-home password change, 6 report + bug draft.
set -uo pipefail
cd "$(dirname "$0")/.."
[[ $EUID -eq 0 ]] || { echo "run as root: sudo $0" >&2; exit 1; }

PAUSE=${DEMO_PAUSE:-1}
PY=.venv/bin/python
PYTEST=".venv/bin/pytest -q --no-header -p no:warnings"
N=0
# Each part keeps its own HTML report (reports/demo-N.html) instead of overwriting one.
tests() { $PYTEST --html="reports/demo-$N.html" "$@"; }
ART=reports/artifacts

part() {
  echo
  echo "================================================================================"
  echo "  $1"
  echo "================================================================================"
  N=$((N + 1))
  if [[ $PAUSE == 1 ]]; then read -r -p "  [Enter to run] " _; fi
}

part "1/6  Lab: 4 emulated radios, AP in the root namespace, 3 clients in their own namespaces"
[[ -e /sys/class/net/hwsim0 ]] || bash lab/setup_lab.sh
$PY -m testbed.preflight --clean | grep -E "FAIL|stopped|ready|problem" | sed 's/^/  /'
bash lab/setup_lab.sh --versions
echo "  root namespace: $(iw dev | awk '/Interface/{print $2}' | xargs) + hwsim0 (capture point)"
for ns in $(ip netns list | awk '{print $1}' | sort); do
  echo "  $ns: $(ip netns exec "$ns" iw dev | awk '/Interface/{print $2}' | xargs)"
done

part "2/6  One good join and one wrong password: where did it fail, and how do we know?"
tests -m failures -k "baseline_success or wrong_passphrase_wpa2"
echo
echo "  Classifier on the wrong-password capture (reads the air, not the client's log):"
$PY -m classifier.classify_join "$ART/test_induced_failure_wrong_passphrase_wpa2_/capture.pcap" \
    --wpa-pwd labpassword123:lab-diag | sed 's/^/    /'

part "3/6  The two failures the first real run found (issues #4, #5), now fixed"
tests -m failures -k "mac_blocked or dhcp_server_down"
$PY - <<'PYEOF'
import json
for case in ("mac_blocked", "dhcp_server_down"):
    d = json.load(open(f"reports/artifacts/test_induced_failure_{case}_/classification.json"))
    print(f"  {case:17} expected={d['expected'][0]:17} classifier={d['classifier']['stage']:17} "
          f"harness={d['join']['failed_stage']}")
PYEOF

part "4/6  Throughput after a full join (iperf3). VIRTUAL-NETWORK numbers, not real Wi-Fi speed"
tests -m perf -k "wpa2"
for dir in "$ART"/test_throughput*wpa2*; do
  $PY -c "import json,sys; r=json.load(open(sys.argv[1]))['iperf']; print(f\"  {r['direction']:9} {r['mbps']:>9} Mbps  retransmits={r['retransmits']}\")" "$dir/iperf.json"
done

part "5/6  Smart-home device: owner changes the Wi-Fi password"
tests -m smarthome -k "password_change"
echo "  What the device's own log said after the change:"
grep -E "4-Way Handshake failed|WRONG_KEY|CTRL-EVENT-DISCONNECTED" \
  "$ART/test_password_change/supplicant-after-change.log" | head -3 | cut -c1-110 | sed 's/^/    /'

part "6/6  Evidence: results dashboard, per-test pcap + logs, and a drafted bug report"
ls "$ART/test_induced_failure_wrong_passphrase_wpa2_/" | sed 's/^/    /'
$PY -m testbed.bug_draft "$ART/test_induced_failure_wrong_passphrase_wpa2_" | head -16 | sed 's/^/    /'
chmod -R a+rX reports 2>/dev/null
echo
echo "  Reports (one per part):"
ls reports/demo-*.html | sed 's/^/    /'
echo "  One-page summary of every run so far: xdg-open reports/dashboard.html  (as your user)"
