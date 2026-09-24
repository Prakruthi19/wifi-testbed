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


def parse_wifi_connected(status_text: str) -> str | None:
    """SSID from `cmd wifi status` ("Wifi is connected to "AndroidWifi""), else None."""
    m = re.search(r'Wifi is connected to "?([^"\n]+)"?', status_text)
    return m.group(1) if m else None


def parse_wifi_enabled(status_text: str) -> bool:
    return "Wifi is enabled" in status_text


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

    def logcat_wifi(self, max_lines: int = 2000) -> str:
        filters = [f"{tag}:V" for tag in WIFI_LOG_TAGS] + ["*:S"]
        return self.run("logcat", "-d", "-v", "threadtime", "-t", str(max_lines), *filters,
                        check=False, timeout=60)
