"""Packet capture on hwsim0, which sees every emulated 802.11 frame (with radiotap headers)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from testbed.util import log, wait_for


class Capture:
    def __init__(self, pcap: Path, iface: str = "hwsim0"):
        self.pcap = Path(pcap)
        self.iface = iface
        self._proc: subprocess.Popen | None = None

    def start(self) -> "Capture":
        self.pcap.parent.mkdir(parents=True, exist_ok=True)
        self.pcap.unlink(missing_ok=True)
        # dumpcap is what tshark uses underneath; -P writes pcap (not pcapng) for pyshark/tools.
        self._proc = subprocess.Popen(
            ["dumpcap", "-q", "-P", "-i", self.iface, "-w", str(self.pcap)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        )
        if not wait_for(lambda: self.pcap.exists() or self._proc.poll() is not None, timeout=5):
            log.warning("capture file %s did not appear", self.pcap)
        if self._proc.poll() is not None:
            raise RuntimeError(f"dumpcap exited: {self._proc.stderr.read()}")
        return self

    def stop(self) -> Path:
        """Stop the capture (idempotent) and return the pcap path."""
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
        return self.pcap

    def __enter__(self) -> "Capture":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
