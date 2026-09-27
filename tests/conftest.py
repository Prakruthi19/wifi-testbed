"""Shared fixtures: lab up/down checks, per-test artifacts and capture, report attachments.

Lab tests (marker `lab`) need root inside the Ubuntu VM after `sudo lab/setup_lab.sh`.
Android tests (marker `android`) run on the host with `-m android` and are deselected otherwise.
Unit tests (tests/unit) run anywhere.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

import pytest

from testbed import REPORTS_DIR, inventory as inv
from testbed.report import matrix_html

ARTIFACTS_DIR = REPORTS_DIR / "artifacts"
ATTACHMENTS = pytest.StashKey[list]()
MATRIX_RESULTS: list[dict] = []


# -- options & collection ------------------------------------------------------------------

def pytest_addoption(parser):
    g = parser.getgroup("testbed")
    g.addoption("--repeats", type=int, default=5, help="joins per matrix case (default 5)")
    g.addoption("--channels", default=None, help="comma-separated channel subset, e.g. 6,36")
    g.addoption("--android-serial", default=None, help="adb serial (default: only device)")
    g.addoption("--android-ping-host", default="8.8.8.8", help="host pinged from the emulator")
    g.addoption("--android-ssid", default=None,
                help="network the phone joins by command (join tests skip without it)")
    g.addoption("--android-security", default="wpa2", choices=["open", "owe", "wpa2", "wpa3"])
    g.addoption("--android-psk", default=None, help="passphrase for --android-ssid")
    g.addoption("--android-bugreport", action="store_true",
                help="save an adb bugreport zip when an Android test fails (slow)")


def lab_available() -> str | None:
    """None if the lab looks usable, otherwise the reason it is not."""
    if not sys.platform.startswith("linux"):
        return "lab tests need the Ubuntu VM"
    if os.geteuid() != 0:
        return "lab tests need root (sudo -E .venv/bin/pytest ...)"
    if not Path("/sys/class/net/hwsim0").exists():
        return "hwsim0 missing: run sudo lab/setup_lab.sh"
    return None


def pytest_collection_modifyitems(config, items):
    markexpr = config.getoption("-m") or ""
    if "android" not in markexpr:
        keep = [i for i in items if "android" not in i.keywords]
        deselected = [i for i in items if "android" in i.keywords]
        if deselected:
            config.hook.pytest_deselected(items=deselected)
            items[:] = keep
    reason = lab_available()
    if reason:
        for item in items:
            if "lab" in item.keywords:
                item.add_marker(pytest.mark.skip(reason=reason))


# -- artifacts & attachments ---------------------------------------------------------------

def _safe(nodeid: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", nodeid.split("::", 1)[-1])[:120]


@pytest.fixture
def artifacts(request) -> Path:
    path = ARTIFACTS_DIR / _safe(request.node.nodeid)
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture
def attach(request):
    """attach(path, name=None): link a file (log, pcap) from this test's HTML report row."""
    request.node.stash.setdefault(ATTACHMENTS, [])

    def _attach(path: Path, name: str | None = None) -> None:
        path = Path(path)
        if path.exists():
            request.node.stash[ATTACHMENTS].append((path, name or path.name))

    return _attach


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call":
        return
    item.call_failed = report.failed  # read by fixtures that collect evidence on failure
    try:
        from pytest_html import extras
    except ImportError:
        return
    extra = getattr(report, "extras", [])
    for path, name in item.stash.get(ATTACHMENTS, []):
        rel = os.path.relpath(path, REPORTS_DIR).replace(os.sep, "/")
        extra.append(extras.url(rel, name=name))
        if report.failed and path.suffix in (".log", ".txt"):
            text = path.read_text(errors="replace").splitlines()[-60:]
            extra.append(extras.text("\n".join(text), name=f"{name} (tail)"))
    report.extras = extra


def pytest_runtest_logreport(report):
    if report.when == "call":
        props = dict(report.user_properties)
        if "matrix_row" in props:
            MATRIX_RESULTS.append({
                "row": props["matrix_row"], "col": props["matrix_col"],
                "pass_rate": props["pass_rate"], "median_join_ms": props["median_join_ms"],
                "expected": props["expected"], "failed_stages": props.get("failed_stages", []),
            })


def pytest_html_results_summary(prefix, summary, postfix):
    if MATRIX_RESULTS:
        prefix.append("<h2>Connectivity matrix</h2>" + matrix_html(MATRIX_RESULTS))


def pytest_sessionfinish(session):
    if MATRIX_RESULTS:
        REPORTS_DIR.mkdir(exist_ok=True)
        (REPORTS_DIR / "matrix.html").write_text(
            "<!doctype html><meta charset='utf-8'><title>Connectivity matrix</title>"
            "<body style='font-family:sans-serif'><h1>Connectivity matrix</h1>"
            + matrix_html(MATRIX_RESULTS) + "</body>")


# -- lab fixtures --------------------------------------------------------------------------

@pytest.fixture(scope="session")
def inventory():
    return inv.load()


@pytest.fixture(scope="session")
def lab_workdir() -> Path:
    path = REPORTS_DIR / "run"
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(scope="session")
def clients(inventory, lab_workdir):
    from testbed.client import WifiClient
    from testbed.network import iface_in_namespace

    out = {}
    for c in inventory.clients:
        if not iface_in_namespace(c.iface, c.namespace):
            pytest.skip(f"{c.iface} not found in {c.namespace}: run sudo lab/setup_lab.sh")
        out[c.name] = WifiClient(c.name, c.iface, c.namespace, lab_workdir / c.name,
                                 inventory.lab["country_code"])
    yield out
    for client in out.values():
        client.disconnect()


@pytest.fixture(scope="module")
def hostap(inventory, lab_workdir):
    from testbed.ap import HostAP

    ap = HostAP(inventory.ap_iface, lab_workdir / "hostapd", inventory.lab["country_code"])
    yield ap
    ap.stop()


@pytest.fixture(scope="module")
def dnsmasq(inventory, lab_workdir):
    from testbed.network import Dnsmasq, Subnet

    lab = inventory.lab
    d = Dnsmasq(lab_workdir / "dnsmasq",
                [Subnet(inventory.ap_iface, "lab", lab["gateway"], *lab["dhcp_range"])],
                domain=lab["dns_domain"], dns_records={lab["dns_test_name"]: lab["gateway"]})
    d.start()
    yield d
    d.stop()


@pytest.fixture
def capture(request, inventory, artifacts, attach):
    """Per-test capture on hwsim0; stopped (idempotently) and attached at teardown."""
    from testbed.capture import Capture

    cap = Capture(artifacts / "capture.pcap", inventory.lab["capture_iface"]).start()
    yield cap
    cap.stop()
    attach(cap.pcap, "capture.pcap")


@pytest.fixture
def ap_log(hostap, artifacts, attach):
    """Copies the hostapd log lines written during this test into the test's artifacts."""
    start = hostap.log.stat().st_size if hostap.log.exists() else 0
    yield
    if hostap.log.exists():
        with hostap.log.open("rb") as fh:
            fh.seek(start if hostap.log.stat().st_size >= start else 0)
            dest = artifacts / "hostapd.log"
            dest.write_bytes(fh.read())
        attach(dest, "hostapd.log")
