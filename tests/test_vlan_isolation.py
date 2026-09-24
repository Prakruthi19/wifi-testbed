"""Module 3: three SSIDs on three VLANs; prove traffic stays where lab/nftables/vlan-policy.nft says.

Only three client radios exist, so tests re-join clients to whichever SSIDs they need.
"""

from __future__ import annotations

import ipaddress

import pytest

from testbed.network import VlanLab

pytestmark = [pytest.mark.lab, pytest.mark.vlan]


@pytest.fixture(scope="module")
def vlan_lab(hostap, inventory, lab_workdir):
    lab = inventory.lab
    vl = VlanLab(hostap, inventory.vlans, lab_workdir / "vlan",
                 base_cidr=f"{lab['gateway']}/24")
    vl.up()
    yield vl
    vl.down()


@pytest.fixture
def joiner(vlan_lab, clients, artifacts):
    """joiner(client_name, ssid) -> JoinResult, with automatic disconnects afterwards."""
    used = []
    by_ssid = {v["ssid"]: v for v in vlan_lab.vlans}

    def _join(name: str, ssid: str):
        v = by_ssid[ssid]
        client = clients[name]
        used.append(client)
        res = client.join(ssid, {"key_mgmt": "WPA-PSK SAE", "ieee80211w": 1,
                                 "psk": v["passphrase"]},
                          gateway=v["gateway"], dns_name="gw.lab",
                          artifacts=artifacts / f"{name}-{ssid}")
        assert res.passed, f"{name} failed to join {ssid}: {res}"
        return res

    yield _join
    for c in used:
        c.disconnect()


def vlan(inventory, ssid):
    return next(v for v in inventory.vlans if v["ssid"] == ssid)


@pytest.mark.parametrize("ssid", ["lab-mgmt", "lab-test", "lab-iot"])
def test_lease_from_correct_subnet(ssid, joiner, inventory, capture):
    res = joiner("client1", ssid)
    assert ipaddress.ip_address(res.ip) in ipaddress.ip_network(vlan(inventory, ssid)["subnet"])


@pytest.mark.parametrize("ssid", ["lab-mgmt", "lab-test", "lab-iot"])
def test_dns_resolves(ssid, joiner, clients, inventory):
    joiner("client1", ssid)
    answers, _ = clients["client1"].resolve(vlan(inventory, ssid)["gateway"], "gw.lab")
    assert answers, f"no DNS answer on {ssid}"


def test_iot_cannot_reach_mgmt(joiner, clients, inventory, capture):
    mgmt = joiner("client1", "lab-mgmt")
    joiner("client2", "lab-iot")
    iot = clients["client2"]
    assert not iot.ping(mgmt.ip, count=2), "IoT client pinged a management client"
    assert not iot.tcp_connect(mgmt.ip, 22), "IoT client opened TCP to a management client"
    assert not iot.ping(vlan(inventory, "lab-mgmt")["gateway"], count=2), \
        "IoT client reached the management gateway"


def test_mgmt_can_reach_iot(joiner, clients, capture):
    joiner("client1", "lab-mgmt")
    iot = joiner("client2", "lab-iot")
    assert clients["client1"].ping(iot.ip), "management client could not reach IoT subnet"


def test_test_ssid_cannot_reach_iot(joiner, clients, capture):
    joiner("client1", "lab-test")
    iot = joiner("client2", "lab-iot")
    assert not clients["client1"].ping(iot.ip, count=2)


def test_iot_clients_reach_each_other(joiner, clients, capture):
    joiner("client2", "lab-iot")
    other = joiner("client3", "lab-iot")
    assert clients["client2"].ping(other.ip), "IoT peers should reach each other without ap_isolate"


def test_iot_client_isolation(vlan_lab, joiner, clients, capture):
    """ap_isolate=1 on lab-iot: peers on the same SSID must not reach each other."""
    vlan_lab.start_ap(ap_isolate=True)
    try:
        joiner("client2", "lab-iot")
        other = joiner("client3", "lab-iot")
        assert not clients["client2"].ping(other.ip, count=2), "ap_isolate did not isolate peers"
    finally:
        for c in clients.values():
            c.disconnect()
        vlan_lab.start_ap(ap_isolate=False)
