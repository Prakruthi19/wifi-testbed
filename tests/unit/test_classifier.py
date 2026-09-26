"""Classifier decision logic on synthetic frame sequences modelled on each induced failure."""

import pytest

from classifier.classify_join import Frame, classify, eapol_message, guess_sta

AP = "02:00:00:00:00:00"
STA = "02:00:00:00:01:00"
BC = "ff:ff:ff:ff:ff:ff"


class Seq:
    def __init__(self):
        self.frames = []

    def add(self, kind, src, dst, **kw):
        self.frames.append(Frame(no=len(self.frames) + 1, time=len(self.frames) * 0.01, kind=kind,
                                 src=src, dst=dst, bssid=AP, **kw))
        return self

    def probe(self):
        return self.add("probe_req", STA, BC).add("probe_resp", AP, STA)

    def open_auth(self, status=0):
        return self.add("auth", STA, AP, auth_alg=0, auth_seq=1, status=0) \
                   .add("auth", AP, STA, auth_alg=0, auth_seq=2, status=status)

    def sae(self, ap_confirms=True):
        self.add("auth", STA, AP, auth_alg=3, auth_seq=1, status=0)
        self.add("auth", AP, STA, auth_alg=3, auth_seq=1, status=0)
        self.add("auth", STA, AP, auth_alg=3, auth_seq=2, status=0)
        if ap_confirms:
            self.add("auth", AP, STA, auth_alg=3, auth_seq=2, status=0)
        return self

    def assoc(self, status=0):
        return self.add("assoc_req", STA, AP, rsn=True).add("assoc_resp", AP, STA, status=status)

    def handshake(self, upto=4):
        for m in range(1, upto + 1):
            src, dst = (AP, STA) if m in (1, 3) else (STA, AP)
            self.add("eapol", src, dst, eapol_msg=m)
        return self

    def dhcp(self, *types):
        for t in types:
            src, dst = (STA, BC) if t in (1, 3) else (AP, STA)
            self.add("dhcp", src, dst, dhcp_type=t, dhcp_client=STA)
        return self

    def dns(self, answered=True, rcode=0):
        self.add("dns", STA, AP, dns_id=7, dns_response=False, dns_name="gw.lab")
        if answered:
            self.add("dns", AP, STA, dns_id=7, dns_response=True, dns_rcode=rcode)
        return self


def full_join():
    return Seq().probe().open_auth().assoc().handshake().dhcp(1, 2, 3, 5).dns()


def test_success():
    res = classify(full_join().frames)
    assert res.stage == "success" and res.sta == STA and res.bssid == AP


def test_wrong_wpa2_passphrase_is_key_exchange():
    s = Seq().probe().open_auth().assoc().handshake(upto=2).handshake(upto=2)
    s.add("deauth", AP, STA, reason=15)
    res = classify(s.frames)
    assert res.stage == "key_exchange"
    assert "message 3" in res.summary
    assert any(f.kind == "deauth" for f in res.evidence)


def test_wrong_sae_password_is_authentication():
    res = classify(Seq().probe().sae(ap_confirms=False).sae(ap_confirms=False).frames)
    assert res.stage == "authentication" and "Confirm" in res.summary


def test_akm_or_pmf_mismatch_is_network_selection():
    # Client sees the AP's RSN element, finds it incompatible and never sends Auth or Assoc.
    res = classify(Seq().probe().probe().frames)
    assert res.stage == "network_selection" and "never attempted" in res.summary


def test_no_client_frames_is_network_selection():
    assert classify([]).stage == "network_selection"


def test_assoc_reject_is_association():
    # Status 31 (robust management frame policy violation): the client picked the network
    # despite a PMF mismatch and the AP refused it, so this one really is association.
    res = classify(Seq().probe().open_auth().assoc(status=31).frames)
    assert res.stage == "association" and "31" in res.summary


def test_mac_blocked_is_authentication():
    res = classify(Seq().probe().open_auth(status=1).frames)
    assert res.stage == "authentication" and "status 1" in res.summary


@pytest.mark.parametrize("types,summary", [((1, 1, 1), "no Offer"), ((1, 2, 3, 6), "NAK"),
                                           ((1, 2), "no ACK")])
def test_dhcp_failures(types, summary):
    res = classify(Seq().open_auth().assoc().handshake().dhcp(*types).frames)
    assert res.stage == "dhcp" and summary in res.summary


def test_dns_no_answer():
    s = Seq().open_auth().assoc().handshake().dhcp(1, 2, 3, 5).dns(answered=False).dns(answered=False)
    assert classify(s.frames).stage == "dns"


def test_dns_error_rcode():
    s = Seq().open_auth().assoc().handshake().dhcp(1, 2, 3, 5).dns(rcode=2)
    assert classify(s.frames).stage == "dns"


def test_retry_then_success_counts_as_success():
    s = Seq().open_auth().assoc().handshake(upto=2).add("deauth", AP, STA, reason=15)
    s.open_auth().assoc().handshake().dhcp(1, 2, 3, 5).dns()
    assert classify(s.frames).stage == "success"


def test_encrypted_without_key_is_undetermined():
    s = Seq().open_auth().assoc().handshake().add("data", STA, AP, protected=True)
    assert classify(s.frames).stage == "undetermined"


def test_open_network_skips_key_exchange():
    s = Seq().open_auth()
    s.add("assoc_req", STA, AP, rsn=False).add("assoc_resp", AP, STA, status=0)
    s.dhcp(1, 2, 3, 5)
    assert classify(s.frames).stage == "success"


def test_other_stations_are_ignored():
    s = full_join()
    other = "02:00:00:00:02:00"
    s.add("auth", other, AP, auth_alg=0, auth_seq=1, status=0)
    assert classify(s.frames, sta=STA).stage == "success"
    assert guess_sta(s.frames) == other


def test_sae_status_126_counts_as_commit():
    s = Seq()
    s.add("auth", STA, AP, auth_alg=3, auth_seq=1, status=126)
    s.add("auth", AP, STA, auth_alg=3, auth_seq=1, status=126)
    s.add("auth", STA, AP, auth_alg=3, auth_seq=2, status=0)
    s.add("auth", AP, STA, auth_alg=3, auth_seq=2, status=0)
    s.assoc().handshake().dhcp(1, 2, 3, 5)
    assert classify(s.frames).stage == "success"


@pytest.mark.parametrize("key_info,msg", [(0x008A, 1), (0x010A, 2), (0x13CA, 3), (0x030A, 4)])
def test_eapol_message_numbers(key_info, msg):
    assert eapol_message(key_info) == msg
