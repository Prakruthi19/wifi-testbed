"""Module 1: connectivity matrix across security, PMF, band/channel and client capability.

Each case joins `--repeats` times (default 5) so flakiness shows up as a pass rate.
Expected results come from testbed/matrix.py and are documented in docs/test-plan.md.
"""

from __future__ import annotations

import json

import pytest

from testbed.client import summarize
from testbed.matrix import CLIENT_PROFILES, ApConfig, build_matrix, compliance_violations

pytestmark = pytest.mark.lab

# Which physical client radio plays which capability profile.
PROFILE_CLIENT = {"wpa3-capable": "client1", "wpa2-only": "client2"}


def pytest_generate_tests(metafunc):
    if "case" in metafunc.fixturenames:
        opt = metafunc.config.getoption("--channels")
        channels = [int(c) for c in opt.split(",")] if opt else None
        cases = build_matrix(channels)
        metafunc.parametrize("case", cases, ids=[c.id for c in cases])


def join_repeatedly(client, ap: ApConfig, profile, inventory, artifacts, repeats):
    lab = inventory.lab
    results = []
    for i in range(repeats):
        res = client.join(ap.ssid, profile.network_for(ap), gateway=lab["gateway"],
                          dns_name=lab["dns_test_name"], dns_expect=lab["gateway"],
                          artifacts=artifacts / f"attempt{i + 1}")
        results.append(res)
        client.disconnect()
    return results


@pytest.mark.matrix
def test_matrix(case, hostap, dnsmasq, clients, inventory, artifacts, attach, capture, ap_log,
                record_property, request):
    ap, profile, exp = case.ap, case.client, case.expectation
    hostap.ensure(**ap.template_params())
    client = clients[PROFILE_CLIENT[profile.name]]

    results = join_repeatedly(client, ap, profile, inventory, artifacts,
                              request.config.getoption("--repeats"))
    stats = summarize(results)

    (artifacts / "results.json").write_text(
        json.dumps({"case": case.id, "expected": exp.__dict__, "summary": stats,
                    "attempts": [r.to_dict() for r in results]}, indent=2))
    attach(artifacts / "results.json")
    for i in range(len(results)):
        attach(artifacts / f"attempt{i + 1}" / f"wpa_supplicant-{client.name}.log",
               f"wpa_supplicant attempt {i + 1}")
    for key, value in [("matrix_row", ap.label), ("matrix_col", profile.name),
                       ("expected", exp.outcome), ("pass_rate", stats["pass_rate"]),
                       ("median_join_ms", stats["median_join_ms"]),
                       ("failed_stages", stats["failed_stages"])]:
        record_property(key, value)

    if exp.outcome == "noncompliant":
        # The harness must flag the config; the join result is recorded, not judged.
        assert compliance_violations(ap), "non-compliant config was not flagged"
        record_property("compliance", "NON-COMPLIANT: " + exp.reason)
        return
    if exp.outcome == "pass":
        assert stats["pass_rate"] == 1.0, (
            f"expected every join to pass; pass rate {stats['pass_rate']:.0%}, "
            f"failed at {stats['failed_stages']}")
    else:
        assert stats["pass_rate"] == 0.0, (
            f"expected failure at {exp.stage} ({exp.reason}) but "
            f"{stats['pass_rate']:.0%} of joins passed -- a pass that should fail is a bug")


# -- qualify_ap: 6-case baseline for each AP entry in inventory.yaml ------------------------

QUALIFY_STEPS = ["beacons", "wpa3_join", "wpa2_join", "dhcp_lease", "dns", "reconnect"]


def qualify_aps():
    from testbed import inventory as inv
    try:
        return inv.load().aps
    except FileNotFoundError:
        return []


@pytest.mark.qualify
@pytest.mark.parametrize("ap_entry", qualify_aps(), ids=lambda a: a["name"])
@pytest.mark.parametrize("step", QUALIFY_STEPS)
def test_qualify_ap(ap_entry, step, hostap, dnsmasq, clients, inventory, artifacts, capture,
                    ap_log):
    ap = ApConfig(ap_entry["security"], ap_entry["pmf"], ap_entry["channel"],
                  ssid=ap_entry["ssid"], passphrase=ap_entry["passphrase"])
    assert not compliance_violations(ap), f"{ap_entry['name']} is non-compliant"
    hostap.ensure(**ap.template_params())
    lab = inventory.lab

    if step == "beacons":
        assert hostap.status().get("ssid[0]") == ap.ssid
        return

    profile = CLIENT_PROFILES["wpa2-only" if step == "wpa2_join" else "wpa3-capable"]
    client = clients[PROFILE_CLIENT[profile.name]]
    if step == "wpa2_join" and (ap.security == "wpa3" or ap.pmf == 2):
        pytest.skip("AP does not admit WPA2-only clients by design")
    res = client.join(ap.ssid, profile.network_for(ap), gateway=lab["gateway"],
                      dns_name=lab["dns_test_name"], dns_expect=lab["gateway"],
                      artifacts=artifacts)
    try:
        if step in ("wpa3_join", "wpa2_join"):
            assert res.failed_stage not in ("association", "authentication", "key_exchange"), res
        elif step == "dhcp_lease":
            assert res.ip and res.ip.startswith(lab["subnet"].rsplit(".", 1)[0]), res
        elif step == "dns":
            assert res.dns_ok, res
        elif step == "reconnect":
            assert res.passed, res
            client.disconnect()
            again = client.join(ap.ssid, profile.network_for(ap), gateway=lab["gateway"],
                                artifacts=artifacts / "rejoin")
            assert again.passed, again
    finally:
        client.disconnect()
