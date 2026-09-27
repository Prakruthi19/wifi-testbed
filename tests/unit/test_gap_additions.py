"""Parsers and failure handling added for performance (iperf3), Android join-by-command, and the
DHCP-timeout fix. No lab or phone needed."""

from __future__ import annotations

import json
import subprocess

from testbed.android import parse_saved_networks, phone_join_stage
from testbed.client import WifiClient
from testbed.perf import parse_iperf_json


def test_parse_iperf_json():
    text = json.dumps({"end": {
        "sum_sent": {"seconds": 5.0, "bits_per_second": 812_500_000, "retransmits": 3},
        "sum_received": {"seconds": 5.01, "bits_per_second": 810_000_000}}})
    r = parse_iperf_json(text, "uplink")
    assert (r.direction, r.mbps, r.retransmits, r.error) == ("uplink", 810.0, 3, None)


def test_parse_iperf_json_errors():
    r = parse_iperf_json(json.dumps({"error": "unable to connect to server"}), "downlink")
    assert r.error == "unable to connect to server" and r.mbps == 0.0
    assert parse_iperf_json("", "uplink").error.startswith("not JSON")


LIST_NETWORKS = """\
Network Id      SSID                         Security type
0            HomeNet                      wpa2-psk
3            My Cafe WiFi                 open
"""


def test_parse_saved_networks():
    nets = parse_saved_networks(LIST_NETWORKS)
    assert [(n.network_id, n.ssid, n.security) for n in nets] == [
        (0, "HomeNet", "wpa2-psk"), (3, "My Cafe WiFi", "open")]


def test_phone_join_stage():
    wrong_psk = ("I wpa_supplicant: wlan0: WPA: 4-Way Handshake failed - pre-shared key may be "
                 "incorrect\nI wpa_supplicant: wlan0: CTRL-EVENT-SSID-TEMP-DISABLED id=1 "
                 "ssid=\"HomeNet\" auth_failures=1 duration=10 reason=WRONG_KEY")
    assert phone_join_stage(wrong_psk) == "key_exchange"
    assert phone_join_stage("wlan0: CTRL-EVENT-ASSOC-REJECT bssid=aa status_code=17") == "association"
    assert phone_join_stage("wlan0: SME: Trying to authenticate with aa\n"
                            "wlan0: CTRL-EVENT-SSID-TEMP-DISABLED reason=AUTH_FAILED") == "authentication"
    assert phone_join_stage("wlan0: CTRL-EVENT-CONNECTED - Connection to aa completed") is None
    assert phone_join_stage("wlan0: CTRL-EVENT-SCAN-RESULTS") == "network_selection"


def test_dhcp_timeout_means_no_lease(tmp_path, monkeypatch):
    """No DHCP server: dhclient outlives its timeout. That is a dhcp failure, not a crash."""
    client = WifiClient("client1", "sta1", "ns-client1", tmp_path, "US")
    (tmp_path / "dhclient.leases").write_text("lease { fixed-address 192.168.50.150; }\n")

    def fake_sh(*cmd, **kw):
        if cmd[0] == "dhclient":
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(client, "sh", fake_sh)
    ip, elapsed = client.dhcp(timeout=1)
    assert ip is None and elapsed >= 0
    assert not (tmp_path / "dhclient.leases").exists(), "stale lease was not cleared"


def test_mac_randomization_parsing():
    from testbed.android import is_randomized_mac, parse_wifi_mac

    text = ' mWifiInfo SSID: "AndroidWifi", BSSID: 00:13:10:85:fe:01, MAC: 02:15:B2:00:00:00, IP: /10.0.2.16'
    assert parse_wifi_mac(text) == "02:15:b2:00:00:00"
    assert is_randomized_mac("02:15:b2:00:00:00") and is_randomized_mac("da:a1:19:00:00:01")
    assert not is_randomized_mac("00:13:10:85:fe:01")


def test_parse_signal_poll():
    from testbed.client import parse_signal_poll

    text = "RSSI=-52\nLINKSPEED=866\nNOISE=9999\nFREQUENCY=5180\n"
    assert parse_signal_poll(text) == {"rssi_dbm": -52, "link_mbps": 866.0, "freq_mhz": 5180}
    assert parse_signal_poll("FAIL") == {}


def test_openwrt_uci_commands():
    from testbed.matrix import ApConfig
    from testbed.openwrt import OpenWrtAP

    cmds = OpenWrtAP("192.168.1.1").uci_commands(
        ApConfig("wpa3", 2, 36, ssid="lab wpa3", passphrase="labpassword123"))
    assert "uci set wireless.radio0.band=5g" in cmds
    assert "uci set wireless.radio0.channel=36" in cmds
    assert "uci set wireless.default_radio0.ssid='lab wpa3'" in cmds
    assert "uci set wireless.default_radio0.encryption=sae" in cmds
    assert "uci set wireless.default_radio0.ieee80211w=2" in cmds
    assert cmds[-2:] == ["uci commit wireless", "wifi reload"]
    open_cmds = OpenWrtAP("h").uci_commands(ApConfig("open", 0, 6, ssid="o", passphrase=None))
    assert "uci set wireless.default_radio0.encryption=none" in open_cmds
    assert not any(".key=" in c for c in open_cmds)


def test_attenuator(monkeypatch):
    import pytest

    from testbed.attenuator import AttenuatorError, HttpAttenuator, rvr_steps

    assert rvr_steps(0, 20, 5) == [0, 5, 10, 15, 20]
    att = HttpAttenuator("http://att")
    calls = []
    monkeypatch.setattr(att, "_get", lambda path: calls.append(path) or "1")
    att.set(30)
    assert calls == ["SETATT=30"]
    with pytest.raises(AttenuatorError):
        att.set(120)
    monkeypatch.setattr(att, "_get", lambda path: "0")
    with pytest.raises(AttenuatorError):
        att.set(10)


def test_bug_draft(tmp_path):
    from testbed.bug_draft import draft

    d = tmp_path / "test_induced_failure_mac_blocked_"
    d.mkdir()
    (d / "classification.json").write_text(json.dumps({
        "case": "mac_blocked", "expected": ["authentication"],
        "join": {"passed": False, "failed_stage": "network_selection"},
        "classifier": {"stage": "network_selection", "summary": "client never attempted auth",
                       "evidence": [{"no": 191, "kind": "probe_req", "src": "02:00:00:00:01:00",
                                     "dst": "ff:ff:ff:ff:ff:ff", "status": None, "reason": None}]}}))
    (d / "capture.pcap").write_bytes(b"")
    text = draft(d)
    assert text.startswith("# mac_blocked: classifier says network_selection, expected authentication")
    assert '-k "mac_blocked"' in text and "frame #191 probe_req" in text and "capture.pcap" in text


def test_parse_iperf_udp_json():
    from testbed.perf import parse_iperf_udp_json

    text = json.dumps({"end": {"sum": {"bits_per_second": 19_800_000, "jitter_ms": 0.0421,
                                       "lost_percent": 0.35}}})
    r = parse_iperf_udp_json(text, "uplink", 20)
    assert (r.mbps, r.jitter_ms, r.lost_percent, r.error) == (19.8, 0.042, 0.35, None)
    assert parse_iperf_udp_json('{"error": "boom"}', "uplink", 20).lost_percent == 100.0


def test_openwrt_htmode():
    from testbed.matrix import ApConfig
    from testbed.openwrt import OpenWrtAP

    ap = ApConfig("wpa2", 1, 6, ssid="s", passphrase="labpassword123")
    assert "uci set wireless.radio0.htmode=HT20" in OpenWrtAP("h").uci_commands(ap, "HT20")
    assert not any("htmode" in c for c in OpenWrtAP("h").uci_commands(ap))
