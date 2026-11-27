"""Packet capture page: the analysis (no tshark needed) and the capture job API (no lab needed)."""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

import pytest

from classifier.classify_join import Frame
from testbed.pcap_analysis import Packet, analyse

SAMPLE = Path(__file__).parent / "data" / "sample_capture.pcap"  # made up, see make_sample_capture.py
AP, STA = "02:00:00:00:03:00", "02:00:00:00:02:00"


def pkt(no, kind, src, dst, ftype=0, **kw) -> Packet:
    extra = {k: kw.pop(k) for k in ("ssid", "signal", "dhcp_ip") if k in kw}
    return Packet(Frame(no=no, time=100 + no / 10, kind=kind, src=src, dst=dst, bssid=AP, **kw), ftype=ftype, **extra)


def handshake_timeout() -> list[Packet]:
    return [
        pkt(1, "beacon", AP, "ff:ff:ff:ff:ff:ff", ssid="lab-wpa2", rsn=True, signal=-40),
        pkt(2, "auth", STA, AP, auth_alg=0, auth_seq=1, status=0),
        pkt(3, "auth", AP, STA, auth_alg=0, auth_seq=2, status=0),
        pkt(4, "assoc_req", STA, AP, ssid="lab-wpa2", rsn=True, signal=-67),
        pkt(5, "assoc_resp", AP, STA, status=0),
        pkt(6, "eapol", AP, STA, ftype=2, eapol_msg=1),
        pkt(7, "eapol", STA, AP, ftype=2, eapol_msg=2),
        pkt(8, "eapol", AP, STA, ftype=2, eapol_msg=3),
        pkt(9, "eapol", AP, STA, ftype=2, eapol_msg=3, retry=True),
        pkt(10, "deauth", AP, STA, reason=15),
        pkt(11, "control", None, AP, ftype=1),
    ]


def test_analysis_names_the_stage_and_the_reason():
    r = analyse(handshake_timeout())
    assert r["frames"] == 11 and r["by_type"] == {"management": 6, "control": 1, "data": 4, "other": 0}
    assert r["networks"] == [{"bssid": AP, "ssid": "lab-wpa2", "beacons": 1, "secured": True, "signal_dbm": -40}]
    [dev] = r["devices"]
    assert dev["mac"] == STA and dev["stage"] == "key_exchange" and dev["ssid"] == "lab-wpa2"
    assert dev["signal_dbm"] == -67  # from the frames the device sent, not the AP's
    [d] = r["disconnects"]
    assert (d["reason"], d["meaning"], d["sender"]) == (15, "4-way handshake timeout", "ap")
    [hs] = r["handshakes"]
    assert hs["messages"] == [1, 2, 3, 3] and not hs["complete"] and hs["retries"] == 1
    assert r["retries"] == 1
    assert all(e["kind"] not in ("beacon", "control") for e in r["events"])


def test_analysis_explains_encrypted_and_empty_captures():
    sealed = handshake_timeout()[:9] + [pkt(12, "data", STA, AP, ftype=2, protected=True)]
    sealed[7].frame.eapol_msg = 4  # a complete handshake, then encrypted data
    r = analyse(sealed)
    assert r["devices"][0]["stage"] == "undetermined"
    assert any("encrypted" in n for n in r["notes"])
    assert any("empty" in n for n in analyse([])["notes"])
    beacons_only = analyse(handshake_timeout()[:1])
    assert beacons_only["devices"] == [] and any("No client" in n for n in beacons_only["notes"])


def test_unknown_reason_code_is_said_plainly():
    r = analyse([pkt(1, "deauth", AP, STA, reason=99)])
    assert r["disconnects"][0]["meaning"] == "Reason code not in the common list"


needs_tshark = pytest.mark.skipif(shutil.which("tshark") is None, reason="tshark not installed")


@needs_tshark
def test_sample_pcap_end_to_end():
    pytest.importorskip("pyshark")
    from testbed.pcap_analysis import analyse_pcap

    r = analyse_pcap(str(SAMPLE))
    by_mac = {d["mac"]: d for d in r["devices"]}
    assert by_mac["02:00:00:00:01:00"]["stage"] == "success"
    assert by_mac["02:00:00:00:01:00"]["ip"] == "192.168.50.100"
    assert by_mac["02:00:00:00:01:00"]["dns_names"] == ["gw.lab"]
    assert by_mac[STA]["stage"] == "key_exchange"
    assert [d["reason"] for d in r["disconnects"]] == [15]
    assert {n["ssid"] for n in r["networks"]} == {"lab-open", "lab-wpa2"}
    assert [x["type"] for x in r["dhcp"]] == ["Discover", "Offer", "Request", "ACK"]


# -- API -----------------------------------------------------------------------------------------

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from testbed import api  # noqa: E402
from testbed.capturejobs import CaptureJobs  # noqa: E402

FAKE_RESULT = {"frames": 27, "devices": [{"mac": STA}], "disconnects": [{"reason": 15}]}


def fake_capture(iface, seconds, path):
    return [sys.executable, "-c", "import shutil,sys,time; time.sleep(float(sys.argv[3])); shutil.copy(sys.argv[1], sys.argv[2])",
            str(SAMPLE), str(path), str(seconds / 10)]


def fake_analyse(pcap, out, wpa_pwd):
    result = FAKE_RESULT | {"wpa": wpa_pwd}
    return [sys.executable, "-c", "import sys; open(sys.argv[1], 'w').write(sys.argv[2])", str(out), json.dumps(result)]


@pytest.fixture
def app(tmp_path):
    inv = tmp_path / "inventory.yaml"
    inv.write_text("aps:\n  - {name: ap-wpa2-2g, ssid: lab-wpa2, security: wpa2, channel: 6, passphrase: secret123}\n")
    caps = CaptureJobs(tmp_path / "reports" / "captures", capture_cmd=fake_capture, analyse_cmd=fake_analyse,
                       iface_exists=lambda name: True)
    return TestClient(api.create_app(tmp_path / "reports", inv, captures=caps), base_url="http://localhost"), caps


def wait_done(c, cid, timeout=10):
    """Poll like the page does, until the job ends."""
    end = time.monotonic() + timeout
    seen = set()
    while time.monotonic() < end:
        j = c.get(f"/api/captures/{cid}").json()
        seen.add(j["status"])
        if j["status"] in ("done", "failed"):
            return j, seen
        time.sleep(0.05)
    raise AssertionError("capture did not finish")


def test_live_capture_is_polled_until_done(app):
    c, _ = app
    r = c.post("/api/captures", json={"seconds": 3, "decrypt": "lab-wpa2"})
    assert r.status_code == 202 and r.json()["status"] == "capturing"
    cid = r.json()["id"]
    assert c.get("/api/captures/current").json()["capture"]["id"] == cid
    assert c.post("/api/captures", json={"seconds": 1}).status_code == 409  # one at a time
    job, seen = wait_done(c, cid)
    assert job["status"] == "done" and "capturing" in seen
    assert job["result"]["frames"] == 27
    assert job["result"]["wpa"] == "secret123:lab-wpa2"  # looked up on the server...
    assert "secret123" not in json.dumps({k: v for k, v in job.items() if k != "result"})  # ...never sent back
    assert c.get("/api/captures/current").json()["capture"] is None
    listed = c.get("/api/captures").json()[0]
    assert listed["id"] == cid and listed["devices"] == 1 and "result" not in listed
    f = c.get(f"/api/captures/{cid}/pcap")
    assert f.status_code == 200 and f.content == SAMPLE.read_bytes()


def test_capture_input_is_checked(app):
    c, caps = app
    assert c.post("/api/captures", json={"seconds": 0}).status_code == 422
    assert c.post("/api/captures", json={"seconds": 301}).status_code == 422
    assert c.post("/api/captures", json={"seconds": 5, "decrypt": "nope"}).status_code == 400
    caps.iface_exists = lambda name: False
    r = c.post("/api/captures", json={"seconds": 5})
    assert r.status_code == 409 and "setup_lab.sh" in r.json()["detail"]
    assert c.get("/api/captures/zzz").status_code == 404
    assert c.get("/api/captures/../x/pcap").status_code == 404


def test_networks_list_has_no_passwords(app):
    c, _ = app
    r = c.get("/api/captures/networks")
    assert r.json() == [{"ssid": "lab-wpa2", "security": "wpa2"}] and "secret123" not in r.text


def test_upload_is_analysed(app):
    c, _ = app
    assert c.post("/api/captures/upload?name=x.txt", content=b"hello world").status_code == 400
    r = c.post("/api/captures/upload?name=../../home.pcap", content=SAMPLE.read_bytes())
    assert r.status_code == 202 and r.json()["status"] == "analysing" and r.json()["filename"] == "home.pcap"
    job, _ = wait_done(c, r.json()["id"])
    assert job["status"] == "done" and job["source"] == "upload"


def test_failed_capture_says_why(tmp_path):
    caps = CaptureJobs(tmp_path / "captures", iface_exists=lambda n: True, capture_cmd=lambda i, s, p: [
        sys.executable, "-c", "import sys; sys.stderr.write(\"You don't have permission to capture on that device\"); sys.exit(2)"])
    c = TestClient(api.create_app(tmp_path, tmp_path / "none.yaml", captures=caps), base_url="http://localhost")
    job, _ = wait_done(c, c.post("/api/captures", json={"seconds": 1}).json()["id"])
    assert job["status"] == "failed" and "wireshark group" in job["error"]
