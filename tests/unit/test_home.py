"""Home network: device profiles, expected interop results, troubleshooting diagnosis, scan
parsing, config rendering. No lab needed."""

from __future__ import annotations

from pathlib import Path

import pytest

from testbed import inventory
from testbed.home import (FREQ_2G, ScanEntry, channel_freq, device_profiles, diagnose,
                          expected_home, home_ap, in_parallel, interop_plan, parse_scan_results,
                          small_pool)
from testbed.util import render

HOME = inventory.load().home
DEV = {d.name: d for d in device_profiles(HOME)}
SSID, PASS = HOME["ssid"], HOME["passphrase"]
MAC = "02:00:00:00:04:00"


def ap(security="transition", channel=6):
    return home_ap(security, channel, SSID, PASS)


def seen(ssid=SSID, freq=2437):
    return [ScanEntry("02:00:00:00:00:00", freq, -30, "[WPA2-PSK-CCMP][ESS]", ssid)]


def test_inventory_home_layout():
    assert [a["iface"] for a in HOME["access_points"]] == ["ap0", "ap1", "ap2"]
    assert [d["iface"] for d in HOME["devices"]] == [f"sta{i}" for i in range(1, 6)]
    assert set(DEV) == {"phone", "laptop", "camera", "plug", "speaker"}


def test_channel_freq():
    assert (channel_freq(1), channel_freq(6), channel_freq(11), channel_freq(36)) == (2412, 2437, 2462, 5180)


def test_2g_only_devices_get_freq_list():
    assert DEV["plug"].network_for(ap())["freq_list"] == FREQ_2G
    assert "freq_list" not in DEV["phone"].network_for(ap())


def test_network_for_wrong_password_and_open():
    assert DEV["plug"].network_for(ap(), "oldpassword999")["psk"] == "oldpassword999"
    assert DEV["plug"].network_for(ap())["psk"] == PASS
    assert DEV["plug"].network_for(ap("open"), "x")["psk"] is None


def test_home_ap_uses_compliant_pmf():
    assert (ap("wpa2").pmf, ap("wpa3").pmf, ap("transition").pmf) == (1, 2, 1)


@pytest.mark.parametrize("security,channel,device,outcome", [
    ("transition", 6, "camera", "pass"),     # mixed mode exists for old devices
    ("wpa3", 6, "camera", "fail"),           # WPA2-only camera vs WPA3-only router
    ("wpa3", 6, "speaker", "pass"),
    ("transition", 36, "plug", "fail"),      # 2.4 GHz-only plug vs 5 GHz network
    ("transition", 36, "laptop", "pass"),
])
def test_expected_home(security, channel, device, outcome):
    exp = expected_home(ap(security, channel), DEV[device])
    assert exp.outcome == outcome
    if outcome == "fail":
        assert exp.stage == "network_selection"


def test_interop_plan_lists_every_device():
    plan = interop_plan(HOME)
    assert plan.splitlines()[0].count("|") == len(DEV) + 2
    assert "fails (network_selection)" in plan


def test_parse_scan_results():
    text = ("bssid / frequency / signal level / flags / ssid\n"
            "02:00:00:00:00:00\t2437\t-30\t[WPA2-PSK+SAE-CCMP][ESS]\tlab-home\n"
            "02:00:00:00:05:00\t5180\t-30\t[WPA2-PSK-CCMP][ESS]\t\n")
    got = parse_scan_results(text)
    assert [(e.freq, e.ssid) for e in got] == [(2437, "lab-home"), (5180, "")]


@pytest.mark.parametrize("stage,device,router,scan,log,cause", [
    ("network_selection", "plug", ap("transition", 36), [], "", "band"),
    ("network_selection", "camera", ap("wpa3"), seen(), "", "security"),
    ("network_selection", "speaker", ap(), seen(), "", "blocked"),
    ("authentication", "speaker", ap(), seen(), "", "blocked"),
    ("network_selection", "phone", ap(), [], "", "not_heard"),
    ("key_exchange", "plug", ap(), seen(), "", "wrong_password"),
    ("dhcp", "phone", ap(), seen(), f"DHCPDISCOVER(br-home) {MAC} no address available", "pool_full"),
    ("dhcp", "phone", ap(), seen(), "", "dhcp_down"),
    ("dns", "laptop", ap(), seen(), "", "dns"),
    ("ping", "laptop", ap(), seen(), "", "no_route"),
])
def test_diagnose(stage, device, router, scan, log, cause):
    d = diagnose(stage, DEV[device], router, SSID, scan, log, MAC)
    assert d.cause == cause and d.problem and d.fix


def test_diagnose_pool_full_only_for_this_device():
    other = "DHCPDISCOVER(br-home) 02:00:00:00:09:00 no address available"
    assert diagnose("dhcp", DEV["phone"], ap(), SSID, seen(), other, MAC).cause == "dhcp_down"


def test_diagnose_success_is_none():
    assert diagnose(None, DEV["phone"], ap(), SSID, seen()) is None
    assert diagnose("success", DEV["phone"], ap(), SSID, seen()) is None


def test_small_pool():
    assert small_pool("192.168.50.100", 2) == ("192.168.50.100", "192.168.50.101")


def test_in_parallel_runs_together():
    import threading
    import time

    barrier = threading.Barrier(3, timeout=2)  # deadlocks unless all three run at once

    def work(name, n):
        barrier.wait()
        time.sleep(0.01)
        return n * 2

    assert in_parallel(work, {"a": 1, "b": 2, "c": 3}) == {"a": 2, "b": 4, "c": 6}
    assert in_parallel(work, {}) == {}


def test_ap_template_bridge_line():
    params = {**ap().template_params(), "iface": "ap1", "ctrl_dir": "/run/x", "country_code": "US",
              "deny_mac_file": "/tmp/deny"}
    assert "bridge=br-home" in render("hostapd/ap.conf.j2", bridge="br-home", **params)
    assert "bridge=" not in render("hostapd/ap.conf.j2", **params)


def test_setup_lab_home_profile_radio_count():
    text = (Path(__file__).resolve().parents[2] / "lab" / "setup_lab.sh").read_text()
    assert "HOMENET" in text and "STAS=5; EXTRA_APS=2" in text
