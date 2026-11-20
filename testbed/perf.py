"""Throughput with iperf3: a server on the AP side (root namespace), clients in their namespaces.

In this lab the radios are emulated, so the numbers measure the software path (kernel, hostapd,
CPU), not RF. They are a smoke test and a regression baseline, not a statement about air speed.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from testbed.util import log, wait_for

IPERF_PORT = 5201
# Stamped on every saved result so no number is mistaken for real Wi-Fi performance.
VIRTUAL_NOTE = ("virtual-network measurement (mac80211_hwsim, same VM): reflects the software "
                "path, not RF or real Wi-Fi performance")


@dataclass
class IperfResult:
    direction: str            # "uplink" (client -> AP side) or "downlink" (AP side -> client)
    seconds: float
    mbps: float               # goodput the receiver saw
    retransmits: int | None   # TCP retransmits on the sender; None when iperf3 does not report
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def parse_iperf_json(text: str, direction: str) -> IperfResult:
    """Read `iperf3 -J` output. Receiver-side bits/s is the number that counts."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return IperfResult(direction, 0.0, 0.0, None, error=f"not JSON: {text[:200]!r}")
    if data.get("error"):
        return IperfResult(direction, 0.0, 0.0, None, error=data["error"])
    end = data.get("end", {})
    received = end.get("sum_received", {})
    sent = end.get("sum_sent", {})
    return IperfResult(
        direction=direction,
        seconds=round(received.get("seconds", 0.0), 2),
        mbps=round(received.get("bits_per_second", 0.0) / 1e6, 2),
        retransmits=sent.get("retransmits"),
    )


@dataclass
class UdpResult:
    direction: str
    target_mbps: float        # offered load (-b)
    mbps: float               # what the receiver got
    jitter_ms: float
    lost_percent: float
    error: str | None = None
    sent_mbps: float | None = None  # what the sender managed; less than target = sender-bound

    def to_dict(self) -> dict:
        return asdict(self)


def parse_iperf_udp_json(text: str, direction: str, target_mbps: float) -> UdpResult:
    """Read `iperf3 -u -J` output: jitter and datagram loss matter for voice/video/cameras."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return UdpResult(direction, target_mbps, 0.0, 0.0, 100.0, error=f"not JSON: {text[:200]!r}")
    if data.get("error"):
        return UdpResult(direction, target_mbps, 0.0, 0.0, 100.0, error=data["error"])
    end = data.get("end", {})
    s = end.get("sum", {})
    lost = s.get("lost_percent", 100.0)
    # "sum" is the sender's rate (2026-09-29 VM run: asked 20, sum 19.98 Mbps with 6.69% lost).
    # Received = sum_received when this iperf3 reports it, else the sent rate minus the loss.
    sent = end.get("sum_sent", s).get("bits_per_second", 0.0)
    received = end.get("sum_received", {}).get("bits_per_second", sent * (1 - lost / 100))
    return UdpResult(direction, target_mbps, round(received / 1e6, 2),
                     round(s.get("jitter_ms", 0.0), 3), round(lost, 2),
                     sent_mbps=round(sent / 1e6, 2))


class IperfServer:
    """iperf3 -s bound to one address in the root namespace (the AP / gateway side)."""

    def __init__(self, bind: str, workdir: Path, port: int = IPERF_PORT):
        self.bind = bind
        self.port = port
        self.log = Path(workdir) / "iperf3-server.log"
        self._proc: subprocess.Popen | None = None

    def start(self) -> "IperfServer":
        self.stop()
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self._proc = subprocess.Popen(
            ["iperf3", "-s", "-B", self.bind, "-p", str(self.port), "--logfile", str(self.log)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        )
        if not wait_for(lambda: self._listening() or self._proc.poll() is not None, timeout=5):
            log.warning("iperf3 server on %s:%s did not start listening", self.bind, self.port)
        if self._proc.poll() is not None:
            # With --logfile, iperf3 writes its errors to the log, not stderr (first home run,
            # 2026-09-29: the error was empty). Also name what is already on the port.
            why = self._proc.stderr.read().strip()
            if self.log.exists():
                why = (why + " " + self.log.read_text(errors="replace").strip()[-300:]).strip()
            users = subprocess.run(["ss", "-ltnp", f"sport = :{self.port}"], capture_output=True,
                                   text=True).stdout.strip().splitlines()[1:]
            if users:
                why += f" | already listening on port {self.port}: {' '.join(users)[:200]}"
            raise RuntimeError(f"iperf3 server on {self.bind}:{self.port} exited: {why or 'no message'}")
        return self

    def _listening(self) -> bool:
        out = subprocess.run(["ss", "-ltn"], capture_output=True, text=True).stdout
        return f"{self.bind}:{self.port}" in out

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
