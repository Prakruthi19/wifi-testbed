"""Performance: iperf3 TCP throughput, uplink and downlink, after a full join.

The radios are emulated, so Mbps here reflects the software path (kernel, hostapd, CPU), not RF.
The floor below only catches a broken data path; the recorded numbers are a baseline to compare
runs against (a big drop between two builds is a regression worth a look).
"""

from __future__ import annotations

import json

import pytest

from testbed.matrix import CLIENT_PROFILES, ApConfig
from testbed.perf import VIRTUAL_NOTE, IperfServer

pytestmark = [pytest.mark.lab, pytest.mark.perf]

MIN_MBPS = 1.0
SECONDS = 5
# UDP at camera-like loads, highest first. The test RECORDS the highest rate that stays under
# MAX_LOSS_PERCENT (received Mbps, not the rate asked for) plus its jitter, and FAILS only when the
# data path is broken: no rate down to 2 Mbps gets through cleanly, or under 1 Mbps arrives.
# Why not pass/fail on speed, loss or jitter: in this emulated lab they measure the VM's CPU.
# 2026-09-29 VM runs, uplink asked 20 Mbps: 2 vCPU sent 2.81 / 4.06 Mbps; 4 vCPU sent 7.05 /
# 19.98 Mbps. Jitter across runs: 0.01, 36, 142 ms. Loss at 10 Mbps once beat loss at 20.
UDP_RATES_MBPS = (20, 10, 5, 2)
MIN_CLEAN_UDP_MBPS = 1
MAX_LOSS_PERCENT = 5.0
MAX_AVG_RTT_MS = 50.0

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
        {"measurement": VIRTUAL_NOTE, "ap": ap.label, "join": join.to_dict(),
         "iperf": result.to_dict()}, indent=2))
    attach(artifacts / "iperf.json")
    record_property("measurement", VIRTUAL_NOTE)
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
        tries, result = [], None
        for rate in UDP_RATES_MBPS:
            r = client.iperf_udp(lab["gateway"], mbps=rate, seconds=SECONDS,
                                 reverse=direction == "downlink")
            tries.append(r.to_dict())
            if r.error is None and r.lost_percent <= MAX_LOSS_PERCENT:
                result = r
                break
    finally:
        client.disconnect()

    clean_mbps = result.mbps if result else 0  # delivered, see MIN_CLEAN_UDP_MBPS
    (artifacts / "iperf-udp.json").write_text(json.dumps(
        {"measurement": VIRTUAL_NOTE, "ap": ap.label, "max_clean_mbps": clean_mbps, "tries": tries},
        indent=2))
    attach(artifacts / "iperf-udp.json")
    record_property("measurement", VIRTUAL_NOTE)
    record_property("max_clean_mbps", clean_mbps)
    record_property("tries", [(t["target_mbps"], t["sent_mbps"], t["mbps"], t["lost_percent"],
                               t["jitter_ms"]) for t in tries])

    assert result is not None and clean_mbps >= MIN_CLEAN_UDP_MBPS, \
        f"no rate down to {UDP_RATES_MBPS[-1]} Mbps delivered {MIN_CLEAN_UDP_MBPS}+ Mbps under " \
        f"{MAX_LOSS_PERCENT}% loss: " + ", ".join(
            f"asked {t['target_mbps']}, sent {t['sent_mbps']}, got {t['mbps']} Mbps, "
            f"{t['lost_percent']}% lost ({t['error']})"
            for t in tries)
    record_property("jitter_ms", result.jitter_ms)  # recorded, not judged: see UDP_RATES_MBPS


def test_latency(hostap, dnsmasq, clients, inventory, artifacts, attach, capture,
                 record_property):
    ap = APS[0]
    client = clients["client1"]
    lab = inventory.lab
    hostap.ensure(**ap.template_params())
    try:
        join = client.join(ap.ssid, CLIENT_PROFILES["wpa3-capable"].network_for(ap),
                           gateway=lab["gateway"], artifacts=artifacts)
        assert join.passed, f"join failed at {join.failed_stage}: {join}"
        stats = client.ping_stats(lab["gateway"], count=20)
    finally:
        client.disconnect()
    (artifacts / "ping.json").write_text(json.dumps({"measurement": VIRTUAL_NOTE, **stats}, indent=2))
    attach(artifacts / "ping.json")
    record_property("measurement", VIRTUAL_NOTE)
    for key, value in stats.items():
        record_property(key, value)
    assert stats.get("loss_percent") == 0.0, f"ping loss: {stats}"
    assert stats["rtt_avg_ms"] <= MAX_AVG_RTT_MS, f"average RTT {stats['rtt_avg_ms']} ms"
