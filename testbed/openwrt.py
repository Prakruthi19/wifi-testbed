"""Drive a real OpenWrt access point over SSH with the same ApConfig the emulated lab uses.

DESIGNED, NOT RUN: written without an OpenWrt device. The uci option names follow OpenWrt 21.02+
(wireless.<radio>.band, wireless.<iface>.encryption/key/ieee80211w); check them against the
router's /etc/config/wireless before trusting a run. Unit tests cover the command generation.

    ap = OpenWrtAP("192.168.1.1")
    ap.apply(ApConfig("wpa3", 2, 36, ssid="lab-wpa3", passphrase="labpassword123"))
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass

from testbed.matrix import ApConfig

# ApConfig.security -> OpenWrt `encryption` (CCMP is the default cipher for psk2/sae).
ENCRYPTION = {"open": "none", "wpa2": "psk2", "wpa3": "sae", "transition": "sae-mixed"}
BAND = {"g": "2g", "a": "5g"}


@dataclass
class OpenWrtAP:
    host: str
    user: str = "root"
    radio: str = "radio0"          # wifi-device section (the physical radio)
    iface: str = "default_radio0"  # wifi-iface section (the SSID on that radio)

    def uci_commands(self, ap: ApConfig) -> list[str]:
        w = "wireless"
        cmds = [
            f"uci set {w}.{self.radio}.disabled=0",
            f"uci set {w}.{self.radio}.band={BAND[ap.hw_mode]}",
            f"uci set {w}.{self.radio}.channel={ap.channel}",
            f"uci set {w}.{self.iface}.mode=ap",
            f"uci set {w}.{self.iface}.ssid={shlex.quote(ap.ssid)}",
            f"uci set {w}.{self.iface}.encryption={ENCRYPTION[ap.security]}",
            f"uci set {w}.{self.iface}.ieee80211w={ap.pmf}",
        ]
        if ap.security == "open":
            cmds.append(f"uci -q delete {w}.{self.iface}.key || true")
        else:
            cmds.append(f"uci set {w}.{self.iface}.key={shlex.quote(ap.passphrase)}")
        cmds += [f"uci commit {w}", "wifi reload"]
        return cmds

    def ssh(self, command: str, timeout: float = 60) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", f"{self.user}@{self.host}",
             command], capture_output=True, text=True, timeout=timeout, check=True)

    def apply(self, ap: ApConfig) -> None:
        """Push the config and reload Wi-Fi. The BSS is down for a few seconds during reload."""
        self.ssh(" && ".join(self.uci_commands(ap)))

    def status(self) -> str:
        """`iwinfo` output: SSID, channel, encryption as the radio actually runs them."""
        return self.ssh("iwinfo").stdout
