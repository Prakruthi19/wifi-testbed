"""Wi-Fi client in its own network namespace: join, measure, collect logs."""

from __future__ import annotations

import re
import shutil
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from testbed.util import render, run, wait_for

STAGES = ("network_selection", "authentication", "association", "key_exchange", "dhcp", "dns", "ping")

_TS = r"^(?P<ts>\d+\.\d+): "
_RE_AUTH_START = re.compile(_TS + r".*Trying to authenticate with", re.M)
_RE_ASSOC_START = re.compile(_TS + r".*Trying to associate with", re.M)
_RE_ASSOCIATED = re.compile(_TS + r".*Associated with", re.M)
_RE_CONNECTED = re.compile(_TS + r".*CTRL-EVENT-CONNECTED", re.M)


@dataclass
class JoinResult:
    passed: bool
    failed_stage: str | None = None
    assoc_ms: float | None = None
    dhcp_ms: float | None = None
    dns_ms: float | None = None
    dns_ok: bool | None = None
    ping_ok: bool | None = None
    ip: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def supplicant_stage(log_text: str) -> str | None:
    """Infer where a join stopped from a wpa_supplicant -dd -t log. None means it connected."""
    if _RE_CONNECTED.search(log_text):
        return None
    if "CTRL-EVENT-AUTH-REJECT" in log_text:
        return "authentication"
    if "CTRL-EVENT-ASSOC-REJECT" in log_text:
        return "association"
    if "4-Way Handshake failed" in log_text:
        return "key_exchange"
    if not _RE_AUTH_START.search(log_text):
        # The supplicant never picked the BSS: no common AKM, PMF mismatch, or not found.
        return "network_selection"
    if not _RE_ASSOC_START.search(log_text):
        return "authentication"
    if not _RE_ASSOCIATED.search(log_text):
        return "association"
    return "key_exchange"


def assoc_time_ms(log_text: str) -> float | None:
    """Time from the first authentication attempt to CTRL-EVENT-CONNECTED (auth + assoc + 4-way)."""
    start, done = _RE_AUTH_START.search(log_text), _RE_CONNECTED.search(log_text)
    if not (start and done):
        return None
    return round((float(done["ts"]) - float(start["ts"])) * 1000, 1)


def summarize(results: list[JoinResult]) -> dict:
    """Pass rate and median join time over repeated joins."""
    times = [r.assoc_ms for r in results if r.passed and r.assoc_ms is not None]
    stages = sorted({r.failed_stage for r in results if r.failed_stage})
    return {
        "attempts": len(results),
        "pass_rate": sum(r.passed for r in results) / len(results) if results else 0.0,
        "median_join_ms": statistics.median(times) if times else None,
        "median_dhcp_ms": statistics.median([r.dhcp_ms for r in results if r.dhcp_ms]) if any(
            r.dhcp_ms for r in results) else None,
        "failed_stages": stages,
    }


class WifiClient:
    def __init__(self, name: str, iface: str, namespace: str, workdir: Path, country_code: str = "US"):
        self.name = name
        self.iface = iface
        self.namespace = namespace
        self.workdir = Path(workdir)
        self.country_code = country_code
        self.ctrl_dir = Path(f"/run/testbed/wpas-{name}")

    # -- helpers ---------------------------------------------------------------------------
    def sh(self, *cmd: str, check: bool = True, timeout: float = 30):
        return run(list(cmd), namespace=self.namespace, check=check, timeout=timeout)

    @property
    def mac(self) -> str:
        return self.sh("cat", f"/sys/class/net/{self.iface}/address").stdout.strip()

    def wpa_status(self) -> dict[str, str]:
        proc = self.sh("wpa_cli", "-p", str(self.ctrl_dir), "-i", self.iface, "status",
                       check=False, timeout=5)
        return dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)

    def ipv4(self) -> str | None:
        out = self.sh("ip", "-4", "-o", "addr", "show", "dev", self.iface, check=False).stdout
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out)
        return m.group(1) if m else None

    # -- lifecycle -------------------------------------------------------------------------
    def disconnect(self) -> None:
        self.sh("wpa_cli", "-p", str(self.ctrl_dir), "-i", self.iface, "terminate",
                check=False, timeout=5)
        pid_file = self.workdir / "dhclient.pid"
        if pid_file.exists():
            self.sh("dhclient", "-x", "-pf", str(pid_file), self.iface, check=False, timeout=10)
        self.sh("pkill", "-f", f"wpa_supplicant.*-i {self.iface}", check=False)
        self.sh("ip", "addr", "flush", "dev", self.iface, check=False)
        wait_for(lambda: not self.wpa_status(), timeout=3)

    def associate(self, ssid: str, key_mgmt: str, ieee80211w: int = 0, psk: str | None = None,
                  sae_password: str | None = None, timeout: float = 15) -> tuple[bool, Path]:
        """Start wpa_supplicant and wait for wpa_state=COMPLETED. Returns (connected, log path)."""
        self.disconnect()
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.ctrl_dir.mkdir(parents=True, exist_ok=True)
        conf = self.workdir / f"wpa_supplicant-{self.name}.conf"
        log = self.workdir / f"wpa_supplicant-{self.name}.log"
        log.unlink(missing_ok=True)
        render("wpa_supplicant/client.conf.j2", conf, ctrl_dir=self.ctrl_dir,
               country_code=self.country_code, ssid=ssid, key_mgmt=key_mgmt,
               ieee80211w=ieee80211w, psk=psk, sae_password=sae_password)
        self.sh("wpa_supplicant", "-B", "-D", "nl80211", "-i", self.iface, "-c", str(conf),
                "-t", "-dd", "-f", str(log))
        connected = bool(wait_for(lambda: self.wpa_status().get("wpa_state") == "COMPLETED",
                                  timeout=timeout, interval=0.05))
        return connected, log

    def dhcp(self, timeout: float = 10) -> tuple[str | None, float]:
        conf = self.workdir / "dhclient.conf"
        conf.write_text(f"timeout {int(timeout)};\nretry 1;\n")
        start = time.monotonic()
        self.sh("dhclient", "-1", "-v", "-cf", str(conf), "-pf", str(self.workdir / "dhclient.pid"),
                "-lf", str(self.workdir / "dhclient.leases"), self.iface,
                check=False, timeout=timeout + 5)
        elapsed = round((time.monotonic() - start) * 1000, 1)
        return self.ipv4(), elapsed

    def resolve(self, server: str, name: str, timeout: float = 2) -> tuple[list[str], float]:
        start = time.monotonic()
        proc = self.sh("dig", "+short", f"+time={int(timeout)}", "+tries=1", f"@{server}", name,
                       check=False, timeout=timeout + 5)
        elapsed = round((time.monotonic() - start) * 1000, 1)
        answers = [a for a in proc.stdout.split() if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", a)]
        return answers, elapsed

    def ping(self, target: str, count: int = 3) -> bool:
        return self.sh("ping", "-c", str(count), "-i", "0.2", "-W", "1", target,
                       check=False, timeout=count + 5).returncode == 0

    def tcp_connect(self, target: str, port: int, timeout: float = 2) -> bool:
        return self.sh("nc", "-z", "-w", str(int(timeout)), target, str(port),
                       check=False, timeout=timeout + 5).returncode == 0

    # -- the full join ---------------------------------------------------------------------
    def join(self, ssid: str, network: dict, gateway: str | None = None,
             dns_name: str | None = None, dns_expect: str | None = None,
             artifacts: Path | None = None, assoc_timeout: float = 15) -> JoinResult:
        """Associate, then DHCP, DNS and ping. Stops at the first failing stage."""
        connected, log = self.associate(ssid, timeout=assoc_timeout, **network)
        log_text = log.read_text(errors="replace") if log.exists() else ""
        if artifacts and log.exists():
            artifacts.mkdir(parents=True, exist_ok=True)
            shutil.copy(log, artifacts / log.name)
        result = JoinResult(passed=False, assoc_ms=assoc_time_ms(log_text))
        if not connected:
            result.failed_stage = supplicant_stage(log_text) or "network_selection"
            return result

        ip, result.dhcp_ms = self.dhcp()
        result.ip = ip
        if not ip:
            result.failed_stage = "dhcp"
            return result

        if gateway and dns_name:
            answers, result.dns_ms = self.resolve(gateway, dns_name)
            result.dns_ok = bool(answers) and (dns_expect is None or dns_expect in answers)
            if not result.dns_ok:
                result.failed_stage = "dns"
                result.notes.append(f"dig {dns_name} @{gateway} -> {answers or 'no answer'}")
                return result

        if gateway:
            result.ping_ok = self.ping(gateway)
            if not result.ping_ok:
                result.failed_stage = "ping"
                return result

        result.passed = True
        return result
