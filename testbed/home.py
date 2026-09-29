"""Home network lab: a main router and two mesh points with one Wi-Fi name, and five home devices.

        router (ap0, ch 6)   mesh-living (ap1, ch 1)   mesh-bedroom (ap2, ch 11)
                 \\                  |                    /
                  br-home  192.168.50.1   one network: DHCP and DNS for every AP

        phone  laptop  camera  plug  speaker   (sta1..sta5, one namespace each)

What is emulated and what is not:
- The mesh points share the router's network through a bridge, like mesh units with a wired
  (Ethernet) backhaul. Real mesh units usually link to each other over the air; that radio link
  is not emulated here.
- Each fake radio runs one band at a time. A real dual-band router runs 2.4 and 5 GHz together.
- All fake radios hear each other at full strength, so a device never moves because the signal
  got weak. Moves are forced with `wpa_cli roam`, or caused by switching an AP off.

Needs `sudo HOMENET=1 lab/setup_lab.sh`. Layout and devices come from lab/inventory.yaml `home:`.
"""

from __future__ import annotations

import argparse
import ipaddress
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from testbed.ap import HostAP
from testbed.matrix import CLIENT_PROFILES, ApConfig, ClientProfile, Expectation, expected
from testbed.network import Dnsmasq, Subnet
from testbed.steering import btm_candidate, neighbor_element
from testbed.util import run

# 2.4 GHz channels 1-11 in MHz: what a device with only a 2.4 GHz radio may use.
FREQ_2G = " ".join(str(2407 + 5 * ch) for ch in range(1, 12))


def channel_freq(channel: int) -> int:
    return 2407 + 5 * channel if channel <= 14 else 5000 + 5 * channel


def freq_band(freq: int) -> str:
    return "2.4" if freq < 3000 else "5"


# -- devices ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class DeviceProfile:
    """A kind of home device: which security it supports and which bands its radio has."""

    name: str
    client: ClientProfile
    bands: tuple[str, ...]

    def network_for(self, ap: ApConfig, passphrase: str | None = None) -> dict:
        """wpa_supplicant network settings for this device on `ap` (optionally a wrong password)."""
        net = self.client.network_for(ap)
        if passphrase is not None and net.get("psk"):
            net["psk"] = passphrase
        if self.bands == ("2.4",):
            net["freq_list"] = FREQ_2G
        return net

    def can_use(self, freq: int) -> bool:
        return freq_band(freq) in self.bands


def device_profiles(home: dict) -> list[DeviceProfile]:
    return [DeviceProfile(d["name"], CLIENT_PROFILES[d["profile"]], tuple(str(b) for b in d["bands"]))
            for d in home["devices"]]


def home_ap(security: str, channel: int, ssid: str, passphrase: str) -> ApConfig:
    """The router settings a home owner can pick: WPA2, WPA3 or WPA2/WPA3 mixed, each with the
    PMF setting the Wi-Fi Alliance requires for it."""
    pmf = {"open": 0, "wpa2": 1, "wpa3": 2, "transition": 1}[security]
    return ApConfig(security, pmf, channel, ssid=ssid, passphrase=passphrase)


def expected_home(ap: ApConfig, device: DeviceProfile) -> Expectation:
    """Written down before the run: security rules from the matrix, plus the band the device has."""
    if not device.can_use(channel_freq(ap.channel)):
        return Expectation("fail", "network_selection",
                           f"{device.name} has no {freq_band(channel_freq(ap.channel))} GHz radio")
    return expected(ap, device.client)


INTEROP_ROUTERS = [("wpa2", 6), ("wpa3", 6), ("transition", 6), ("transition", 36)]


def interop_plan(home: dict) -> str:
    """Expected results table: router setting x device, as markdown."""
    devices = device_profiles(home)
    rows = ["| Router setting | " + " | ".join(d.name for d in devices) + " |",
            "|---|" + "---|" * len(devices)]
    for security, channel in INTEROP_ROUTERS:
        ap = home_ap(security, channel, home["ssid"], home["passphrase"])
        cells = []
        for d in devices:
            exp = expected_home(ap, d)
            cells.append("joins" if exp.outcome == "pass" else f"fails ({exp.stage})")
        rows.append(f"| {ap.label} | " + " | ".join(cells) + " |")
    return "\n".join(rows)


# -- troubleshooting -------------------------------------------------------------------------

@dataclass(frozen=True)
class ScanEntry:
    bssid: str
    freq: int
    signal: int
    flags: str
    ssid: str


def parse_scan_results(text: str) -> list[ScanEntry]:
    """`wpa_cli scan_results`: "bssid / frequency / signal level / flags / ssid", tab separated."""
    out = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 4 or not parts[1].isdigit():
            continue
        out.append(ScanEntry(parts[0].lower(), int(parts[1]), int(parts[2]), parts[3],
                             parts[4] if len(parts) > 4 else ""))
    return out


@dataclass(frozen=True)
class Diagnosis:
    cause: str     # short code the tests assert on
    problem: str   # what went wrong, in plain words
    fix: str       # what the owner (or support) should do


def diagnose(stage: str | None, device: DeviceProfile, router: ApConfig, ssid: str,
             scan: list[ScanEntry], dnsmasq_log: str = "", mac: str = "") -> Diagnosis | None:
    """Turn a failed join into a cause and a fix, the way a support engineer would: look at the
    stage it stopped at, what the device could see, and how the router is set up.
    None means the device joined fine."""
    if stage is None or stage == "success":
        return None
    if stage == "network_selection":
        router_freq = channel_freq(router.channel)
        if not device.can_use(router_freq):
            return Diagnosis("band", f"The network is only on {freq_band(router_freq)} GHz and the "
                             f"{device.name} only has a {'/'.join(device.bands)} GHz radio.",
                             "Turn on the 2.4 GHz band on the router (or use a band-steering mode "
                             "that keeps 2.4 GHz on).")
        exp = expected(router, device.client)
        if exp.outcome == "fail":
            return Diagnosis("security", f"The {device.name} is too old for the router's security "
                             f"({router.label}): {exp.reason}.",
                             "Switch the router to WPA2/WPA3 mixed mode.")
        if any(e.ssid == ssid for e in scan):
            return Diagnosis("blocked", f"The {device.name} can see the network and supports its "
                             "settings, but the router never answered it.",
                             "Check the router's blocked-devices (MAC filter) list.")
        return Diagnosis("not_heard", f"The {device.name} cannot hear the network at all.",
                         "Check the router is on and the device is in range.")
    if stage == "authentication":
        return Diagnosis("blocked", f"The router turned the {device.name} away at the first step.",
                         "Check the router's blocked-devices (MAC filter) list.")
    if stage == "association":
        return Diagnosis("refused", f"The router refused to let the {device.name} join.",
                         "Check the router's device limit and settings.")
    if stage == "eap":
        return Diagnosis("login", "The username/password login (802.1X) failed.",
                         "Check the account and the login server.")
    if stage == "key_exchange":
        return Diagnosis("wrong_password", f"The {device.name} has the wrong Wi-Fi password.",
                         "Enter the current password on the device.")
    if stage == "dhcp":
        if mac and f"{mac.lower()} no address available" in dnsmasq_log.lower():
            return Diagnosis("pool_full", "The router has run out of addresses to hand out.",
                             "Make the router's address pool bigger, or remove old devices.")
        return Diagnosis("dhcp_down", "Wi-Fi works, but the router never gave the "
                         f"{device.name} an address.", "Restart the router (its DHCP service).")
    if stage == "dns":
        return Diagnosis("dns", "Connected with an address, but names (like websites) do not work.",
                         "Check the router's DNS setting.")
    if stage == "ping":
        return Diagnosis("no_route", "Connected with an address, but the router does not answer.",
                         "Restart the router; check its firewall.")
    return Diagnosis("unknown", f"Stopped at {stage}.", "Read the device and router logs.")


# -- the lab ---------------------------------------------------------------------------------

class HomeLab:
    """Every AP bridged into br-home, one dnsmasq for DHCP and DNS on the bridge."""

    BRIDGE = "br-home"

    def __init__(self, home: dict, workdir: Path, lab: dict, country_code: str):
        self.home = home
        self.lab = lab
        self.workdir = Path(workdir)
        self.ssid, self.passphrase = home["ssid"], home["passphrase"]
        self.channels = {a["name"]: a["channel"] for a in home["access_points"]}
        self.aps = {a["name"]: HostAP(a["iface"], self.workdir / f"hostapd-{a['iface']}", country_code)
                    for a in home["access_points"]}
        self.base_cidr = f"{lab['gateway']}/{lab['subnet'].split('/')[1]}"
        self.dnsmasq = Dnsmasq(self.workdir / "dnsmasq", [self._subnet(*lab["dhcp_range"])],
                               domain=lab["dns_domain"],
                               dns_records={lab["dns_test_name"]: lab["gateway"]})

    @property
    def router_name(self) -> str:
        return self.home["access_points"][0]["name"]

    def _subnet(self, start: str, end: str) -> Subnet:
        return Subnet(self.BRIDGE, "home", self.lab["gateway"], start, end)

    def up(self) -> None:
        br = self.BRIDGE
        run(["ip", "addr", "flush", "dev", self.aps[self.router_name].iface])
        # No spanning tree and no forward delay: a port added by hostapd must pass traffic at once.
        # First lab run (2026-09-29): DHCP requests reached dnsmasq ~15 s after the devices
        # joined (the default forward delay), after every device had already given up.
        run(["ip", "link", "add", br, "type", "bridge", "stp_state", "0", "forward_delay", "0"])
        run(["ip", "addr", "add", self.base_cidr, "dev", br])
        run(["ip", "link", "set", br, "up"])
        run(["sysctl", "-qw", "net.bridge.bridge-nf-call-iptables=0"], check=False)
        self.dnsmasq.start()

    def config(self, security: str = "transition", channel: int | None = None,
               name: str | None = None) -> ApConfig:
        return home_ap(security, channel or self.channels[name or self.router_name], self.ssid,
                       self.passphrase)

    def start(self, name: str, ap: ApConfig, deny_macs: list[str] | None = None,
              **features) -> str:
        """Start (or keep) one AP with these settings; returns its BSSID.
        features: rrm (802.11k), bss_transition (802.11v), ap_isolate (client isolation)."""
        params = {**ap.template_params(), "bridge": self.BRIDGE, "deny_macs": deny_macs or [],
                  **features}
        self.aps[name].ensure(**params)
        return self.bssid(name)

    def start_all(self, security: str = "transition", **features) -> dict[str, str]:
        """Every AP on its own channel with the same name and security; returns name -> BSSID."""
        return {name: self.start(name, self.config(security, name=name), **features)
                for name in self.aps}

    def only_router(self, ap: ApConfig, deny_macs: list[str] | None = None, **features) -> str:
        for name, hostap in self.aps.items():
            if name != self.router_name:
                hostap.stop()
        return self.start(self.router_name, ap, deny_macs, **features)

    def set_neighbors(self) -> dict[str, list[str]]:
        """802.11k: tell every AP about the other APs of the network (what a mesh controller
        does). Returns AP name -> the neighbor BSSIDs it was given."""
        given = {}
        for name, hostap in self.aps.items():
            given[name] = []
            for other in self.aps:
                if other == name or not self.aps[other].enabled():
                    continue
                bssid = self.bssid(other)
                nr = neighbor_element(bssid, self.channels[other])
                hostap.cli("set_neighbor", bssid, f'ssid="{self.ssid}"', f"nr={nr}")
                given[name].append(bssid)
        return given

    def steer(self, name: str, sta_mac: str, target_bssid: str, target_channel: int,
              imminent: bool = False) -> str:
        """802.11v: AP `name` asks the device to move to `target_bssid`. Returns hostapd's answer
        to the command (OK/FAIL); the device's reply arrives later as BSS-TM-RESP in the log.

        imminent: set "disassociation imminent" with a timer of 100 beacons (~10 s): the AP
        will drop the device, so it must leave. Without it the request is a suggestion and the
        device may stay if the target is not clearly better."""
        args = ["bss_tm_req", sta_mac, "pref=1", "abridged=1"]
        if imminent:
            args += ["disassoc_imminent=1", "disassoc_timer=100"]
        args.append(f"neighbor={btm_candidate(target_bssid, target_channel)}")
        return self.aps[name].cli(*args).strip()

    def stop(self, name: str) -> None:
        self.aps[name].stop()

    def bssid(self, name: str) -> str:
        return Path(f"/sys/class/net/{self.aps[name].iface}/address").read_text().strip().lower()

    def ap_for_bssid(self, bssid: str | None) -> str | None:
        return next((n for n in self.aps if bssid and self.bssid(n) == bssid.lower()), None)

    def set_dhcp(self, dhcp: bool = True, dns: bool = True, pool: tuple[str, str] | None = None) -> None:
        """Restart dnsmasq: DHCP/DNS on or off, and optionally a smaller address pool. Leases are
        cleared so earlier tests' devices do not hold addresses."""
        self.dnsmasq.subnets = [self._subnet(*(pool or self.lab["dhcp_range"]))]
        self.dnsmasq.stop()
        (self.dnsmasq.workdir / "dnsmasq.leases").unlink(missing_ok=True)
        # dnsmasq appends to its log; read only what this setting wrote, so an earlier test's
        # "no address available" cannot leak into a later diagnosis.
        self._log_start = self.dnsmasq.log.stat().st_size if self.dnsmasq.log.exists() else 0
        self.dnsmasq.start(dhcp=dhcp, dns=dns)

    def dnsmasq_log(self) -> str:
        log = self.dnsmasq.log
        if not log.exists():
            return ""
        with log.open("rb") as fh:
            fh.seek(getattr(self, "_log_start", 0))
            return fh.read().decode(errors="replace")

    def down(self) -> None:
        self.dnsmasq.stop()
        for hostap in self.aps.values():
            hostap.stop()
        run(["ip", "link", "del", self.BRIDGE], check=False)
        first = self.aps[self.router_name].iface
        run(["ip", "addr", "replace", self.base_cidr, "dev", first], check=False)
        run(["ip", "link", "set", first, "up"], check=False)


def small_pool(first: str, size: int) -> tuple[str, str]:
    """A DHCP range of `size` addresses starting at `first` (to fill it up on purpose)."""
    return first, str(ipaddress.ip_address(first) + size - 1)


def in_parallel(fn, items: dict) -> dict:
    """Run fn(key, value) for every item at the same time; returns key -> result. Each device is
    its own namespace and radio, so joins do not share state (a whole house coming online at
    once is also the realistic case after a power cut)."""
    if not items:
        return {}
    with ThreadPoolExecutor(max_workers=len(items)) as pool:
        futures = {k: pool.submit(fn, k, v) for k, v in items.items()}
        return {k: f.result() for k, f in futures.items()}


if __name__ == "__main__":
    from testbed import inventory

    parser = argparse.ArgumentParser(description="Home network plan")
    parser.add_argument("--plan", action="store_true", help="expected interop results (markdown)")
    parser.parse_args()
    print(interop_plan(inventory.load().home))
