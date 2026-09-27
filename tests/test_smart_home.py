"""Smart-home device behaviours: what a plug or camera goes through after it is set up.

- the router reboots: the device must come back on its own, without a person
- the owner changes the Wi-Fi password: the device's old password must fail cleanly, at the
  4-way handshake, and the device must join once it has the new one
- a 2.4 GHz-only device (most cheap IoT radios) meets a 5 GHz-only network: it never picks it

client1 plays the device. Stage expectations are hypotheses until confirmed from captures,
the same as tests/test_failures.py.
"""

from __future__ import annotations

import time

import pytest

from classifier.classify_join import classify_pcap
from testbed.client import supplicant_stage
from testbed.matrix import ApConfig
from testbed.util import wait_for

pytestmark = [pytest.mark.lab, pytest.mark.smarthome]

SSID = "lab-home"
PASS = "labpassword123"
NEW_PASS = "newpassword456"
RECOVERY_TIMEOUT_S = 45
# 2.4 GHz channels 1-11 in MHz, the only band a typical IoT radio has.
FREQ_2G = " ".join(str(2407 + 5 * ch) for ch in range(1, 12))


def device_network(psk: str, freq_list: str | None = None) -> dict:
    net = {"key_mgmt": "WPA-PSK", "ieee80211w": 1, "psk": psk}
    if freq_list:
        net["freq_list"] = freq_list
    return net


@pytest.fixture
def device(clients):
    client = clients["client1"]
    yield client
    client.disconnect()


def test_recovers_after_router_reboot(device, hostap, dnsmasq, inventory, artifacts, capture,
                                      record_property):
    params = ApConfig("wpa2", 1, 6, ssid=SSID, passphrase=PASS).template_params()
    gw = inventory.lab["gateway"]
    hostap.ensure(**params)
    first = device.join(SSID, device_network(PASS), gateway=gw, artifacts=artifacts)
    assert first.passed, f"initial join failed at {first.failed_stage}"

    hostap.stop()  # the "reboot": the AP disappears
    assert wait_for(lambda: device.wpa_status().get("wpa_state") != "COMPLETED", timeout=15), \
        "device still reports COMPLETED with the AP down"
    start = time.monotonic()
    hostap.start(**params)
    back = wait_for(lambda: device.wpa_status().get("wpa_state") == "COMPLETED" and device.ping(gw),
                    timeout=RECOVERY_TIMEOUT_S, interval=0.5)
    recovery_s = round(time.monotonic() - start, 2)
    record_property("recovery_s", recovery_s)
    assert back, f"device did not rejoin and reach the gateway within {RECOVERY_TIMEOUT_S}s"


def test_password_change(device, hostap, dnsmasq, inventory, artifacts, capture,
                         record_property):
    old = ApConfig("wpa2", 1, 6, ssid=SSID, passphrase=PASS).template_params()
    new = ApConfig("wpa2", 1, 6, ssid=SSID, passphrase=NEW_PASS).template_params()
    gw = inventory.lab["gateway"]
    hostap.ensure(**old)
    first = device.join(SSID, device_network(PASS), gateway=gw, artifacts=artifacts)
    assert first.passed, f"initial join failed at {first.failed_stage}"

    log = device.workdir / f"wpa_supplicant-{device.name}.log"
    seen = len(log.read_text(errors="replace"))
    hostap.start(**new)  # owner changes the password; the device still has the old one
    rejoined = wait_for(lambda: device.wpa_status().get("wpa_state") == "COMPLETED", timeout=20,
                        interval=0.5)
    after = log.read_text(errors="replace")[seen:]
    (artifacts / "supplicant-after-change.log").write_text(after)
    stage = supplicant_stage(after)
    record_property("old_password_stage", stage)
    assert not rejoined, "device joined with the old password after the change"
    assert stage == "key_exchange", f"old password failed at {stage!r}, expected key_exchange"

    again = device.join(SSID, device_network(NEW_PASS), gateway=gw,
                        artifacts=artifacts / "new-password")
    assert again.passed, f"join with the new password failed at {again.failed_stage}"


@pytest.mark.parametrize("channel,expected", [(6, "success"), (36, "network_selection")],
                         ids=["2.4GHz-ap", "5GHz-ap"])
def test_2g_only_device(channel, expected, device, hostap, dnsmasq, inventory, artifacts,
                        capture, record_property):
    hostap.ensure(**ApConfig("wpa2", 1, channel, ssid=SSID, passphrase=PASS).template_params())
    try:
        join = device.join(SSID, device_network(PASS, FREQ_2G), gateway=inventory.lab["gateway"],
                           artifacts=artifacts, assoc_timeout=12)
    finally:
        device.disconnect()
        pcap = capture.stop()
    result = classify_pcap(str(pcap), sta=device.mac, wpa_pwd=f"{PASS}:{SSID}")
    record_property("harness_stage", join.failed_stage or "success")
    record_property("classified_stage", result.stage)
    assert (join.failed_stage or "success") == expected, join
    assert result.stage == expected, f"classifier said {result.stage!r} ({result.summary})"
