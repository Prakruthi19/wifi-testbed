"""802.11k/v helpers and the mDNS encoder/decoder (no lab needed)."""

import pytest

from testbed import mdns
from testbed.steering import (btm_candidate, neighbor_element, op_class, parse_btm_responses,
                              parse_neighbor_reports)
from testbed.util import render


def test_op_class():
    assert op_class(1) == op_class(6) == op_class(11) == 81
    assert op_class(36) == 115
    assert op_class(149) == 125
    with pytest.raises(ValueError):
        op_class(14)


def test_neighbor_element_and_candidate():
    # BSSID, 4 bytes of BSSID info, op class 81 (0x51), channel 1, PHY type 7 (HT)
    assert neighbor_element("02:00:00:00:05:00", 1) == "020000000500" + "00000000" + "510107"
    assert btm_candidate("02:00:00:00:05:00", 11) == "02:00:00:00:05:00,0x0000,81,11,7,0301ff"


def test_parse_neighbor_reports():
    log = ("1790.1: sta1: RRM-NEIGHBOR-REP-RECEIVED bssid=02:00:00:00:05:00 info=0x0 op_class=81 "
           "chan=1 phy_type=7\n"
           "1790.1: sta1: RRM-NEIGHBOR-REP-RECEIVED bssid=02:00:00:00:06:00 info=0x0 op_class=81 "
           "chan=11 phy_type=7\n")
    got = parse_neighbor_reports(log)
    assert [r["bssid"] for r in got] == ["02:00:00:00:05:00", "02:00:00:00:06:00"]
    assert got[1]["chan"] == 11 and got[0]["info"] == 0


def test_parse_btm_responses():
    log = ("1790.2: BSS-TM-RESP 02:00:00:00:01:00 dialog_token=1 status_code=0 "
           "bss_termination_delay=0 target_bssid=02:00:00:00:05:00\n"
           "1790.3: BSS-TM-RESP 02:00:00:00:02:00 dialog_token=1 status_code=7 "
           "bss_termination_delay=0\n")
    phone = parse_btm_responses(log, "02:00:00:00:01:00")
    assert phone == [{"sta": "02:00:00:00:01:00", "dialog_token": 1, "status_code": 0,
                      "bss_termination_delay": 0, "target_bssid": "02:00:00:00:05:00"}]
    assert parse_btm_responses(log)[1]["status_code"] == 7


def test_ap_template_features():
    base = dict(iface="ap0", ctrl_dir="/run/x", country_code="US", deny_mac_file="/x", ssid="lab-home",
                hw_mode="g", channel=6, key_mgmt="WPA-PSK SAE", pmf=1, passphrase="p" * 10,
                sae_password=None, deny_macs=[], bridge="br-home")
    plain = render("hostapd/ap.conf.j2", **base)
    assert "rrm_neighbor_report" not in plain and "ap_isolate" not in plain
    full = render("hostapd/ap.conf.j2", rrm=True, bss_transition=True, ap_isolate=True, **base)
    for line in ("rrm_neighbor_report=1", "bss_transition=1", "ap_isolate=1"):
        assert line in full.splitlines()


def test_mdns_query_roundtrip():
    is_response, questions, records = mdns.parse_message(mdns.build_query(mdns.CAST))
    assert not is_response and questions == [(mdns.CAST, mdns.TYPE_PTR)] and records == []


def test_mdns_response_roundtrip():
    full = f"Living room speaker.{mdns.CAST}"
    answer = mdns.build_response(
        [mdns.Record(mdns.CAST, mdns.TYPE_PTR, 120, full)],
        [mdns.Record(full, mdns.TYPE_SRV, 120, (0, 0, 8009, "speaker.local")),
         mdns.Record("speaker.local", mdns.TYPE_A, 120, "192.168.50.20")])
    is_response, _q, records = mdns.parse_message(answer)
    assert is_response
    found = mdns.found_from(records, mdns.CAST, "192.168.50.20")
    assert len(found) == 1
    assert (found[0].instance, found[0].host, found[0].port, found[0].address) == \
        (full, "speaker.local", 8009, "192.168.50.20")


def test_mdns_compressed_name():
    # Real responders compress names: a pointer (0xC0 0x0C) back to the question's name.
    query = mdns.build_query("speaker.local", mdns.TYPE_A)
    msg = bytearray(query)
    msg[2:4] = b"\x84\x00"          # a response
    msg[6:8] = b"\x00\x01"          # one answer
    msg += b"\xc0\x0c" + b"\x00\x01\x80\x01" + b"\x00\x00\x00\x78" + b"\x00\x04" + bytes([192, 168, 50, 20])
    _r, _q, records = mdns.parse_message(bytes(msg))
    assert records[0].name == "speaker.local" and records[0].data == "192.168.50.20"
