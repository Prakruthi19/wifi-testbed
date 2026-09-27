"""802.1X stage, session-PMK extraction, and roam summaries. No lab needed."""

from __future__ import annotations

import pytest

from classifier.classify_join import Frame, classify, normalize_pmk, roam_summary
from testbed import eap
from testbed.client import STAGES, session_pmk, supplicant_stage
from testbed.util import render

from tests.unit.test_classifier import AP, STA, Seq

AP2 = "02:00:00:00:04:00"
PMK = "3a" * 32


def eap_login(seq: Seq, outcome: int | None, client_answers: bool = True) -> Seq:
    seq.add("eap", AP, STA, eap_code=1, eap_type=1)
    if client_answers:
        seq.add("eap", STA, AP, eap_code=2, eap_type=1)
        seq.add("eap", AP, STA, eap_code=1, eap_type=52)
        seq.add("eap", STA, AP, eap_code=2, eap_type=52)
    if outcome:
        seq.add("eap", AP, STA, eap_code=outcome)
    return seq


def enterprise(outcome, **kw):
    return eap_login(Seq().probe().open_auth().assoc(), outcome, **kw)


def test_eap_failure_is_eap_stage():
    r = classify(enterprise(4).frames)
    assert r.stage == "eap" and "EAP-Failure" in r.summary
    assert any("PWD" in n for n in r.notes)


def test_eap_never_finished():
    assert classify(enterprise(None).frames).stage == "eap"
    silent = classify(enterprise(None, client_answers=False).frames)
    assert silent.stage == "eap" and "never answered" in silent.summary


def test_eap_success_moves_on_to_handshake():
    r = classify(enterprise(3).handshake(upto=2).frames)
    assert r.stage == "key_exchange"
    r = classify(enterprise(3).handshake().dhcp(1, 2, 3, 5).dns().frames)
    assert r.stage == "success"


def test_eap_describe():
    f = Frame(no=1, time=0, kind="eap", src=AP, dst=STA, eap_code=1, eap_type=25)
    assert f.describe().endswith("Request PEAP")


def test_stage_order_has_eap_between_association_and_handshake():
    assert STAGES.index("association") < STAGES.index("eap") < STAGES.index("key_exchange")


# -- supplicant log --------------------------------------------------------------------------

LOG_EAP_FAIL = """\
1.000000: wlan0: SME: Trying to authenticate with 02:00:00:00:00:00 (SSID='lab-corp' freq=2437 MHz)
1.010000: wlan0: Trying to associate with 02:00:00:00:00:00 (SSID='lab-corp' freq=2437 MHz)
1.020000: wlan0: Associated with 02:00:00:00:00:00
1.030000: wlan0: CTRL-EVENT-EAP-STARTED EAP authentication started
1.100000: wlan0: CTRL-EVENT-EAP-FAILURE EAP authentication failed
"""


def test_supplicant_stage_eap():
    assert supplicant_stage(LOG_EAP_FAIL) == "eap"
    cert = LOG_EAP_FAIL.replace("CTRL-EVENT-EAP-FAILURE EAP authentication failed",
                                "CTRL-EVENT-EAP-TLS-CERT-ERROR reason=1 depth=0")
    assert supplicant_stage(cert) == "eap"
    unfinished = "\n".join(LOG_EAP_FAIL.splitlines()[:4])
    assert supplicant_stage(unfinished) == "eap"


def test_supplicant_stage_eap_success_then_handshake_failure():
    text = LOG_EAP_FAIL.replace("CTRL-EVENT-EAP-FAILURE EAP authentication failed",
                                "CTRL-EVENT-EAP-SUCCESS EAP authentication completed successfully")
    assert supplicant_stage(text) == "key_exchange"


def _hexdump(label: str, data: str) -> str:
    return f"2.0: {label} - hexdump(len={len(data) // 2}): " + " ".join(
        data[i:i + 2] for i in range(0, len(data), 2))


def test_session_pmk_sae_and_eap_last_wins():
    old, new = "11" * 32, "22" * 32
    log = "\n".join([_hexdump("SAE: PMK", old), "2.1: wlan0: CTRL-EVENT-CONNECTED",
                     _hexdump("WPA: PMK from EAPOL state machine", new)])
    assert session_pmk(log) == new


def test_session_pmk_absent_without_key_logging():
    assert session_pmk("2.0: SAE: PMK - hexdump(len=32): [REMOVED]") is None
    assert session_pmk("") is None


def test_normalize_pmk():
    assert normalize_pmk(" ".join(["3a"] * 32)) == PMK
    assert normalize_pmk(":".join(["3A"] * 32)) == PMK
    with pytest.raises(ValueError):
        normalize_pmk("abcd")


# -- templates -------------------------------------------------------------------------------

def test_ap_config_enterprise():
    text = render("hostapd/ap.conf.j2", iface="ap0", ctrl_dir="/run/h", country_code="US",
                  ssid="lab-corp", hw_mode="g", channel=6, key_mgmt="WPA-EAP", pmf=1,
                  passphrase=None, sae_password=None, deny_macs=[], deny_mac_file="/d",
                  eap_user_file="/e", eap_cert={"cert": "/c.pem", "key": "/c.key"})
    for line in ("wpa_key_mgmt=WPA-EAP", "ieee8021x=1", "eap_server=1", "eap_user_file=/e",
                 "server_cert=/c.pem", "private_key=/c.key"):
        assert line in text
    assert "wpa_passphrase" not in text


def test_client_config_peap():
    settings = eap.client_settings("PEAP", "alice", "pw", ca_cert="/ca.pem")
    text = render("wpa_supplicant/client.conf.j2", ctrl_dir="/run/c", country_code="US",
                  ssid="lab-corp", key_mgmt="WPA-EAP", ieee80211w=1, psk=None, sae_password=None,
                  eap=settings)
    for line in ("eap=PEAP", 'identity="alice"', 'password="pw"', 'phase2="auth=MSCHAPV2"',
                 'ca_cert="/ca.pem"'):
        assert line in text
    pwd = render("wpa_supplicant/client.conf.j2", ctrl_dir="/run/c", country_code="US",
                 ssid="lab-corp", key_mgmt="WPA-EAP", ieee80211w=1, psk=None, sae_password=None,
                 eap=eap.client_settings("PWD", "alice", "pw"))
    assert "eap=PWD" in pwd and "phase2" not in pwd and "ca_cert" not in pwd


def test_eap_user_file():
    assert eap.user_file_text("PWD", "alice", "pw") == '"alice" PWD "pw"\n'
    assert eap.user_file_text("PEAP", "alice", "pw").splitlines() == [
        '"alice" PEAP', '"alice" MSCHAPV2 "pw" [2]']


@pytest.mark.parametrize("ft", [False, True])
def test_roam_ap_config(ft):
    text = render("hostapd/roam.conf.j2", iface="ap1", ctrl_dir="/run/h", country_code="US",
                  ssid="lab-roam", passphrase="pw12345678", ft=ft, channel=11, bridge="br-roam",
                  mobility_domain="a1b2")
    assert "bridge=br-roam" in text and "channel=11" in text
    if ft:
        assert "wpa_key_mgmt=WPA-PSK FT-PSK" in text and "mobility_domain=a1b2" in text
        assert "ft_psk_generate_local=1" in text and "nas_identifier=ap1.lab" in text
    else:
        assert "wpa_key_mgmt=WPA-PSK\n" in text and "mobility_domain" not in text


# -- roam summary ----------------------------------------------------------------------------

def _roam(seq: Seq, alg: int, handshake: bool) -> list[Frame]:
    def add(kind, src, dst, **kw):
        seq.frames.append(Frame(no=len(seq.frames) + 1, time=len(seq.frames) * 0.01, kind=kind,
                                src=src, dst=dst, bssid=AP2, **kw))
    add("auth", STA, AP2, auth_alg=alg, auth_seq=1, status=0)
    add("auth", AP2, STA, auth_alg=alg, auth_seq=2, status=0)
    add("reassoc_req", STA, AP2, rsn=True)
    add("reassoc_resp", AP2, STA, status=0)
    if handshake:
        for m in range(1, 5):
            add("eapol", *((AP2, STA) if m in (1, 3) else (STA, AP2)), eapol_msg=m)
    return seq.frames


def test_roam_summary_full_vs_ft():
    full = roam_summary(_roam(Seq().probe().open_auth().assoc().handshake(), 0, True), STA, AP2)
    assert full["auth_alg"] == "Open System" and full["eapol_msgs"] == [1, 2, 3, 4]
    assert full["request"] == "reassoc_req"
    ft = roam_summary(_roam(Seq().probe().open_auth().assoc().handshake(), 2, False), STA, AP2)
    assert ft["auth_alg"] == "FT" and ft["eapol_msgs"] == []
