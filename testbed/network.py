"""Lab networking: namespaces, dnsmasq (DHCP/DNS), and the Module 3 VLAN-filtering bridge."""

from __future__ import annotations

import os
import signal
from dataclasses import dataclass
from pathlib import Path

from testbed import LAB_DIR
from testbed.ap import HostAP
from testbed.util import log, render, run, wait_for


def namespaces() -> list[str]:
    return [line.split()[0] for line in run(["ip", "netns", "list"]).stdout.splitlines() if line]


def iface_in_namespace(iface: str, namespace: str | None) -> bool:
    return run(["ip", "link", "show", iface], namespace=namespace, check=False).returncode == 0


@dataclass(frozen=True)
class Subnet:
    iface: str
    tag: str
    gateway: str
    start: str
    end: str


class Dnsmasq:
    """One dnsmasq instance serving DHCP and DNS on one or more lab interfaces."""

    def __init__(self, workdir: Path, subnets: list[Subnet], domain: str = "lab",
                 dns_records: dict[str, str] | None = None):
        self.workdir = Path(workdir)
        self.subnets = subnets
        self.domain = domain
        self.dns_records = dns_records or {}
        self.conf = self.workdir / "dnsmasq.conf"
        self.log = self.workdir / "dnsmasq.log"
        self.pid_file = self.workdir / "dnsmasq.pid"
        self.mode: tuple[bool, bool] | None = None

    def start(self, dhcp: bool = True, dns: bool = True) -> None:
        self.stop()
        self.workdir.mkdir(parents=True, exist_ok=True)
        render("dnsmasq/lab.conf.j2", self.conf, subnets=self.subnets, domain=self.domain,
               dns_records=self.dns_records, dhcp=dhcp, dns=dns, pid_file=self.pid_file,
               log_file=self.log, lease_file=self.workdir / "dnsmasq.leases")
        run(["dnsmasq", "--test", "-C", str(self.conf)])
        run(["dnsmasq", "-C", str(self.conf)])
        wait_for(self.pid_file.exists, timeout=5)
        self.mode = (dhcp, dns)
        log.info("dnsmasq up (dhcp=%s dns=%s)", dhcp, dns)

    def ensure(self, dhcp: bool = True, dns: bool = True) -> None:
        if self.mode != (dhcp, dns):
            self.start(dhcp=dhcp, dns=dns)

    def stop(self) -> None:
        self.mode = None
        try:
            pid = int(self.pid_file.read_text().strip())
        except (FileNotFoundError, ValueError):
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        wait_for(lambda: not Path(f"/proc/{pid}").exists(), timeout=5)
        self.pid_file.unlink(missing_ok=True)


class VlanLab:
    """Module 3: three SSIDs, each bridged onto its own VLAN, routed and firewalled by the host.

        ap0 / ap0v20 / ap0v30 (one BSS per SSID)
              |  PVID 10 / 20 / 30, untagged
           br-lab (vlan_filtering=1)  -- plays the managed switch
              |
        br-lab.10 / .20 / .30  -- gateways; nftables filters forwarding between them
    """

    BRIDGE = "br-lab"
    NFT_FILE = LAB_DIR / "nftables" / "vlan-policy.nft"

    def __init__(self, ap: HostAP, vlans: list[dict], workdir: Path, base_cidr: str,
                 hw_mode: str = "g", channel: int = 6):
        self.ap = ap
        self.vlans = vlans
        self.workdir = Path(workdir)
        self.base_cidr = base_cidr
        self.hw_mode = hw_mode
        self.channel = channel
        self.dnsmasq = Dnsmasq(
            self.workdir / "dnsmasq",
            [Subnet(self.vlan_iface(v), f"vlan{v['vlan']}", v["gateway"], *v["dhcp_range"])
             for v in vlans],
            dns_records={"gw.lab": vlans[0]["gateway"]},
        )

    def vlan_iface(self, vlan: dict) -> str:
        return f"{self.BRIDGE}.{vlan['vlan']}"

    def bss_iface(self, index: int, vlan: dict) -> str:
        return self.ap.iface if index == 0 else f"{self.ap.iface}v{vlan['vlan']}"

    def up(self, ap_isolate: bool = False) -> None:
        br = self.BRIDGE
        run(["ip", "addr", "flush", "dev", self.ap.iface])
        run(["ip", "link", "add", br, "type", "bridge", "vlan_filtering", "1"])
        run(["ip", "link", "set", br, "up"])
        for v in self.vlans:
            vid, sub = str(v["vlan"]), self.vlan_iface(v)
            run(["bridge", "vlan", "add", "dev", br, "vid", vid, "self"])
            run(["ip", "link", "add", "link", br, "name", sub, "type", "vlan", "id", vid])
            run(["ip", "addr", "add", f"{v['gateway']}/24", "dev", sub])
            run(["ip", "link", "set", sub, "up"])
        run(["sysctl", "-qw", "net.ipv4.ip_forward=1"])
        # If br_netfilter is loaded (Docker does this), bridged same-VLAN frames would hit the
        # inet forward chain and be dropped; the policy is meant for routed inter-VLAN traffic.
        run(["sysctl", "-qw", "net.bridge.bridge-nf-call-iptables=0"], check=False)
        run(["nft", "-f", str(self.NFT_FILE)])
        self.start_ap(ap_isolate)
        self.dnsmasq.start()

    def start_ap(self, ap_isolate: bool) -> None:
        bsses = [
            {"iface": self.bss_iface(i, v), "ssid": v["ssid"], "passphrase": v["passphrase"],
             "ap_isolate": ap_isolate and v.get("isolatable", False)}
            for i, v in enumerate(self.vlans)
        ]
        self.ap.start("hostapd/vlan_ssids.conf.j2", bsses=bsses, bridge=self.BRIDGE,
                      hw_mode=self.hw_mode, channel=self.channel)
        # hostapd adds each BSS to the bridge untagged in VLAN 1; move each to its VLAN.
        for i, v in enumerate(self.vlans):
            port = self.bss_iface(i, v)
            run(["bridge", "vlan", "del", "dev", port, "vid", "1"], check=False)
            run(["bridge", "vlan", "add", "dev", port, "vid", str(v["vlan"]), "pvid", "untagged"])

    def down(self) -> None:
        self.dnsmasq.stop()
        self.ap.stop()
        run(["nft", "delete", "table", "inet", "labfw"], check=False)
        for v in self.vlans:
            run(["ip", "link", "del", self.vlan_iface(v)], check=False)
        run(["ip", "link", "del", self.BRIDGE], check=False)
        run(["ip", "addr", "replace", self.base_cidr, "dev", self.ap.iface], check=False)
        run(["ip", "link", "set", self.ap.iface, "up"], check=False)
