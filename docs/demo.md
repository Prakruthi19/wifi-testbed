# Live demo

One command, six parts, about five minutes with talking. Run it inside the Ubuntu VM:

```bash
cd ~/wifi-testbed
sudo lab/demo.sh                 # pauses before each part (press Enter)
sudo DEMO_PAUSE=0 lab/demo.sh    # no pauses, e.g. to record a backup video
```

| Part | Shows | Tests |
|---|---|---|
| 1 | the lab: 4 emulated radios, AP + 3 clients in namespaces, software versions | none |
| 2 | a good join and a wrong password, plus the classifier's verdict from the pcap | `baseline_success`, `wrong_passphrase_wpa2` |
| 3 | the two failures the first real run found (issues #4, #5), now passing | `mac_blocked`, `dhcp_server_down` |
| 4 | iperf3 uplink/downlink after a full join | `test_throughput` (WPA2) |
| 5 | smart-home device after a Wi-Fi password change | `test_password_change` |
| 6 | the evidence: per-test pcap + logs, a drafted bug report, HTML reports | none |

Each part writes `reports/demo-<part>.html`. Open them as your normal user (`xdg-open`), not
root. If a part fails live, the demo still works: open the failed test's `classification.json`
and pcap and locate the stage, which is the job itself.

Before the interview, record one full run (`DEMO_PAUSE=0`) as a backup in case the VM or
screen share misbehaves.
