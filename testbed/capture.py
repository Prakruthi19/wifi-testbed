"""Packet capture on hwsim0, which sees every emulated 802.11 frame (with radiotap headers)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from testbed.util import log, wait_for

SPOOL_DIR = Path("/run/testbed/captures")


class Capture:
    def __init__(self, pcap: Path, iface: str = "hwsim0"):
        self.pcap = Path(pcap)
        self.iface = iface
        self._proc: subprocess.Popen | None = None
        self._spool: Path | None = None

    def start(self) -> "Capture":
        self.pcap.parent.mkdir(parents=True, exist_ok=True)
        self.pcap.unlink(missing_ok=True)
        # dumpcap drops every privilege except capture right after opening the interface, so as
        # "root without powers" it cannot write under a 750 home directory. It writes to a
        # root-owned spool dir instead and stop() moves the file into place.
        SPOOL_DIR.mkdir(parents=True, exist_ok=True)
        SPOOL_DIR.chmod(0o755)
        self._spool = SPOOL_DIR / f"{os.getpid()}-{id(self)}.pcap"
        self._spool.unlink(missing_ok=True)
        # dumpcap is what tshark uses underneath; -P writes pcap (not pcapng) for pyshark/tools.
        self._proc = subprocess.Popen(
            ["dumpcap", "-q", "-P", "-i", self.iface, "-w", str(self._spool)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        )
        if not wait_for(lambda: self._spool.exists() or self._proc.poll() is not None, timeout=5):
            log.warning("capture file %s did not appear", self._spool)
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
        if self._spool and self._spool.exists():
            shutil.move(str(self._spool), self.pcap)
        self._spool = None
        return self.pcap

    def __enter__(self) -> "Capture":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
