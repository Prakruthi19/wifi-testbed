"""Roaming: a connected client moves from one AP to another of the same network.

Two ways to roam, measured the same way:
  full  the client authenticates and runs the 4-way handshake again with the new AP.
  ft    802.11r Fast Transition: the keys for the new AP are prepared during the move, so the
        4-way handshake is skipped. This is what keeps calls from dropping on real networks.

For each: roam time (from the client log), ping loss during the move, the IP address is kept,
and the capture shows how it roamed (auth algorithm, and whether a 4-way handshake followed).
Needs `ROAM=1 sudo lab/setup_lab.sh` (adds a second AP radio, ap1).
"""

from __future__ import annotations

import json
import time

import pytest

from classifier.classify_join import read_frames, roam_summary
from testbed.client import assoc_time_ms
from testbed.network import iface_in_namespace

pytestmark = [pytest.mark.lab, pytest.mark.roam]

SSID, PASS = "lab-roam", "labpassword123"
AP_IFACES = ("ap0", "ap1")
PING_INTERVAL = 0.05


@pytest.fixture(scope="module")
def roam_lab(inventory, lab_workdir):
    # Other modules' single-AP hostapd/dnsmasq on ap0 are module-scoped, so they are already
    # stopped by the time this module starts.
    from testbed.roam import RoamLab

    if not iface_in_namespace("ap1", None):
        pytest.skip("ap1 missing: run ROAM=1 sudo lab/setup_lab.sh")
    lab = RoamLab(AP_IFACES, lab_workdir / "roam", inventory.lab, inventory.lab["country_code"])
    lab.up()
    yield lab
    lab.down()


@pytest.mark.parametrize("ft", [False, True], ids=["full", "ft"])
def test_roam(ft, roam_lab, clients, inventory, artifacts, attach, capture, record_property):
    client = clients["client1"]
    gw = inventory.lab["gateway"]
    roam_lab.stop_aps()
    source = roam_lab.start_ap(0, SSID, PASS, ft)
    network = {"key_mgmt": "FT-PSK WPA-PSK" if ft else "WPA-PSK", "ieee80211w": 1, "psk": PASS}
    try:
        # Join the first AP while it is the only one, so the starting point is known.
        join = client.join(SSID, network, gateway=gw, artifacts=artifacts)
        assert join.passed, f"join to the first AP failed at {join.failed_stage}"
        assert client.current_bssid() == source
        ip_before = client.ipv4()
        record_property("key_mgmt", client.wpa_status().get("key_mgmt"))

        target = roam_lab.start_ap(1, SSID, PASS, ft)
        assert client.scan_for(target), f"second AP {target} never showed up in a scan"
        live_log = client.workdir / f"wpa_supplicant-{client.name}.log"
        offset = live_log.stat().st_size
        ping = client.start_ping(gw, PING_INTERVAL)
        time.sleep(1)  # some pings before the move, so loss is measured around it
        start = time.monotonic()
        moved = client.roam(target)
        wall_ms = round((time.monotonic() - start) * 1000, 1)
        time.sleep(2)
        pings = client.stop_ping(ping)
        ip_after = client.ipv4()
        with live_log.open("rb") as fh:
            fh.seek(offset)
            roam_log = fh.read().decode(errors="replace")
        (artifacts / "roam.log").write_text(roam_log)
        attach(artifacts / "roam.log", "roam.log")
    finally:
        client.disconnect()

    frames = read_frames(str(capture.stop()), f"{PASS}:{SSID}")
    how = roam_summary(frames, client.mac, target)
    lost = pings.get("sent", 0) - pings.get("received", 0)
    result = {"moved": moved, "roam_ms_log": assoc_time_ms(roam_log), "roam_ms_wall": wall_ms,
              "pings": pings, "outage_ms_estimate": round(lost * PING_INTERVAL * 1000),
              "ip_before": ip_before, "ip_after": ip_after, "capture": how}
    (artifacts / "roam.json").write_text(json.dumps(result, indent=2))
    for k, v in result.items():
        record_property(k, v)

    assert moved, f"client still on {client.current_bssid()} after roam to {target}"
    assert ip_after == ip_before, f"IP changed during the roam: {ip_before} -> {ip_after}"
    if ft:
        assert how["auth_alg"] == "FT", f"expected an FT authentication, capture shows {how}"
        assert not how["eapol_msgs"], f"FT roam should skip the 4-way handshake: {how}"
    else:
        assert how["auth_alg"] == "Open System", f"capture shows {how}"
        assert 4 in how["eapol_msgs"], f"full roam should include a 4-way handshake: {how}"
