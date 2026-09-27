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
