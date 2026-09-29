"""Roaming lab: two APs (ap0, ap1) of one network, bridged together so a client keeps its IP.

        ap0 (ch 1)     ap1 (ch 11)        two hwsim radios, one hostapd each, same SSID
             \\          /
              br-roam  192.168.50.1       gateway, DHCP and DNS for both APs

Needs the fifth radio: `ROAM=1 sudo lab/setup_lab.sh` creates ap1.
"""

from __future__ import annotations

from pathlib import Path

from testbed.ap import HostAP
from testbed.network import Dnsmasq, Subnet
from testbed.util import run

MOBILITY_DOMAIN = "a1b2"


def bssid(iface: str) -> str:
    return Path(f"/sys/class/net/{iface}/address").read_text().strip().lower()


class RoamLab:
    BRIDGE = "br-roam"

    def __init__(self, ap_ifaces: tuple[str, str], workdir: Path, lab: dict, country_code: str,
                 channels: tuple[int, int] = (1, 11)):
        self.workdir = Path(workdir)
        self.lab = lab
        self.channels = channels
        self.aps = [HostAP(iface, self.workdir / f"hostapd-{iface}", country_code)
                    for iface in ap_ifaces]
        self.base_cidr = f"{lab['gateway']}/{lab['subnet'].split('/')[1]}"
        self.dnsmasq = Dnsmasq(self.workdir / "dnsmasq",
                               [Subnet(self.BRIDGE, "roam", lab["gateway"], *lab["dhcp_range"])],
                               domain=lab["dns_domain"],
                               dns_records={lab["dns_test_name"]: lab["gateway"]})

    def up(self) -> None:
        br = self.BRIDGE
        run(["ip", "addr", "flush", "dev", self.aps[0].iface])
        run(["ip", "link", "add", br, "type", "bridge"])
        run(["ip", "addr", "add", self.base_cidr, "dev", br])
        run(["ip", "link", "set", br, "up"])
        # If br_netfilter is loaded (Docker does this), bridged frames would hit the firewall.
        run(["sysctl", "-qw", "net.bridge.bridge-nf-call-iptables=0"], check=False)
        self.dnsmasq.start()

    def start_ap(self, index: int, ssid: str, passphrase: str, ft: bool) -> str:
        """Start AP `index` (0 or 1); returns its BSSID."""
        ap = self.aps[index]
        ap.ensure("hostapd/roam.conf.j2", ssid=ssid, passphrase=passphrase, ft=ft,
                  channel=self.channels[index], bridge=self.BRIDGE, mobility_domain=MOBILITY_DOMAIN)
        return bssid(ap.iface)

    def stop_aps(self) -> None:
        for ap in self.aps:
            ap.stop()

    def down(self) -> None:
        self.dnsmasq.stop()
        self.stop_aps()
        run(["ip", "link", "del", self.BRIDGE], check=False)
        first = self.aps[0].iface
        run(["ip", "addr", "replace", self.base_cidr, "dev", first], check=False)
        run(["ip", "link", "set", first, "up"], check=False)
