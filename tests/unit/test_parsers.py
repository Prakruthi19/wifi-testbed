from testbed.android import parse_wifi_connected, parse_wifi_enabled, parse_wifi_info
from testbed.client import JoinResult, assoc_time_ms, lost_after_connect, summarize, supplicant_stage
from testbed.report import cell_state, matrix_html

CONNECTED_LOG = """\
1700000000.100000: sta1: SME: Trying to authenticate with 02:00:00:00:00:00 (SSID='lab' freq=2437 MHz)
1700000000.110000: sta1: Trying to associate with 02:00:00:00:00:00 (SSID='lab' freq=2437 MHz)
1700000000.120000: sta1: Associated with 02:00:00:00:00:00
1700000000.145500: sta1: CTRL-EVENT-CONNECTED - Connection to 02:00:00:00:00:00 completed [id=0 id_str=]
"""


def test_assoc_time_and_success():
    assert assoc_time_ms(CONNECTED_LOG) == 45.5
    assert supplicant_stage(CONNECTED_LOG) is None


def test_supplicant_stage_inference():
    lines = CONNECTED_LOG.splitlines()
    assert supplicant_stage("1.0: sta1: scanning\n") == "network_selection"
    assert supplicant_stage(lines[0]) == "authentication"
    assert supplicant_stage("\n".join(lines[:2])) == "association"
    assert supplicant_stage("\n".join(lines[:3])) == "key_exchange"
    assert supplicant_stage("\n".join(lines[:3]) +
                            "\n1.2: sta1: WPA: 4-Way Handshake failed - pre-shared key may be incorrect") \
        == "key_exchange"
    assert supplicant_stage(lines[0] + "\n1.2: sta1: CTRL-EVENT-AUTH-REJECT 02:00 status_code=1") \
        == "authentication"


def test_summarize():
    rs = [JoinResult(True, assoc_ms=40), JoinResult(True, assoc_ms=60),
          JoinResult(False, failed_stage="dhcp")]
    s = summarize(rs)
    assert s["pass_rate"] == 2 / 3 and s["median_join_ms"] == 50 and s["failed_stages"] == ["dhcp"]


DUMPSYS = """\
WifiClientModeImpl:
 mWifiInfo SSID: "AndroidWifi", BSSID: 00:13:10:85:fe:01, MAC: 02:15:b2:00:00:00, IP: /10.0.2.16, \
Security type: 0, Supplicant state: COMPLETED, Wi-Fi standard: 4, RSSI: -50, Link speed: 866Mbps, \
Tx Link speed: 866Mbps, Rx Link speed: -1Mbps, Frequency: 5180MHz, Net ID: 0
"""

STATUS = """Wifi is enabled
Wifi scanning is always available
==== Primary ClientModeManager instance ====
Wifi is connected to "AndroidWifi"
WifiInfo: SSID: "AndroidWifi", BSSID: 00:13:10:85:fe:01, RSSI: -47, Link speed: 144Mbps
"""


def test_parse_dumpsys_wifi():
    info = parse_wifi_info(DUMPSYS)
    assert (info.ssid, info.rssi_dbm, info.link_speed_mbps) == ("AndroidWifi", -50, 866)


def test_parse_wifi_status():
    assert parse_wifi_connected(STATUS) == "AndroidWifi"
    assert parse_wifi_enabled(STATUS)
    assert parse_wifi_connected("Wifi is enabled\nWifi is not connected\n") is None
    assert parse_wifi_info(STATUS).rssi_dbm == -47


def test_matrix_cells():
    assert cell_state({"expected": "pass", "pass_rate": 1.0}) == "ok"
    assert cell_state({"expected": "fail", "pass_rate": 0.0}) == "ok"
    assert cell_state({"expected": "fail", "pass_rate": 1.0}) == "bug"
    assert cell_state({"expected": "pass", "pass_rate": 0.6}) == "flaky"
    assert cell_state({"expected": "noncompliant", "pass_rate": 1.0}) == "noncompliant"
    html = matrix_html([{"row": "WPA2", "col": "wpa2-only", "pass_rate": 1.0,
                         "median_join_ms": 42.0, "expected": "pass", "failed_stages": []}])
    assert "100%" in html and "42 ms" in html


def test_lost_after_connect():
    # Second -m home run (2026-09-29): connected, then the AP sent 4-way message 1 again.
    dropped = CONNECTED_LOG + ("1700000000.150000: sta1: State: COMPLETED -> 4WAY_HANDSHAKE\n"
                               "1700000000.150100: sta1: WPA: RX message 1 of 4-Way Handshake\n")
    assert lost_after_connect(dropped)
    assert not lost_after_connect(CONNECTED_LOG)
    assert not lost_after_connect("1.0: sta1: scanning\n")
