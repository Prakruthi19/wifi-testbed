"""Range vs rate: step an attenuator up and record signal, link rate and throughput at each step.

DESIGNED, NOT RUN: needs real radios (a USB Wi-Fi adapter moved into ns-client1 in place of sta1,
a real AP), a programmable attenuator between them, and shielded enclosures. Runs only with
--attenuator http://<ip>. The emulated lab has no RF, so this is skipped there.
"""

from __future__ import annotations

import json

import pytest

from testbed.attenuator import HttpAttenuator, rvr_steps
from testbed.matrix import CLIENT_PROFILES, ApConfig

pytestmark = [pytest.mark.lab, pytest.mark.rf]

# The link should survive at least this much added loss before dropping (a lab-chosen baseline).
MIN_DB_CONNECTED = 30
AP = ApConfig("wpa2", 1, 36, ssid="lab-rvr", passphrase="labpassword123")


@pytest.fixture
def attenuator(request):
    url = request.config.getoption("--attenuator")
    if not url:
        pytest.skip("pass --attenuator http://<ip> (real RF setup only)")
    att = HttpAttenuator(url)
    att.set(0)
    yield att
    att.set(0)


def test_range_vs_rate(attenuator, hostap, dnsmasq, clients, inventory, artifacts,
                       record_property):
    client = clients["client1"]
    gw = inventory.lab["gateway"]
    hostap.ensure(**AP.template_params())
    join = client.join(AP.ssid, CLIENT_PROFILES["wpa3-capable"].network_for(AP), gateway=gw,
                       artifacts=artifacts)
    assert join.passed, f"join at 0 dB failed at {join.failed_stage}"
    rows = []
    try:
        for db in rvr_steps():
            attenuator.set(db)
            sig = client.signal_poll()
            connected = client.wpa_status().get("wpa_state") == "COMPLETED"
            perf = client.iperf(gw, seconds=5) if connected else None
            rows.append({"db": db, "connected": connected, "rssi_dbm": sig.get("rssi_dbm"),
                         "link_mbps": sig.get("link_mbps"),
                         "tcp_mbps": perf.mbps if perf else 0.0})
            if not connected:
                break
    finally:
        client.disconnect()
        (artifacts / "rvr.json").write_text(json.dumps(rows, indent=2))
    record_property("rvr", rows)
    last_ok = max((r["db"] for r in rows if r["connected"]), default=-1)
    assert last_ok >= MIN_DB_CONNECTED, f"link dropped after {last_ok} dB (< {MIN_DB_CONNECTED})"
