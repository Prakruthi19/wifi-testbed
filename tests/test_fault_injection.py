"""Fault injection: break the lab in a controlled way while a client is connected, then check the
harness detects it, the capture shows it, and the client recovers (or fails at the right stage).

Faults: the AP kicks the client (deauth), hostapd crashes (SIGKILL) and is restarted, the
client's wpa_supplicant is stopped or crashes and restarts, the client's link drops for a few
seconds, and the AP changes security under a WPA2-only client.
Other faults live elsewhere: AP restart and password change in test_smart_home.py, DHCP and DNS
off in test_failures.py.
"""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

import pytest

from classifier.classify_join import link_events, read_frames
from testbed.client import supplicant_stage
from testbed.matrix import CLIENT_PROFILES, ApConfig
from testbed.util import wait_for

pytestmark = [pytest.mark.lab, pytest.mark.faults]

SSID = "lab-fault"
PASS = "labpassword123"
RECOVERY_TIMEOUT_S = 30
WPA2 = ApConfig("wpa2", 1, 6, ssid=SSID, passphrase=PASS)


@pytest.fixture
def connected(clients, hostap, dnsmasq, inventory, artifacts):
    """client1 joined to a WPA2 AP; yields (client, gateway)."""
    client = clients["client1"]
    gw = inventory.lab["gateway"]
    hostap.ensure(**WPA2.template_params())
    join = client.join(SSID, CLIENT_PROFILES["wpa3-capable"].network_for(WPA2), gateway=gw,
                       artifacts=artifacts)
    assert join.passed, f"setup join failed at {join.failed_stage}"
    yield client, gw
    client.disconnect()


def recovered(client, gw) -> float | None:
    """Seconds until the client is COMPLETED again and can ping the gateway, else None."""
    start = time.monotonic()
    ok = wait_for(lambda: client.wpa_status().get("wpa_state") == "COMPLETED" and client.ping(gw, 1),
                  timeout=RECOVERY_TIMEOUT_S, interval=0.5)
    return round(time.monotonic() - start, 2) if ok else None


def capture_events(capture, client, artifacts) -> dict:
    pcap = capture.stop()
    ev = link_events(read_frames(str(pcap), f"{PASS}:{SSID}"), client.mac)
    (artifacts / "link-events.json").write_text(json.dumps(ev, indent=2))
    return ev


def test_ap_kicks_client(connected, hostap, capture, artifacts, record_property):
    client, gw = connected
    hostap.deauthenticate(client.mac)
    seconds = recovered(client, gw)
    ev = capture_events(capture, client, artifacts)
    record_property("recovery_s", seconds)
    record_property("disconnects", ev["disconnects"])
    assert any(who == "ap" and kind == "deauth" for _, kind, who, _ in ev["disconnects"]), \
        f"no Deauthentication from the AP in the capture: {ev}"
    assert seconds is not None, f"client did not come back within {RECOVERY_TIMEOUT_S}s"


@pytest.mark.parametrize("sig", ["TERM", "KILL"], ids=["clean-stop", "crash"])
def test_supplicant_restart(sig, connected, capture, artifacts, record_property):
    client, gw = connected
    client.sh("pkill", f"-{sig}", "-f", f"wpa_supplicant.*-i {client.iface}", check=False)
    assert wait_for(lambda: not client.wpa_status(), timeout=5), "wpa_supplicant still running"
    start = time.monotonic()
    connected_again, log = client.associate(SSID, **CLIENT_PROFILES["wpa3-capable"].network_for(WPA2))
    record_property("rejoin_s", round(time.monotonic() - start, 2))
    ev = capture_events(capture, client, artifacts)
    record_property("disconnects", ev["disconnects"])
    assert connected_again, f"no rejoin after restart; stage {supplicant_stage(log.read_text())}"
    said_goodbye = any(who == "client" for _, _, who, _ in ev["disconnects"])
    record_property("client_said_goodbye", said_goodbye)
    if sig == "TERM":
        # A cleanly stopped supplicant says goodbye: Deauthentication from the client, reason 3.
        assert said_goodbye, f"no Deauthentication/Disassociation from the client: {ev}"
    # A crash (KILL) may leave no goodbye; the AP only learns when the client re-authenticates.


def test_ap_crash(connected, hostap, artifacts, record_property):
    """hostapd dies without cleanup (SIGKILL); the harness restarts it and the client must return."""
    client, gw = connected
    params = dict(hostap.current)
    pid = int(hostap.pid_file.read_text().strip())
    os.kill(pid, signal.SIGKILL)
    assert wait_for(lambda: not Path(f"/proc/{pid}").exists(), timeout=5), "hostapd survived SIGKILL"
    # Whether the client notices depends on whether the kernel keeps beaconing for a dead
    # hostapd; record it rather than guess. The requirement is recovery after the restart.
    noticed = wait_for(lambda: client.wpa_status().get("wpa_state") != "COMPLETED", timeout=20)
    record_property("client_noticed_ap_death", bool(noticed))
    hostap.start(**params)
    seconds = recovered(client, gw)
    record_property("recovery_s", seconds)
    assert seconds is not None, f"client did not come back within {RECOVERY_TIMEOUT_S}s of restart"


def test_link_interruption(connected, artifacts, record_property):
    client, gw = connected
    client.sh("ip", "link", "set", client.iface, "down")
    time.sleep(3)
    client.sh("ip", "link", "set", client.iface, "up")
    seconds = recovered(client, gw)
    record_property("recovery_s", seconds)
    assert seconds is not None, f"client did not recover within {RECOVERY_TIMEOUT_S}s of link up"


def test_security_change_blocks_wpa2_only_client(clients, hostap, dnsmasq, inventory, artifacts,
                                                 record_property):
    """AP moves from WPA2/WPA3 transition to WPA3-only; a WPA2-only client must not rejoin."""
    client = clients["client2"]
    transition = ApConfig("transition", 1, 6, ssid=SSID, passphrase=PASS)
    wpa3_only = ApConfig("wpa3", 2, 6, ssid=SSID, passphrase=PASS)
    profile = CLIENT_PROFILES["wpa2-only"]
    hostap.ensure(**transition.template_params())
    try:
        join = client.join(SSID, profile.network_for(transition), gateway=inventory.lab["gateway"],
                           artifacts=artifacts)
        assert join.passed, f"WPA2-only client should join a transition AP: {join}"
        log = client.workdir / f"wpa_supplicant-{client.name}.log"
        seen = len(log.read_text(errors="replace"))
        hostap.start(**wpa3_only.template_params())
        rejoined = wait_for(lambda: client.wpa_status().get("wpa_state") == "COMPLETED",
                            timeout=20, interval=0.5)
        after = log.read_text(errors="replace")[seen:]
    finally:
        client.disconnect()
    (artifacts / "supplicant-after-change.log").write_text(after)
    stage = supplicant_stage(after)
    record_property("stage_after_change", stage)
    assert not rejoined, "WPA2-only client rejoined a WPA3-only AP"
    assert stage == "network_selection", f"expected network_selection after the change, got {stage}"
