"""Performance: iperf3 TCP throughput, uplink and downlink, after a full join.

The radios are emulated, so Mbps here reflects the software path (kernel, hostapd, CPU), not RF.
The floor below only catches a broken data path; the recorded numbers are a baseline to compare
runs against (a big drop between two builds is a regression worth a look).
"""

from __future__ import annotations

import json

import pytest

from testbed.matrix import CLIENT_PROFILES, ApConfig
from testbed.perf import IperfServer

pytestmark = [pytest.mark.lab, pytest.mark.perf]

MIN_MBPS = 1.0
SECONDS = 5
# UDP at a camera-like load. Smoke thresholds for an emulated link, not RF targets.
UDP_MBPS = 20
MAX_LOSS_PERCENT = 5.0
MAX_JITTER_MS = 30.0

APS = [
    ApConfig("wpa2", 1, 6, ssid="lab-perf", passphrase="labpassword123"),
    ApConfig("wpa3", 2, 36, ssid="lab-perf", passphrase="labpassword123"),
]


@pytest.fixture(scope="module")
def iperf_server(inventory, lab_workdir):
    server = IperfServer(inventory.lab["gateway"], lab_workdir / "iperf").start()
    yield server
    server.stop()


@pytest.mark.parametrize("ap", APS, ids=[f"{a.security}-ch{a.channel}" for a in APS])
@pytest.mark.parametrize("direction", ["uplink", "downlink"])
def test_throughput(ap, direction, hostap, dnsmasq, clients, inventory, iperf_server,
                    artifacts, attach, capture, record_property):
    client = clients["client1"]
    lab = inventory.lab
    hostap.ensure(**ap.template_params())
    try:
        join = client.join(ap.ssid, CLIENT_PROFILES["wpa3-capable"].network_for(ap),
                           gateway=lab["gateway"], artifacts=artifacts)
        assert join.passed, f"join failed at {join.failed_stage}: {join}"
        result = client.iperf(lab["gateway"], seconds=SECONDS, reverse=direction == "downlink")
    finally:
        client.disconnect()

    (artifacts / "iperf.json").write_text(json.dumps(
        {"ap": ap.label, "join": join.to_dict(), "iperf": result.to_dict()}, indent=2))
    attach(artifacts / "iperf.json")
    record_property("mbps", result.mbps)
    record_property("retransmits", result.retransmits)

    assert result.error is None, f"iperf3 error: {result.error}"
    assert result.mbps >= MIN_MBPS, f"{direction} {result.mbps} Mbps is below the {MIN_MBPS} floor"


@pytest.mark.parametrize("direction", ["uplink", "downlink"])
def test_udp_jitter_loss(direction, hostap, dnsmasq, clients, inventory, iperf_server,
                         artifacts, attach, capture, record_property):
    ap = APS[0]
    client = clients["client1"]
    lab = inventory.lab
    hostap.ensure(**ap.template_params())
    try:
        join = client.join(ap.ssid, CLIENT_PROFILES["wpa3-capable"].network_for(ap),
                           gateway=lab["gateway"], artifacts=artifacts)
        assert join.passed, f"join failed at {join.failed_stage}: {join}"
        result = client.iperf_udp(lab["gateway"], mbps=UDP_MBPS, seconds=SECONDS,
                                  reverse=direction == "downlink")
    finally:
        client.disconnect()

    (artifacts / "iperf-udp.json").write_text(json.dumps(
        {"ap": ap.label, "iperf_udp": result.to_dict()}, indent=2))
    attach(artifacts / "iperf-udp.json")
    record_property("jitter_ms", result.jitter_ms)
    record_property("lost_percent", result.lost_percent)

    assert result.error is None, f"iperf3 error: {result.error}"
    assert result.lost_percent <= MAX_LOSS_PERCENT, f"{result.lost_percent}% datagrams lost"
    assert result.jitter_ms <= MAX_JITTER_MS, f"jitter {result.jitter_ms} ms"
