"""Module 4: Android client state handling on the emulator over ADB (host only: pytest -m android).

The emulator only joins its built-in AndroidWifi network, so these tests cover state handling,
not the security matrix. Thresholds are defined in docs/test-plan.md.
"""

from __future__ import annotations

import time

import pytest

from testbed.android import Adb, parse_wifi_info
from testbed.util import wait_for

pytestmark = pytest.mark.android

RECONNECT_TIMEOUT_S = 30
DEGRADED_PROBE_TIMEOUT_S = 20


@pytest.fixture(scope="session")
def adb(request):
    if not Adb.available():
        pytest.skip("adb not on PATH")
    a = Adb(serial=request.config.getoption("--android-serial"))
    if not a.devices():
        pytest.skip("no emulator/device attached")
    a.wait_boot()
    return a


@pytest.fixture
def ping_host(request):
    return request.config.getoption("--android-ping-host")


@pytest.fixture(autouse=True)
def evidence(request, adb, artifacts, attach):
    """Wi-Fi on before each test; ADB transcript always, logcat excerpt on failure."""
    adb.transcript.clear()
    adb.logcat_clear()
    adb.set_airplane_mode(False)
    adb.set_wifi_enabled(True)
    yield
    attach(adb.save_transcript(artifacts / "adb-transcript.txt"))
    if getattr(request.node, "call_failed", True):
        path = artifacts / "logcat-wifi.txt"
        path.write_text(adb.logcat_wifi())
        attach(path, "logcat (Wi-Fi/connectivity)")


def test_reconnect_after_toggle(adb, ping_host, record_property):
    assert adb.wait_connected(ping_host, timeout=RECONNECT_TIMEOUT_S) is not None, "not connected at start"
    adb.set_wifi_enabled(False)
    assert adb.connected_ssid() is None or not adb.wifi_enabled()
    adb.set_wifi_enabled(True)
    seconds = adb.wait_connected(ping_host, timeout=RECONNECT_TIMEOUT_S)
    record_property("reconnect_s", seconds)
    assert seconds is not None, f"no connection + ping within {RECONNECT_TIMEOUT_S}s of re-enable"


@pytest.mark.parametrize("wifi_before", [True, False], ids=["wifi-on", "wifi-off"])
def test_airplane_mode_round_trip(adb, wifi_before, ping_host):
    adb.set_wifi_enabled(wifi_before)
    adb.set_airplane_mode(True)
    assert adb.airplane_mode()
    adb.set_airplane_mode(False)
    assert not adb.airplane_mode()
    assert wait_for(lambda: adb.wifi_enabled() == wifi_before, timeout=15, interval=0.5), \
        f"Wi-Fi did not return to enabled={wifi_before}"
    if wifi_before:
        assert adb.wait_connected(ping_host, timeout=RECONNECT_TIMEOUT_S) is not None


def test_state_reporting(adb, ping_host, record_property):
    adb.wait_connected(ping_host, timeout=RECONNECT_TIMEOUT_S)
    info = parse_wifi_info(adb.dumpsys_wifi())
    assert info is not None, "no WifiInfo line with SSID/RSSI/Link speed in dumpsys wifi"
    record_property("wifi_info", info.__dict__)
    assert info.ssid and info.ssid != "<unknown ssid>"
    assert -100 <= info.rssi_dbm <= 0, f"RSSI out of range: {info.rssi_dbm}"
    assert info.link_speed_mbps > 0, f"link speed not positive: {info.link_speed_mbps}"


def test_degraded_network(adb, ping_host, record_property):
    adb.emu_network(delay="gprs", speed="edge")
    try:
        start = time.monotonic()
        ok = wait_for(lambda: adb.ping(ping_host, timeout_s=5), timeout=DEGRADED_PROBE_TIMEOUT_S,
                      interval=1)
        record_property("degraded_probe_s", round(time.monotonic() - start, 2))
        assert ok, f"connectivity probe failed within {DEGRADED_PROBE_TIMEOUT_S}s on gprs/edge"
    finally:
        adb.emu_network()
