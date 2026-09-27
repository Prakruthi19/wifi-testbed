"""Module 4: Android Wi-Fi over ADB, on the emulator or a real phone (host only: pytest -m android).

State-handling tests run anywhere. The join tests need --android-ssid (and --android-psk): the
phone joins that network by command, and the wrong-password test names the failed stage from the
phone's own wpa_supplicant lines in logcat. The emulator only sees its built-in AndroidWifi
network, so the wrong-password test needs a real phone on a secured network (e.g. home Wi-Fi).
Thresholds are defined in docs/test-plan.md.
"""

from __future__ import annotations

import time

import pytest

from testbed.android import (Adb, is_randomized_mac, parse_wifi_info, parse_wifi_mac,
                             phone_join_stage)
from testbed.util import wait_for

pytestmark = pytest.mark.android

RECONNECT_TIMEOUT_S = 30
JOIN_TIMEOUT_S = 30
WRONG_PASSWORD_WAIT_S = 20
# Same expectations as the lab's induced failures: WPA2 fails in the 4-way handshake,
# WPA3 (SAE) fails during authentication.
WRONG_PASSWORD_STAGE = {"wpa2": "key_exchange", "wpa3": "authentication"}
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
    adb.set_verbose_logging(True)
    adb.logcat_clear()
    adb.set_airplane_mode(False)
    adb.set_wifi_enabled(True)
    yield
    attach(adb.save_transcript(artifacts / "adb-transcript.txt"))
    if getattr(request.node, "call_failed", True):
        path = artifacts / "logcat-wifi.txt"
        path.write_text(adb.logcat_wifi())
        attach(path, "logcat (Wi-Fi/connectivity)")
        adb.open_wifi_settings()
        time.sleep(1)
        attach(adb.screenshot(artifacts / "wifi-settings.png"), "screenshot (Wi-Fi settings)")
        if request.config.getoption("--android-bugreport"):
            attach(adb.bugreport(artifacts / "bugreport.zip"), "adb bugreport")


@pytest.fixture
def target(request):
    """(ssid, security, psk) the phone joins by command; skips when --android-ssid is not set."""
    ssid = request.config.getoption("--android-ssid")
    if not ssid:
        pytest.skip("pass --android-ssid (and --android-psk) to run join tests")
    return ssid, request.config.getoption("--android-security"), \
        request.config.getoption("--android-psk")


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
    if not adb.is_emulator():
        pytest.skip("network shaping uses the emulator console (adb emu); not on a real phone")
    adb.emu_network(delay="gprs", speed="edge")
    try:
        start = time.monotonic()
        ok = wait_for(lambda: adb.ping(ping_host, timeout_s=5), timeout=DEGRADED_PROBE_TIMEOUT_S,
                      interval=1)
        record_property("degraded_probe_s", round(time.monotonic() - start, 2))
        assert ok, f"connectivity probe failed within {DEGRADED_PROBE_TIMEOUT_S}s on gprs/edge"
    finally:
        adb.emu_network()


def test_join_named_network(adb, target, ping_host, artifacts, record_property):
    ssid, security, psk = target
    adb.forget_network(ssid)
    try:
        start = time.monotonic()
        adb.connect_network(ssid, security, psk)
        joined = wait_for(lambda: adb.connected_ssid() == ssid and adb.ping(ping_host),
                          timeout=JOIN_TIMEOUT_S, interval=0.5)
        record_property("join_s", round(time.monotonic() - start, 2))
        logcat = adb.logcat_wifi()
        (artifacts / "logcat-join.txt").write_text(logcat)
        assert joined, (f"not connected to {ssid} with a ping within {JOIN_TIMEOUT_S}s; "
                        f"phone log says stage={phone_join_stage(logcat)}")
        assert ssid in [n.ssid.strip('"') for n in adb.list_networks()], "network was not saved"
    finally:
        adb.forget_network(ssid)
    assert ssid not in [n.ssid.strip('"') for n in adb.list_networks()], "forget-network left it saved"


def test_wrong_password_names_stage(adb, target, artifacts, record_property):
    ssid, security, _ = target
    if security not in WRONG_PASSWORD_STAGE:
        pytest.skip(f"no password to get wrong on a {security} network")
    adb.forget_network(ssid)
    try:
        adb.connect_network(ssid, security, "wrongpassword1")
        joined = wait_for(lambda: adb.connected_ssid() == ssid, timeout=WRONG_PASSWORD_WAIT_S,
                          interval=0.5)
        logcat = adb.logcat_wifi()
    finally:
        adb.forget_network(ssid)
    (artifacts / "logcat-wrong-password.txt").write_text(logcat)
    stage = phone_join_stage(logcat)
    record_property("phone_stage", stage)
    assert not joined, "phone joined with a wrong password"
    assert stage == WRONG_PASSWORD_STAGE[security], (
        f"phone log says {stage!r}, expected {WRONG_PASSWORD_STAGE[security]!r}; "
        f"see logcat-wrong-password.txt")


def test_mac_randomization(adb, ping_host, record_property):
    """The phone should use a randomized (locally administered) MAC on the network by default."""
    assert adb.wait_connected(ping_host, timeout=RECONNECT_TIMEOUT_S) is not None, "not connected"
    mac = parse_wifi_mac(adb.dumpsys_wifi())
    assert mac, "no MAC in the WifiInfo line of dumpsys wifi"
    record_property("wifi_mac", mac)
    record_property("randomized", is_randomized_mac(mac))
    assert is_randomized_mac(mac), (
        f"{mac} is a factory (globally unique) MAC; per-network randomization is off")
