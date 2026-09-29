"""Wi-Fi client in its own network namespace: join, measure, collect logs."""

from __future__ import annotations

import re
import shutil
import signal
import statistics
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from testbed.perf import IperfResult, UdpResult, parse_iperf_json, parse_iperf_udp_json
from testbed.util import ns_prefix, render, run, wait_for

STAGES = ("network_selection", "authentication", "association", "eap", "key_exchange", "dhcp", "dns",
          "ping")

_TS = r"^(?P<ts>\d+\.\d+): "
_RE_AUTH_START = re.compile(_TS + r".*Trying to authenticate with", re.M)
_RE_ASSOC_START = re.compile(_TS + r".*Trying to associate with", re.M)
_RE_ASSOCIATED = re.compile(_TS + r".*Associated with", re.M)
_RE_CONNECTED = re.compile(_TS + r".*CTRL-EVENT-CONNECTED", re.M)
# Written only because wpa_supplicant runs with -K (log keys); without it the bytes are [REMOVED].
# SAE: WPA3-Personal. "PMK from EAPOL state machines": 802.1X. Last match = current session.
# Both formats confirmed in real logs on Ubuntu 24.04 (2026-09-28); the 802.1X one says
# "machines" in that build, so accept either spelling.
_RE_PMK = re.compile(r"(?:SAE: PMK|WPA: PMK from EAPOL state machines?) - hexdump\(len=(\d+)\): "
                     r"((?:[0-9a-f]{2} ?)+)")


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
    if "CTRL-EVENT-EAP-FAILURE" in log_text or "CTRL-EVENT-EAP-TLS-CERT-ERROR" in log_text:
        return "eap"
    if "4-Way Handshake failed" in log_text:
        return "key_exchange"
    if "CTRL-EVENT-EAP-STARTED" in log_text and "CTRL-EVENT-EAP-SUCCESS" not in log_text:
        return "eap"  # the login began and never finished (server silent, or client gave up)
    if not _RE_AUTH_START.search(log_text):
        # The supplicant never picked the BSS: no common AKM, PMF mismatch, or not found.
        return "network_selection"
    if not _RE_ASSOC_START.search(log_text):
        return "authentication"
    if not _RE_ASSOCIATED.search(log_text):
        return "association"
    return "key_exchange"


def session_pmk(log_text: str) -> str | None:
    """The PMK of the latest WPA3-SAE or 802.1X session, as hex, from a wpa_supplicant -K log.

    WPA2-PSK does not need this (the passphrase + SSID give the PMK). SAE and EAP make a new PMK
    every session, so the capture can only be decrypted with that session's PMK.
    """
    matches = _RE_PMK.findall(log_text)
    if not matches:
        return None
    length, hexbytes = matches[-1]
    pmk = hexbytes.replace(" ", "")
    return pmk if len(pmk) == 2 * int(length) else None


def parse_signal_poll(text: str) -> dict:
    """`wpa_cli signal_poll` -> {"rssi_dbm": -52, "link_mbps": 866.7, "freq_mhz": 5180}."""
    kv = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    out = {}
    if kv.get("RSSI", "").lstrip("-").isdigit():
        out["rssi_dbm"] = int(kv["RSSI"])
    if "LINKSPEED" in kv:
        out["link_mbps"] = float(kv["LINKSPEED"])
    if kv.get("FREQUENCY", "").isdigit():
        out["freq_mhz"] = int(kv["FREQUENCY"])
    return out


def parse_ping(text: str) -> dict:
    """`ping` summary -> {"sent", "received", "loss_percent", "rtt_min_ms", "rtt_avg_ms",
    "rtt_max_ms", "rtt_mdev_ms"}; rtt keys are missing when nothing came back."""
    out = {}
    m = re.search(r"(\d+) packets transmitted, (\d+) (?:packets )?received.*?([\d.]+)% packet loss", text)
    if m:
        out.update(sent=int(m[1]), received=int(m[2]), loss_percent=float(m[3]))
    m = re.search(r"= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms", text)
    if m:
        out.update(rtt_min_ms=float(m[1]), rtt_avg_ms=float(m[2]), rtt_max_ms=float(m[3]),
                   rtt_mdev_ms=float(m[4]))
    return out


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

    def wpa_cli(self, *args: str, timeout: float = 5) -> str:
        return self.sh("wpa_cli", "-p", str(self.ctrl_dir), "-i", self.iface, *args,
                       check=False, timeout=timeout).stdout

    def wpa_status(self) -> dict[str, str]:
        out = self.wpa_cli("status")
        return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)

    def signal_poll(self) -> dict:
        """RSSI and link rate the driver reports now (wpa_cli signal_poll); {} when not connected."""
        proc = self.sh("wpa_cli", "-p", str(self.ctrl_dir), "-i", self.iface, "signal_poll",
                       check=False, timeout=5)
        return parse_signal_poll(proc.stdout)

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
            try:
                self.sh("dhclient", "-x", "-pf", str(pid_file), self.iface, check=False, timeout=10)
            except subprocess.TimeoutExpired:
                pass  # a stuck dhclient is killed just below; cleanup must not fail the test
        # First lab run of the new suites (2026-09-28) left one dhclient per successful join
        # running after -x, so make sure: match this client's interface only.
        self.sh("pkill", "-f", f"dhclient .*{self.iface}$", check=False)
        self.sh("pkill", "-f", f"wpa_supplicant.*-i {self.iface}", check=False)
        self.sh("ip", "addr", "flush", "dev", self.iface, check=False)
        wait_for(lambda: not self.wpa_status(), timeout=3)
        # Reset the radio. In a combined run (2026-09-28) a join stopped mid-authentication
        # (mac_blocked) left sta1 answering every later scan with EBUSY (-16), so every test
        # after it "never found the network". Down/up drops any half-finished scan or auth.
        self.sh("ip", "link", "set", self.iface, "down", check=False)
        self.sh("ip", "link", "set", self.iface, "up", check=False)

    def associate(self, ssid: str, key_mgmt: str, ieee80211w: int = 0, psk: str | None = None,
                  sae_password: str | None = None, freq_list: str | None = None,
                  eap: dict | None = None, timeout: float = 15) -> tuple[bool, Path]:
        """Start wpa_supplicant and wait for wpa_state=COMPLETED. Returns (connected, log path).

        eap: 802.1X settings for key_mgmt=WPA-EAP, see testbed.eap.client_settings.
        The log includes key material (-K) so WPA3/802.1X captures can be decrypted afterwards.
        """
        self.disconnect()
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.ctrl_dir.mkdir(parents=True, exist_ok=True)
        conf = self.workdir / f"wpa_supplicant-{self.name}.conf"
        log = self.workdir / f"wpa_supplicant-{self.name}.log"
        log.unlink(missing_ok=True)
        render("wpa_supplicant/client.conf.j2", conf, ctrl_dir=self.ctrl_dir,
               country_code=self.country_code, ssid=ssid, key_mgmt=key_mgmt,
               ieee80211w=ieee80211w, psk=psk, sae_password=sae_password, freq_list=freq_list,
               eap=eap)
        self.sh("wpa_supplicant", "-B", "-D", "nl80211", "-i", self.iface, "-c", str(conf),
                "-t", "-dd", "-K", "-f", str(log))
        connected = bool(wait_for(lambda: self.wpa_status().get("wpa_state") == "COMPLETED",
                                  timeout=timeout, interval=0.05))
        return connected, log

    # -- roaming -----------------------------------------------------------------------------
    def current_bssid(self) -> str | None:
        status = self.wpa_status()
        return status.get("bssid") if status.get("wpa_state") == "COMPLETED" else None

    def scan_for(self, bssid: str, flag: str | None = None, timeout: float = 10,
                 flush: bool = True) -> bool:
        """Fresh scan until `bssid` is listed (and its flags contain `flag`, e.g. "FT/PSK").

        Old entries are flushed first: a BSS remembered from an earlier test with other security
        settings makes the client pick the wrong key management, and the 4-way handshake then
        fails because the AP's real RSN IE doesn't match the remembered one (seen in the first
        lab run of test_roam[ft], 2026-09-28). flush=False keeps entries already found, to
        look for several APs in a row.
        """
        if flush:
            self.wpa_cli("bss_flush", "0")

        def listed() -> bool:
            for line in self.wpa_cli("scan_results").lower().splitlines():
                if line.startswith(bssid.lower()) and (flag is None or flag.lower() in line):
                    return True
            self.wpa_cli("scan")
            return False

        return bool(wait_for(listed, timeout=timeout, interval=1))

    def roam(self, bssid: str, timeout: float = 10) -> bool:
        """Move to another AP of the same network (`wpa_cli roam`). With FT-PSK in key_mgmt and
        802.11r on the APs this is a Fast Transition; otherwise a full re-authentication."""
        self.wpa_cli("roam", bssid)
        return bool(wait_for(lambda: (self.current_bssid() or "").lower() == bssid.lower(),
                             timeout=timeout, interval=0.02))

    def start_ping(self, target: str, interval: float = 0.05) -> subprocess.Popen:
        """Background ping (root allows intervals under 0.2 s); stop it with stop_ping."""
        return subprocess.Popen(ns_prefix(self.namespace) + ["ping", "-i", str(interval), "-W", "1",
                                                             target],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    @staticmethod
    def stop_ping(proc: subprocess.Popen) -> dict:
        proc.send_signal(signal.SIGINT)  # ping prints its summary on Ctrl-C
        try:
            out, _ = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
        return parse_ping(out)

    def dhcp(self, timeout: float = 10) -> tuple[str | None, float]:
        conf = self.workdir / "dhclient.conf"
        conf.write_text(f"timeout {int(timeout)};\nretry 1;\n")
        leases = self.workdir / "dhclient.leases"
        # A lease left over from an earlier join would let dhclient "succeed" with no server.
        leases.unlink(missing_ok=True)
        start = time.monotonic()
        try:
            proc = self.sh("dhclient", "-1", "-v", "-cf", str(conf), "-pf", str(self.workdir / "dhclient.pid"),
                           "-lf", str(leases), self.iface, check=False, timeout=timeout + 5)
            out = (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired as e:
            # No DHCP server answered and dhclient kept retrying; the caller sees ip=None.
            out = "".join(x.decode(errors="replace") if isinstance(x, bytes) else (x or "")
                          for x in (e.stdout, e.stderr)) + "\n(timed out)\n"
        elapsed = round((time.monotonic() - start) * 1000, 1)
        # dhclient -v lists every DISCOVER/OFFER/REQUEST/ACK it sent or got, with times: the
        # client's side of a DHCP failure (the server's side is in dnsmasq.log).
        (self.workdir / "dhclient.log").write_text(
            time.strftime("%H:%M:%S started\n", time.localtime(time.time() - elapsed / 1000)) + out)
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

    def ping_stats(self, target: str, count: int = 20, interval: float = 0.2) -> dict:
        """Latency and loss: round-trip min/avg/max/mdev (mdev is ping's jitter figure)."""
        proc = self.sh("ping", "-c", str(count), "-i", str(interval), "-W", "1", target,
                       check=False, timeout=count * interval + 10)
        return parse_ping(proc.stdout)

    def tcp_connect(self, target: str, port: int, timeout: float = 2) -> bool:
        return self.sh("nc", "-z", "-w", str(int(timeout)), target, str(port),
                       check=False, timeout=timeout + 5).returncode == 0

    def iperf(self, server: str, seconds: int = 5, reverse: bool = False,
              port: int = 5201, streams: int = 1) -> IperfResult:
        """One iperf3 TCP run to `server`. reverse=True measures downlink (server -> client)."""
        direction = "downlink" if reverse else "uplink"
        cmd = ["iperf3", "-c", server, "-p", str(port), "-t", str(seconds), "-P", str(streams),
               "-J"]
        if reverse:
            cmd.append("-R")
        try:
            proc = self.sh(*cmd, check=False, timeout=seconds + 15)
        except subprocess.TimeoutExpired:
            return IperfResult(direction, 0.0, 0.0, None, error="iperf3 client timed out")
        return parse_iperf_json(proc.stdout, direction)

    def iperf_udp(self, server: str, mbps: float = 20, seconds: int = 5, reverse: bool = False,
                  port: int = 5201) -> UdpResult:
        """One iperf3 UDP run at a fixed offered load; reports jitter and datagram loss."""
        direction = "downlink" if reverse else "uplink"
        cmd = ["iperf3", "-c", server, "-p", str(port), "-u", "-b", f"{mbps:g}M",
               "-t", str(seconds), "-J"]
        if reverse:
            cmd.append("-R")
        try:
            proc = self.sh(*cmd, check=False, timeout=seconds + 15)
        except subprocess.TimeoutExpired:
            return UdpResult(direction, mbps, 0.0, 0.0, 100.0, error="iperf3 client timed out")
        return parse_iperf_udp_json(proc.stdout, direction, mbps)

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
        if artifacts and (self.workdir / "dhclient.log").exists():
            shutil.copy(self.workdir / "dhclient.log", artifacts / "dhclient.log")
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
