"""802.1X enterprise login (WPA2-Enterprise): join with a username and password checked by an
authentication server, and name the stage when the login fails.

hostapd's built-in EAP server stands in for RADIUS (see testbed/eap.py). Enterprise adds one step
to the join: after association the client logs in over EAP, and only then does the 4-way
handshake run. So a wrong password fails at `eap`, not at key_exchange as with WPA2-PSK.

Each case also decrypts its capture with the session PMK from the client log: a password alone
cannot decrypt 802.1X traffic, because every session gets a fresh key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from classifier.classify_join import classify_pcap
from testbed import eap
from testbed.client import session_pmk

pytestmark = [pytest.mark.lab, pytest.mark.enterprise]

SSID = "lab-corp"
USER, PASSWORD = "alice", "alicepassword1"


@dataclass
class EapCase:
    id: str
    method: str
    password: str
    expected: str  # classifier / harness stage; "success" when the join must pass
    untrusted_server: bool = False


CASES = [
    EapCase("pwd_success", "PWD", PASSWORD, "success"),
    EapCase("pwd_wrong_password", "PWD", "wrongpassword1", "eap"),
    EapCase("peap_success", "PEAP", PASSWORD, "success"),
    EapCase("peap_wrong_password", "PEAP", "wrongpassword1", "eap"),
    # The client trusts a different CA than the one that signed the server certificate: a
    # correctly configured client refuses to send its password to an unknown server.
    EapCase("peap_untrusted_server", "PEAP", PASSWORD, "eap", untrusted_server=True),
]


@pytest.fixture(scope="module")
def certs(lab_workdir):
    d = lab_workdir / "eap"
    return {"server": eap.make_cert(d, "radius", "radius.lab"),
            "other": eap.make_cert(d, "other-ca", "not-our-radius.example")}


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_enterprise_join(case, hostap, dnsmasq, clients, inventory, certs, lab_workdir, artifacts,
                         attach, capture, ap_log, record_property):
    client = clients["client1"]
    lab = inventory.lab
    users = eap.write_user_file(lab_workdir / "eap" / f"eap_user.{case.method}", case.method,
                                USER, PASSWORD)
    hostap.ensure(ssid=SSID, hw_mode="g", channel=6, key_mgmt="WPA-EAP", pmf=1, passphrase=None,
                  sae_password=None, deny_macs=[], eap_user_file=str(users),
                  eap_cert=certs["server"] if case.method == "PEAP" else None)
    dnsmasq.ensure()
    ca = certs["other" if case.untrusted_server else "server"]["cert"]
    network = {"key_mgmt": "WPA-EAP", "ieee80211w": 1,
               "eap": eap.client_settings(case.method, USER, case.password, ca_cert=ca)}
    try:
        join = client.join(SSID, network, gateway=lab["gateway"], dns_name=lab["dns_test_name"],
                           dns_expect=lab["gateway"], artifacts=artifacts, assoc_timeout=20)
    finally:
        client.disconnect()
    pcap = capture.stop()
    log = artifacts / f"wpa_supplicant-{client.name}.log"
    attach(log, log.name)
    pmk = session_pmk(log.read_text(errors="replace")) if log.exists() else None
    verdict = classify_pcap(str(pcap), sta=client.mac, pmk=pmk)
    (artifacts / "classification.json").write_text(json.dumps(verdict.to_dict(), indent=2))
    record_property("harness_stage", join.failed_stage)
    record_property("classifier_stage", verdict.stage)
    record_property("pmk_found", pmk is not None)

    if case.expected == "success":
        assert join.passed, f"join failed at {join.failed_stage}"
        assert pmk, "no PMK in the supplicant log (is -K on? did the line format change?)"
        assert verdict.stage == "success", \
            f"classifier said {verdict.stage} with the session PMK: {verdict.summary}"
    else:
        assert join.failed_stage == case.expected, f"harness stage {join.failed_stage}"
        assert verdict.stage == case.expected, f"classifier said {verdict.stage}: {verdict.summary}"
    if case.untrusted_server:
        assert "CTRL-EVENT-EAP-TLS-CERT-ERROR" in log.read_text(errors="replace"), \
            "client failed but not because of the server certificate"
