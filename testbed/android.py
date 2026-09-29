"""ADB wrapper for the Android Emulator. Every command goes through Adb.run so it is logged."""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from testbed.util import wait_for

WIFI_LOG_TAGS = [
    "WifiService", "WifiClientModeImpl", "WifiConnectivityManager", "WifiNetworkFactory",
    "SupplicantStaIfaceHal", "wpa_supplicant", "ConnectivityService", "NetworkMonitor",
]

_WIFI_INFO = re.compile(
    r'SSID: "?(?P<ssid>[^",]*)"?,.*?RSSI: (?P<rssi>-?\d+),\s*Link speed: (?P<speed>-?\d+)\s*Mbps',
    re.S,
)


@dataclass
class WifiInfo:
    ssid: str
    rssi_dbm: int
    link_speed_mbps: int


def parse_wifi_info(text: str) -> WifiInfo | None:
    """Parse the first WifiInfo line from `dumpsys wifi` or `cmd wifi status`."""
    for line in text.splitlines():
        if "SSID:" in line and "RSSI:" in line:
            m = _WIFI_INFO.search(line)
            if m:
                return WifiInfo(m["ssid"], int(m["rssi"]), int(m["speed"]))
    return None


def parse_wifi_mac(text: str) -> str | None:
    """MAC the phone uses on the current network, from the WifiInfo line of `dumpsys wifi`."""
    m = re.search(r"\bMAC: ([0-9a-f]{2}(?::[0-9a-f]{2}){5})", text, re.I)
    return m.group(1).lower() if m else None


def is_randomized_mac(mac: str) -> bool:
    """Locally administered bit (0x02 in the first byte) set: a randomized, not factory, MAC.

    Android 10+ uses a random per-network MAC by default, which breaks MAC allow/deny lists and
    DHCP reservations keyed on the factory address.
    """
    return bool(int(mac.split(":")[0], 16) & 0x02)


def parse_wifi_connected(status_text: str) -> str | None:
    """SSID from `cmd wifi status` ("Wifi is connected to "AndroidWifi""), else None."""
    m = re.search(r'Wifi is connected to "?([^"\n]+)"?', status_text)
    return m.group(1) if m else None


def parse_wifi_enabled(status_text: str) -> bool:
    return "Wifi is enabled" in status_text


@dataclass
class SavedNetwork:
    network_id: int
    ssid: str
    security: str


def parse_saved_networks(text: str) -> list[SavedNetwork]:
    """Rows of `cmd wifi list-networks`: "<id>  <ssid>  <security type>" under a header line."""
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0].isdigit():
            out.append(SavedNetwork(int(parts[0]), " ".join(parts[1:-1]), parts[-1]))
    return out


def phone_join_stage(logcat_text: str) -> str | None:
    """Where a phone's join stopped, from the wpa_supplicant lines in its logcat.

    Android runs the same wpa_supplicant as the lab clients, so the same events show up
    (tag wpa_supplicant). None means CTRL-EVENT-CONNECTED was seen. The mapping mirrors
    testbed.client.supplicant_stage and is a hypothesis until checked on a real phone.
    """
    if "CTRL-EVENT-CONNECTED" in logcat_text:
        return None
    if "CTRL-EVENT-AUTH-REJECT" in logcat_text:
        return "authentication"
    if "CTRL-EVENT-ASSOC-REJECT" in logcat_text:
        return "association"
    if "4-Way Handshake failed" in logcat_text or "reason=WRONG_KEY" in logcat_text:
        return "key_exchange"
    if "reason=AUTH_FAILED" in logcat_text:
        return "authentication"
    if "Trying to associate" not in logcat_text and "Trying to authenticate" not in logcat_text:
        return "network_selection"
    return "undetermined"


@dataclass
class Adb:
    serial: str | None = None
    adb_path: str = "adb"
    transcript: list[str] = field(default_factory=list)

    @staticmethod
    def available() -> bool:
        return shutil.which("adb") is not None

    def run(self, *args: str, timeout: float = 30, check: bool = True) -> str:
        cmd = [self.adb_path] + (["-s", self.serial] if self.serial else []) + list(args)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (proc.stdout + proc.stderr).strip()
        self.transcript.append(f"$ {shlex.join(cmd)}  [rc={proc.returncode}]\n{out}")
        if check and proc.returncode != 0:
            raise RuntimeError(f"adb failed: {shlex.join(cmd)}\n{out}")
        return proc.stdout

    def shell(self, command: str, **kw) -> str:
        return self.run("shell", command, **kw)

    def save_transcript(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n\n".join(self.transcript))
        return path

    # -- device ----------------------------------------------------------------------------
    def devices(self) -> list[str]:
        out = self.run("devices", check=False)
        return [l.split()[0] for l in out.splitlines()[1:] if l.strip().endswith("device")]

    def wait_boot(self, timeout: float = 120) -> bool:
        self.run("wait-for-device", timeout=timeout)
        return bool(wait_for(
            lambda: self.shell("getprop sys.boot_completed", check=False).strip() == "1",
            timeout=timeout, interval=1))

    def is_emulator(self) -> bool:
        return self.shell("getprop ro.kernel.qemu", check=False).strip() == "1" or \
            (self.serial or "").startswith("emulator-")

    # -- Wi-Fi -----------------------------------------------------------------------------
    def wifi_status(self) -> str:
        return self.shell("cmd wifi status")

    def set_wifi_enabled(self, enabled: bool) -> None:
        self.shell(f"cmd wifi set-wifi-enabled {'enabled' if enabled else 'disabled'}")

    def wifi_enabled(self) -> bool:
        return parse_wifi_enabled(self.wifi_status())

    def connected_ssid(self) -> str | None:
        return parse_wifi_connected(self.wifi_status())

    def dumpsys_wifi(self) -> str:
        return self.shell("dumpsys wifi", timeout=60)

    def ping(self, host: str, count: int = 1, timeout_s: int = 2) -> bool:
        out = self.shell(f"ping -c {count} -W {timeout_s} {host}; echo rc=$?", check=False)
        return "rc=0" in out

    def wait_connected(self, ping_host: str, timeout: float = 60) -> float | None:
        """Seconds until Wi-Fi reports connected and a ping succeeds, or None on timeout."""
        start = time.monotonic()
        ok = wait_for(lambda: self.connected_ssid() and self.ping(ping_host), timeout=timeout,
                      interval=0.5)
        return round(time.monotonic() - start, 2) if ok else None

    def connect_network(self, ssid: str, security: str = "wpa2", password: str | None = None) -> None:
        """Join a network by command. security: open, owe, wpa2 or wpa3 (Android 11+)."""
        cmd = f"cmd wifi connect-network {shlex.quote(ssid)} {security}"
        if password is not None:
            cmd += f" {shlex.quote(password)}"
        self.shell(cmd)

    def list_networks(self) -> list[SavedNetwork]:
        return parse_saved_networks(self.shell("cmd wifi list-networks", check=False))

    def forget_network(self, ssid: str) -> int:
        """Forget every saved network with this SSID; returns how many were removed."""
        saved = [n for n in self.list_networks() if n.ssid.strip('"') == ssid]
        for n in saved:
            self.shell(f"cmd wifi forget-network {n.network_id}", check=False)
        return len(saved)

    def set_verbose_logging(self, enabled: bool) -> None:
        """Wi-Fi verbose logging: more wpa_supplicant/framework detail in logcat."""
        self.shell(f"cmd wifi set-verbose-logging {'enabled' if enabled else 'disabled'}",
                   check=False)

    def set_airplane_mode(self, enabled: bool) -> None:
        self.shell(f"cmd connectivity airplane-mode {'enable' if enabled else 'disable'}")

    def airplane_mode(self) -> bool:
        return self.shell("settings get global airplane_mode_on").strip() == "1"

    # -- emulator console (adb emu ...) ----------------------------------------------------
    def emu_network(self, delay: str = "none", speed: str = "full") -> None:
        """Emulator network shaping, e.g. delay='gprs' speed='edge'. Restore with defaults."""
        self.run("emu", "network", "delay", delay)
        self.run("emu", "network", "speed", speed)

    # -- evidence --------------------------------------------------------------------------
    def logcat_clear(self) -> None:
        self.run("logcat", "-c", check=False)

    def screenshot(self, dest: Path) -> Path:
        """PNG of the phone screen (e.g. the Wi-Fi settings page when a join fails)."""
        cmd = [self.adb_path] + (["-s", self.serial] if self.serial else []) + [
            "exec-out", "screencap", "-p"]
        proc = subprocess.run(cmd, capture_output=True, timeout=30)
        self.transcript.append(f"$ {shlex.join(cmd)}  [rc={proc.returncode}] {len(proc.stdout)} bytes")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(proc.stdout)
        return dest

    def open_wifi_settings(self) -> None:
        self.shell("am start -a android.settings.WIFI_SETTINGS", check=False)

    def bugreport(self, dest: Path, timeout: float = 600) -> Path:
        """Full `adb bugreport` zip (logs + system state), the usual attachment for Android bugs."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        self.run("bugreport", str(dest), timeout=timeout)
        return dest

    def logcat_wifi(self, max_lines: int = 2000) -> str:
        filters = [f"{tag}:V" for tag in WIFI_LOG_TAGS] + ["*:S"]
        return self.run("logcat", "-d", "-v", "threadtime", "-t", str(max_lines), *filters,
                        check=False, timeout=60)
