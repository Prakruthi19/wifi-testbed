from testbed.matrix import ApConfig
from testbed.network import Subnet
from testbed.util import render


def hostapd(ap: ApConfig, **extra) -> dict[str, str]:
    params = ap.template_params() | extra
    text = render("hostapd/ap.conf.j2", iface="ap0", ctrl_dir="/run/x", country_code="US",
                  deny_mac_file="/tmp/deny", **params)
    return dict(l.split("=", 1) for l in text.splitlines() if "=" in l and not l.startswith("#"))


def test_wpa2_config():
    conf = hostapd(ApConfig("wpa2", 1, 6))
    assert conf["wpa_key_mgmt"] == "WPA-PSK"
    assert conf["ieee80211w"] == "1"
    assert conf["hw_mode"] == "g" and conf["channel"] == "6"
    assert "wpa_passphrase" in conf and "sae_password" not in conf


def test_sae_config_uses_sae_password():
    conf = hostapd(ApConfig("wpa3", 2, 36))
    assert conf["wpa_key_mgmt"] == "SAE"
    assert conf["hw_mode"] == "a"
    assert "sae_password" in conf and "wpa_passphrase" not in conf


def test_transition_config_has_both():
    conf = hostapd(ApConfig("transition", 1, 11))
    assert conf["wpa_key_mgmt"] == "WPA-PSK SAE"
    assert "sae_password" in conf and "wpa_passphrase" in conf


def test_open_config_has_no_rsn():
    conf = hostapd(ApConfig("open", 0, 1))
    assert "wpa" not in conf and "ieee80211w" not in conf


def test_deny_mac_file_only_when_needed():
    assert "deny_mac_file" not in hostapd(ApConfig("wpa2", 1, 6))
    assert hostapd(ApConfig("wpa2", 1, 6), deny_macs=["02:00:00:00:01:00"])["macaddr_acl"] == "0"


def test_client_config():
    text = render("wpa_supplicant/client.conf.j2", ctrl_dir="/run/c", country_code="US",
                  ssid="lab", key_mgmt="SAE", ieee80211w=2, psk=None, sae_password="pw")
    assert 'sae_password="pw"' in text and "ieee80211w=2" in text and "psk=" not in text
    open_text = render("wpa_supplicant/client.conf.j2", ctrl_dir="/run/c", country_code="US",
                       ssid="lab", key_mgmt="NONE", ieee80211w=0, psk=None, sae_password=None)
    assert "proto=RSN" not in open_text


def dnsmasq(**kw):
    base = dict(subnets=[Subnet("ap0", "lab", "192.168.50.1", "192.168.50.100", "192.168.50.199")],
                domain="lab", dns_records={"gw.lab": "192.168.50.1"}, dhcp=True, dns=True,
                pid_file="/p", log_file="/l", lease_file="/le")
    return render("dnsmasq/lab.conf.j2", **(base | kw))


def test_dnsmasq_modes():
    assert "dhcp-range=set:lab,192.168.50.100" in dnsmasq()
    assert "port=0" not in dnsmasq()
    assert "dhcp-range" not in dnsmasq(dhcp=False)
    no_dns = dnsmasq(dns=False)
    assert "port=0" in no_dns and "address=/gw.lab" not in no_dns


def test_vlan_hostapd_config():
    bsses = [{"iface": "ap0", "ssid": "lab-mgmt", "passphrase": "p1", "ap_isolate": False},
             {"iface": "ap0v30", "ssid": "lab-iot", "passphrase": "p3", "ap_isolate": True}]
    text = render("hostapd/vlan_ssids.conf.j2", bsses=bsses, bridge="br-lab", ctrl_dir="/r",
                  country_code="US", hw_mode="g", channel=6)
    assert text.count("bridge=br-lab") == 2
    assert "bss=ap0v30" in text and "interface=ap0" in text
    assert text.index("ap_isolate=1") > text.index("bss=ap0v30")
