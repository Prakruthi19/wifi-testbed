"""Start and stop hostapd with a rendered config."""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path

from testbed.util import log, render, run, wait_for


class HostapdError(RuntimeError):
    pass


class HostAP:
    def __init__(self, iface: str, workdir: Path, country_code: str = "US"):
        self.iface = iface
        self.workdir = Path(workdir)
        self.country_code = country_code
        self.ctrl_dir = Path("/run/testbed/hostapd")
        self.conf = self.workdir / "hostapd.conf"
        self.log = self.workdir / "hostapd.log"
        self.pid_file = self.workdir / "hostapd.pid"
        self.deny_mac_file = self.workdir / "hostapd.deny"
        self.current: dict | None = None

    def start(self, template: str = "hostapd/ap.conf.j2", **params) -> None:
        """Render `template` with `params` and start hostapd; blocks until the BSS is enabled."""
        self.stop()
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.ctrl_dir.mkdir(parents=True, exist_ok=True)
        deny = params.get("deny_macs") or []
        self.deny_mac_file.write_text("".join(f"{mac}\n" for mac in deny))
        render(
            template,
            self.conf,
            iface=self.iface,
            ctrl_dir=self.ctrl_dir,
            country_code=self.country_code,
            deny_mac_file=self.deny_mac_file,
            **params,
        )
        self.log.write_text("")
        proc = run(["hostapd", "-B", "-t", "-dd", "-f", str(self.log), "-P", str(self.pid_file),
                    str(self.conf)], check=False)
        if proc.returncode != 0:
            raise HostapdError(f"hostapd failed to start ({proc.returncode}); see {self.log}")
        if not wait_for(self.enabled, timeout=15):
            self.stop()
            raise HostapdError(f"hostapd never reached state=ENABLED; see {self.log}")
        self.current = params
        log.info("hostapd up on %s: %s", self.iface, params.get("ssid"))

    def ensure(self, template: str = "hostapd/ap.conf.j2", **params) -> None:
        """Start hostapd only if it is not already running with the same config."""
        if self.current != params or not self.enabled():
            self.start(template, **params)

    def status(self) -> dict[str, str]:
        proc = run(["hostapd_cli", "-p", str(self.ctrl_dir), "-i", self.iface, "status"],
                   check=False, timeout=5)
        return dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)

    def cli(self, *args: str, timeout: float = 5) -> str:
        """One hostapd_cli command on this AP; returns its output ("" if hostapd did not answer)."""
        try:
            return run(["hostapd_cli", "-p", str(self.ctrl_dir), "-i", self.iface, *args],
                       check=False, timeout=timeout).stdout
        except subprocess.TimeoutExpired:
            return ""

    def deauthenticate(self, mac: str) -> None:
        """Kick one client off the AP (sends a Deauthentication frame to it)."""
        run(["hostapd_cli", "-p", str(self.ctrl_dir), "-i", self.iface, "deauthenticate", mac],
            check=False, timeout=5)

    def enabled(self) -> bool:
        return self.status().get("state") == "ENABLED"

    def stop(self) -> None:
        self.current = None
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
