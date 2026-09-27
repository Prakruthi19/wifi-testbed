"""Check the VM is ready for lab tests, and optionally clean up leftovers from manual runs.

    sudo .venv/bin/python -m testbed.preflight          # report only
    sudo .venv/bin/python -m testbed.preflight --clean  # also stop stray hostapd/wpa_supplicant/...

Stray processes started by hand (like a manual hostapd on ap0) fight the harness for the same
radio, so a run that starts with them gives confusing failures.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

from testbed import inventory as inv

TOOLS = ["hostapd", "hostapd_cli", "wpa_supplicant", "wpa_cli", "dnsmasq", "dumpcap", "tshark",
         "dhclient", "dig", "iw", "ip", "nc", "iperf3"]
DAEMONS = ["hostapd", "wpa_supplicant", "dnsmasq", "dumpcap", "dhclient", "iperf3"]


def check(clean: bool = False) -> list[tuple[bool, str]]:
    results: list[tuple[bool, str]] = []

    def add(ok: bool, msg: str) -> None:
        results.append((ok, msg))

    add(os.geteuid() == 0, "running as root")
    for tool in TOOLS:
        add(shutil.which(tool) is not None, f"tool installed: {tool}")
    add(Path("/sys/class/net/hwsim0").exists(), "hwsim0 capture interface exists")
    try:
        lab = inv.load()
        add(Path(f"/sys/class/net/{lab.ap_iface}").exists(), f"AP interface {lab.ap_iface} exists")
        netns = subprocess.run(["ip", "netns", "list"], capture_output=True, text=True).stdout
        for c in lab.clients:
            present = c.namespace in netns and subprocess.run(
                ["ip", "-n", c.namespace, "link", "show", c.iface],
                capture_output=True).returncode == 0
            add(present, f"{c.iface} in {c.namespace}")
    except Exception as e:  # a broken inventory is itself a finding
        add(False, f"inventory loads: {e}")

    for name in DAEMONS:
        pids = subprocess.run(["pgrep", "-x", name], capture_output=True, text=True).stdout.split()
        if pids and clean:
            subprocess.run(["pkill", "-x", name])
            add(True, f"stopped stray {name} ({', '.join(pids)})")
        else:
            add(not pids, f"no stray {name} running" + (f" (pids {', '.join(pids)})" if pids else ""))
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--clean", action="store_true", help="stop stray lab daemons")
    args = ap.parse_args(argv)
    results = check(args.clean)
    for ok, msg in results:
        print(f"  {'OK  ' if ok else 'FAIL'}  {msg}")
    failed = [m for ok, m in results if not ok]
    print(f"\n{'ready' if not failed else f'{len(failed)} problem(s)'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
