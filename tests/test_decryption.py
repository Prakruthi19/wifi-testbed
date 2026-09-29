"""WPA3 captures can be classified past layer 2 only with the session key.

With WPA2-PSK, passphrase + SSID are enough to decrypt a capture (--wpa-pwd). WPA3-SAE makes a
fresh PMK every session, so the same trick fails and the classifier can only say "undetermined"
after the handshake. This test proves both halves on one WPA3 join: without a key the verdict is
undetermined; with the PMK from the client log (wpa_supplicant -K) it sees DHCP and says success.
"""

from __future__ import annotations

import json

import pytest

from classifier.classify_join import classify_pcap
from testbed.client import session_pmk
from testbed.matrix import ApConfig

pytestmark = [pytest.mark.lab, pytest.mark.decrypt]

SSID, PASS = "lab-wpa3-dec", "labpassword123"


def test_wpa3_capture_needs_session_pmk(hostap, dnsmasq, clients, inventory, artifacts, attach,
                                        capture, record_property):
    client = clients["client1"]
    lab = inventory.lab
    hostap.ensure(**ApConfig("wpa3", 2, 6, ssid=SSID, passphrase=PASS).template_params())
    dnsmasq.ensure()
    try:
        join = client.join(SSID, {"key_mgmt": "SAE", "ieee80211w": 2, "sae_password": PASS},
                           gateway=lab["gateway"], dns_name=lab["dns_test_name"],
                           dns_expect=lab["gateway"], artifacts=artifacts)
    finally:
        client.disconnect()
    pcap = capture.stop()
    log = artifacts / f"wpa_supplicant-{client.name}.log"
    attach(log, log.name)
    assert join.passed, f"WPA3 join failed at {join.failed_stage}"

    pmk = session_pmk(log.read_text(errors="replace"))
    assert pmk, "no 'SAE: PMK' line in the supplicant log (is -K on? did the line format change?)"
    # Passphrase decryption is the WPA2 method; on SAE it must not work.
    with_password = classify_pcap(str(pcap), sta=client.mac, wpa_pwd=f"{PASS}:{SSID}")
    with_pmk = classify_pcap(str(pcap), sta=client.mac, pmk=pmk)
    (artifacts / "classification.json").write_text(json.dumps(
        {"with_password": with_password.to_dict(), "with_pmk": with_pmk.to_dict()}, indent=2))
    record_property("with_password", with_password.stage)
    record_property("with_pmk", with_pmk.stage)
    assert with_password.stage == "undetermined", \
        f"expected the passphrase to be useless on SAE, got {with_password.stage}"
    assert with_pmk.stage == "success", f"with the PMK: {with_pmk.stage}: {with_pmk.summary}"
