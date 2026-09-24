"""Module 2: induce one join failure at a time, capture it, and check the classifier names the stage.

The expected stages below are hypotheses until confirmed against real captures and written
up in docs/failure-signatures.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from classifier.classify_join import classify_pcap
from testbed.matrix import ApConfig

pytestmark = [pytest.mark.lab, pytest.mark.failures]

PASS = "labpassword123"
SSID = "lab-diag"


@dataclass
class FailureCase:
    id: str
    ap: ApConfig
    network: dict
    expected: tuple[str, ...]
    deny_client: bool = False
    dhcp: bool = True
    dns: bool = True
    notes: list[str] = field(default_factory=list)


def wpa2(pmf=1):
    return ApConfig("wpa2", pmf, 6, ssid=SSID, passphrase=PASS)


def wpa3():
    return ApConfig("wpa3", 2, 6, ssid=SSID, passphrase=PASS)


CASES = [
    FailureCase("baseline_success", wpa2(),
                {"key_mgmt": "WPA-PSK", "ieee80211w": 1, "psk": PASS}, ("success",)),
    FailureCase("wrong_passphrase_wpa2", wpa2(),
                {"key_mgmt": "WPA-PSK", "ieee80211w": 1, "psk": "wrongpassword1"}, ("key_exchange",)),
    FailureCase("wrong_password_wpa3", wpa3(),
                {"key_mgmt": "SAE", "ieee80211w": 2, "sae_password": "wrongpassword1"},
                ("authentication",)),
    FailureCase("wpa2_client_wpa3_ap", wpa3(),
                {"key_mgmt": "WPA-PSK", "ieee80211w": 0, "psk": PASS},
                ("association", "authentication")),
    FailureCase("pmf_mismatch", wpa2(pmf=2),
                {"key_mgmt": "WPA-PSK", "ieee80211w": 0, "psk": PASS}, ("association",)),
    FailureCase("mac_blocked", wpa2(),
                {"key_mgmt": "WPA-PSK", "ieee80211w": 1, "psk": PASS}, ("authentication",),
                deny_client=True),
    FailureCase("dhcp_server_down", wpa2(),
                {"key_mgmt": "WPA-PSK", "ieee80211w": 1, "psk": PASS}, ("dhcp",), dhcp=False),
    FailureCase("dns_broken", wpa2(),
                {"key_mgmt": "WPA-PSK", "ieee80211w": 1, "psk": PASS}, ("dns",), dns=False),
]


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_induced_failure(case, hostap, dnsmasq, clients, inventory, artifacts, attach, capture,
                         ap_log, record_property):
    client = clients["client1"]
    lab = inventory.lab
    params = case.ap.template_params()
    params["deny_macs"] = [client.mac] if case.deny_client else []
    hostap.ensure(**params)
    dnsmasq.ensure(dhcp=case.dhcp, dns=case.dns)
    try:
        join = client.join(SSID, dict(case.network), gateway=lab["gateway"],
                           dns_name=lab["dns_test_name"], dns_expect=lab["gateway"],
                           artifacts=artifacts, assoc_timeout=12)
    finally:
        client.disconnect()
        pcap = capture.stop()
        dnsmasq.ensure()  # restore DHCP + DNS for the next case

    # WPA2-PSK data frames are decrypted with the passphrase; SAE data stays opaque, which is
    # fine because every SAE case here fails before any data flows.
    wpa_pwd = f"{PASS}:{SSID}" if case.ap.security == "wpa2" else None
    result = classify_pcap(str(pcap), sta=client.mac, wpa_pwd=wpa_pwd)

    (artifacts / "classification.json").write_text(json.dumps(
        {"case": case.id, "expected": case.expected, "join": join.to_dict(),
         "classifier": result.to_dict()}, indent=2))
    attach(artifacts / "classification.json")
    attach(artifacts / f"wpa_supplicant-{client.name}.log", "wpa_supplicant.log")
    record_property("classified_stage", result.stage)
    record_property("harness_stage", join.failed_stage or "success")

    assert result.stage in case.expected, (
        f"classifier said {result.stage!r} ({result.summary}); expected {case.expected}. "
        f"Evidence: {[f.describe() for f in result.evidence]}")
