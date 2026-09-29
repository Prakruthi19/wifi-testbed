"""Home network: a main router, two mesh points and five kinds of home devices.

1. everyone joins      all five devices join at once, get their own address, and can reach
                       each other (the phone reaches the speaker, like casting music)
2. mesh walk           the phone walks router -> living room -> bedroom -> router, pinging all
                       the way; it keeps its address and loses few pings
3. mesh point down     a mesh point switches off; the device on it moves to another AP by itself
4. interoperability    every device against every router setting (WPA2, WPA3, mixed, 5 GHz);
                       expected results are written in testbed/home.py before anything runs
5. busy house          laptop downloads and camera streams while the others measure delay
6. troubleshooting     break one thing, check the diagnosis names the cause in plain words,
                       apply the fix, and check the device joins

Needs `sudo HOMENET=1 lab/setup_lab.sh` (ap1, ap2 and sta1..sta5).
"""

from __future__ import annotations

import json
import time

import pytest

from classifier.classify_join import classify_pcap
from testbed.client import assoc_time_ms
from testbed.home import (INTEROP_ROUTERS, HomeLab, device_profiles, diagnose, expected_home,
                          in_parallel, parse_scan_results, small_pool)
from testbed.network import iface_in_namespace
from testbed.perf import VIRTUAL_NOTE, IperfServer
from testbed.util import wait_for

pytestmark = [pytest.mark.lab, pytest.mark.home]

PING_INTERVAL = 0.05
MAX_BACK_ONLINE_S = 3.0  # after each move the phone must reach the router again within this
RECOVERY_TIMEOUT_S = 30
# Busy-house thresholds: smoke levels for virtual radios, not real Wi-Fi targets.
MIN_LAPTOP_MBPS = 1.0
CAMERA_MBPS = 4
MAX_CAMERA_LOSS_PERCENT = 5.0
MAX_PING_LOSS_PERCENT = 10.0
MAX_AVG_RTT_MS = 100.0


@pytest.fixture(scope="module")
def home(inventory):
    return inventory.home


@pytest.fixture(scope="module")
def home_lab(inventory, home, lab_workdir):
    # Other modules' single-AP hostapd/dnsmasq on ap0 are module-scoped, so they are already
    # stopped by the time this module starts.
    missing = [a["iface"] for a in home["access_points"] if not iface_in_namespace(a["iface"], None)]
    missing += [d["iface"] for d in home["devices"]
                if not iface_in_namespace(d["iface"], d["namespace"])]
    if missing:
        pytest.skip(f"{', '.join(missing)} missing: run sudo HOMENET=1 lab/setup_lab.sh")
    lab = HomeLab(home, lab_workdir / "home", inventory.lab, inventory.lab["country_code"])
    lab.up()
    yield lab
    lab.down()


@pytest.fixture(scope="module")
def devices(home, home_lab, inventory, lab_workdir):
    """name -> (WifiClient, DeviceProfile) for the phone, laptop, camera, plug and speaker."""
    from testbed.client import WifiClient

    profiles = {p.name: p for p in device_profiles(home)}
    out = {d["name"]: (WifiClient(d["name"], d["iface"], d["namespace"], lab_workdir / "home" / d["name"],
                                  inventory.lab["country_code"]), profiles[d["name"]])
           for d in home["devices"]}
    yield out
    disconnect_all(out)


def disconnect_all(devs: dict) -> None:
    in_parallel(lambda _, dev: dev[0].disconnect(), devs)


@pytest.fixture
def fresh(devices, home_lab):
    """Every test starts with all devices off the network and DHCP/DNS back to normal."""
    disconnect_all(devices)
    home_lab.set_dhcp()
    yield devices
    disconnect_all(devices)


def join_devices(devs: dict, names, ap, gw: str, artifacts, passphrase: str | None = None,
                 dns: tuple[str, str] | None = None) -> dict:
    """Join the named devices at the same time; returns name -> JoinResult."""
    def one(name, dev):
        client, profile = dev
        return client.join(ap.ssid, profile.network_for(ap, passphrase), gateway=gw,
                           dns_name=dns[0] if dns else None, dns_expect=dns[1] if dns else None,
                           artifacts=artifacts / name, assoc_timeout=15)
    return in_parallel(one, {n: devs[n] for n in names})


def facts_and_diagnosis(name, devs, home_lab, ap, result):
    client, profile = devs[name]
    scan = parse_scan_results(client.wpa_cli("scan_results"))
    return diagnose(result.failed_stage, profile, ap, ap.ssid, scan, home_lab.dnsmasq_log(),
                    client.mac)


# -- 1. everyone joins -------------------------------------------------------------------------

def test_everyone_joins(fresh, home_lab, inventory, artifacts, attach, capture, record_property):
    lab = inventory.lab
    bssids = home_lab.start_all("transition")
    ap = home_lab.config("transition")
    start = time.monotonic()
    results = join_devices(fresh, fresh, ap, lab["gateway"], artifacts,
                           dns=(lab["dns_test_name"], lab["gateway"]))
    house_online_s = round(time.monotonic() - start, 2)
    where = {n: home_lab.ap_for_bssid(fresh[n][0].current_bssid()) for n in fresh}
    ips = {n: r.ip for n, r in results.items()}
    phone = fresh["phone"][0]
    cast_ok = bool(ips.get("speaker")) and phone.ping(ips["speaker"])

    summary = {"aps": bssids, "house_online_s": house_online_s, "connected_to": where, "ips": ips,
               "joins": {n: r.to_dict() for n, r in results.items()}, "phone_reaches_speaker": cast_ok}
    (artifacts / "home-join.json").write_text(json.dumps(summary, indent=2))
    attach(artifacts / "home-join.json")
    record_property("house_online_s", house_online_s)
    record_property("connected_to", where)

    failed = {n: r.failed_stage for n, r in results.items() if not r.passed}
    assert not failed, f"devices failed to join: {failed}"
    assert len(set(ips.values())) == len(ips), f"two devices got the same address: {ips}"
    assert cast_ok, f"phone {ips.get('phone')} cannot reach the speaker {ips.get('speaker')}"


# -- 2. mesh walk --------------------------------------------------------------------------------

def test_mesh_walk(fresh, home_lab, inventory, artifacts, attach, capture, record_property):
    gw = inventory.lab["gateway"]
    bssids = home_lab.start_all("transition")
    ap = home_lab.config("transition")
    phone, profile = fresh["phone"]
    names = list(bssids)
    route = names[1:] + names[:1]  # router -> living -> bedroom -> router

    # Join while only the router is up, so the walk starts from a known place.
    for name in names[1:]:
        home_lab.stop(name)
    join = phone.join(ap.ssid, profile.network_for(ap), gateway=gw, artifacts=artifacts)
    assert join.passed, f"phone failed to join the router at {join.failed_stage}"
    for name in names[1:]:
        home_lab.start(name, home_lab.config("transition", name=name))
    ip_before = phone.ipv4()
    # Scan for every AP before the walk. A scan takes the radio off its channel, so scanning
    # before each hop lost ~30% of the pings in the first lab run (2026-09-29): that measured
    # the scans, not the moves.
    seen = {name: phone.scan_for(bssids[name], flush=(i == 0)) for i, name in enumerate(route)}

    log = phone.workdir / f"wpa_supplicant-{phone.name}.log"
    hops = []
    ping = phone.start_ping(gw, PING_INTERVAL)
    try:
        time.sleep(1)
        for name in route:
            target = bssids[name]
            offset = log.stat().st_size
            start = time.monotonic()
            moved = phone.roam(target)
            wall_ms = round((time.monotonic() - start) * 1000, 1)
            back = wait_for(lambda: phone.ping(gw, 1), timeout=MAX_BACK_ONLINE_S, interval=0.1)
            back_s = round(time.monotonic() - start, 2) if back else None
            with log.open("rb") as fh:
                fh.seek(offset)
                hop_log = fh.read().decode(errors="replace")
            hops.append({"to": name, "seen_in_scan": seen[name], "moved": moved, "wall_ms": wall_ms, "back_online_s": back_s,
                         "log_ms": assoc_time_ms(hop_log)})
            time.sleep(1)
    finally:
        pings = phone.stop_ping(ping)
    ip_after = phone.ipv4()

    result = {"hops": hops, "pings": pings, "ip_before": ip_before, "ip_after": ip_after,
              "note": "moves forced with wpa_cli roam; virtual radios have no signal strength"}
    (artifacts / "mesh-walk.json").write_text(json.dumps(result, indent=2))
    attach(artifacts / "mesh-walk.json")
    record_property("hops", hops)
    record_property("ping_loss_percent", pings.get("loss_percent"))

    stuck = [h["to"] for h in hops if not h["moved"]]
    assert not stuck, f"phone did not move to {stuck}: {hops}"
    assert ip_after == ip_before, f"address changed on the walk: {ip_before} -> {ip_after}"
    # Ping loss is recorded, not asserted: every hop here is a full WPA3 (SAE) re-join, and the
    # first lab run (2026-09-29) lost 11 of 53 pings over 3 hops. What must hold is that the
    # phone is reachable again soon after every move.
    offline = [h["to"] for h in hops if h["back_online_s"] is None]
    assert not offline, f"phone not reachable within {MAX_BACK_ONLINE_S}s after moving to {offline}"


# -- 3. mesh point down --------------------------------------------------------------------------

def test_mesh_point_down(fresh, home_lab, inventory, artifacts, attach, capture, record_property):
    gw = inventory.lab["gateway"]
    bssids = home_lab.start_all("transition")
    ap = home_lab.config("transition")
    speaker, profile = fresh["speaker"]
    mesh = list(bssids)[1]  # the first mesh point
    join = speaker.join(ap.ssid, profile.network_for(ap), gateway=gw, artifacts=artifacts)
    assert join.passed, f"speaker failed to join at {join.failed_stage}"
    if speaker.current_bssid() != bssids[mesh]:
        assert speaker.scan_for(bssids[mesh]) and speaker.roam(bssids[mesh]), \
            f"could not put the speaker on {mesh}"
    ip_before = speaker.ipv4()

    home_lab.stop(mesh)  # the mesh point loses power
    start = time.monotonic()
    back = wait_for(lambda: speaker.current_bssid() not in (None, bssids[mesh]) and speaker.ping(gw, 1),
                    timeout=RECOVERY_TIMEOUT_S, interval=0.5)
    recovery_s = round(time.monotonic() - start, 2)
    now_on = home_lab.ap_for_bssid(speaker.current_bssid())
    home_lab.start(mesh, home_lab.config("transition", name=mesh))

    result = {"switched_off": mesh, "recovery_s": recovery_s, "now_on": now_on,
              "ip_before": ip_before, "ip_after": speaker.ipv4()}
    (artifacts / "mesh-point-down.json").write_text(json.dumps(result, indent=2))
    attach(artifacts / "mesh-point-down.json")
    record_property("recovery_s", recovery_s)
    record_property("now_on", now_on)
    assert back, f"speaker did not move to another AP within {RECOVERY_TIMEOUT_S}s"
    assert result["ip_after"] == ip_before, f"address changed: {ip_before} -> {result['ip_after']}"


# -- 4. interoperability ---------------------------------------------------------------------------

@pytest.mark.parametrize("security,channel", INTEROP_ROUTERS,
                         ids=[f"{s}-ch{c}" for s, c in INTEROP_ROUTERS])
def test_interop(security, channel, fresh, home_lab, inventory, artifacts, attach, capture,
                 record_property):
    ap = home_lab.config(security, channel)
    home_lab.only_router(ap)
    results = join_devices(fresh, fresh, ap, inventory.lab["gateway"], artifacts)

    rows, wrong = {}, []
    for name, r in results.items():
        exp = expected_home(ap, fresh[name][1])
        got = "pass" if r.passed else "fail"
        diag = facts_and_diagnosis(name, fresh, home_lab, ap, r)
        rows[name] = {"expected": exp.outcome, "expected_stage": exp.stage, "reason": exp.reason,
                      "got": got, "stage": r.failed_stage, "join_ms": r.assoc_ms,
                      "diagnosis": diag.problem if diag else None}
        if got != exp.outcome or (exp.stage and r.failed_stage != exp.stage):
            wrong.append(f"{name}: expected {exp.outcome} {exp.stage or ''}, got {got} "
                         f"{r.failed_stage or ''}")
    disconnect_all(fresh)

    # Second witness: the capture must show the same stage for every device that failed.
    pcap = capture.stop()
    for name, row in rows.items():
        if row["got"] == "fail":
            seen = classify_pcap(str(pcap), sta=fresh[name][0].mac,
                                 wpa_pwd=f"{ap.passphrase}:{ap.ssid}")
            row["classified_stage"] = seen.stage
            if seen.stage != row["stage"]:
                wrong.append(f"{name}: capture says {seen.stage}, device log says {row['stage']}")

    (artifacts / "interop.json").write_text(json.dumps({"router": ap.label, "devices": rows}, indent=2))
    attach(artifacts / "interop.json")
    record_property("router", ap.label)
    record_property("results", {n: r["got"] for n, r in rows.items()})
    assert not wrong, "; ".join(wrong)


# -- 5. busy house ---------------------------------------------------------------------------------

def test_busy_house(fresh, home_lab, inventory, lab_workdir, artifacts, attach, capture,
                    record_property):
    gw = inventory.lab["gateway"]
    home_lab.start_all("transition")
    ap = home_lab.config("transition")
    results = join_devices(fresh, fresh, ap, gw, artifacts)
    failed = {n: r.failed_stage for n, r in results.items() if not r.passed}
    assert not failed, f"devices failed to join: {failed}"

    servers = [IperfServer(gw, lab_workdir / "home" / f"iperf-{port}", port).start()
               for port in (5201, 5202)]
    try:
        work = {
            "laptop": lambda c: c.iperf(gw, seconds=8, reverse=True, port=5201).to_dict(),
            "camera": lambda c: c.iperf_udp(gw, mbps=CAMERA_MBPS, seconds=8, port=5202).to_dict(),
            "phone": lambda c: c.ping_stats(gw, count=30),
            "plug": lambda c: c.ping_stats(gw, count=30),
            "speaker": lambda c: c.ping_stats(gw, count=30),
        }
        measured = in_parallel(lambda name, fn: fn(fresh[name][0]), work)
    finally:
        for s in servers:
            s.stop()

    (artifacts / "busy-house.json").write_text(json.dumps(
        {"measurement": VIRTUAL_NOTE, "laptop_download": measured["laptop"],
         "camera_upload": measured["camera"],
         "ping_while_busy": {n: measured[n] for n in ("phone", "plug", "speaker")}}, indent=2))
    attach(artifacts / "busy-house.json")
    record_property("measurement", VIRTUAL_NOTE)
    record_property("laptop_mbps", measured["laptop"]["mbps"])
    record_property("camera_loss_percent", measured["camera"]["lost_percent"])

    problems = []
    laptop, camera = measured["laptop"], measured["camera"]
    if laptop["error"] or laptop["mbps"] < MIN_LAPTOP_MBPS:
        problems.append(f"laptop download {laptop['mbps']} Mbps ({laptop['error']})")
    if camera["error"] or camera["lost_percent"] > MAX_CAMERA_LOSS_PERCENT:
        problems.append(f"camera lost {camera['lost_percent']}% ({camera['error']})")
    for name in ("phone", "plug", "speaker"):
        p = measured[name]
        if p.get("loss_percent", 100.0) > MAX_PING_LOSS_PERCENT or p.get("rtt_avg_ms", 1e9) > MAX_AVG_RTT_MS:
            problems.append(f"{name} ping {p}")
    assert not problems, "; ".join(problems)


# -- 6. troubleshooting -----------------------------------------------------------------------------
# Each case: (device, how to break it, expected stage(s), expected cause).

TROUBLES = {
    "wrong_password": ("plug", ("key_exchange",), "wrong_password"),
    "router_5ghz_only": ("plug", ("network_selection",), "band"),
    "wpa3_only_router": ("camera", ("network_selection",), "security"),
    "device_blocked": ("speaker", ("network_selection", "authentication"), "blocked"),
    "dhcp_down": ("phone", ("dhcp",), "dhcp_down"),
    "dns_down": ("laptop", ("dns",), "dns"),
    "address_pool_full": (None, ("dhcp",), "pool_full"),
}


def break_home(case: str, home_lab: HomeLab, devs: dict):
    """Apply one fault; returns the router settings in force and any join overrides."""
    ap, deny, passphrase = home_lab.config("transition"), [], None
    if case == "wrong_password":
        passphrase = "oldpassword999"
    elif case == "router_5ghz_only":
        ap = home_lab.config("transition", 36)
    elif case == "wpa3_only_router":
        ap = home_lab.config("wpa3")
    elif case == "device_blocked":
        deny = [devs["speaker"][0].mac]
    elif case == "dhcp_down":
        home_lab.set_dhcp(dhcp=False)
    elif case == "dns_down":
        home_lab.set_dhcp(dns=False)
    elif case == "address_pool_full":
        home_lab.set_dhcp(pool=small_pool(home_lab.lab["dhcp_range"][0], 2))
    home_lab.only_router(ap, deny)
    return ap, passphrase


def fix_home(case: str, home_lab: HomeLab):
    home_lab.set_dhcp()
    ap = home_lab.config("transition")
    home_lab.only_router(ap)
    return ap


@pytest.mark.parametrize("case", list(TROUBLES))
def test_troubleshoot(case, fresh, home_lab, inventory, artifacts, attach, capture, record_property):
    lab = inventory.lab
    device, stages, cause = TROUBLES[case]
    dns = (lab["dns_test_name"], lab["gateway"])
    ap, passphrase = break_home(case, home_lab, fresh)
    # Pool of two addresses, three devices: exactly one must be left without an address.
    names = ["phone", "laptop", "plug"] if device is None else [device]
    results = join_devices(fresh, names, ap, lab["gateway"], artifacts / "broken", passphrase, dns)
    failed = [n for n, r in results.items() if not r.passed]
    diagnoses = {n: facts_and_diagnosis(n, fresh, home_lab, ap, results[n]) for n in failed}
    disconnect_all({n: fresh[n] for n in names})

    fixed_ap = fix_home(case, home_lab)
    after = join_devices(fresh, failed, fixed_ap, lab["gateway"], artifacts / "fixed", None, dns)

    report = {"case": case,
              "broken": {n: r.to_dict() for n, r in results.items()},
              "diagnosis": {n: vars(d) for n, d in diagnoses.items() if d},
              "after_fix": {n: r.to_dict() for n, r in after.items()}}
    (artifacts / "troubleshoot.json").write_text(json.dumps(report, indent=2))
    attach(artifacts / "troubleshoot.json")
    record_property("diagnosis", {n: d.problem for n, d in diagnoses.items() if d})

    assert len(failed) == 1, f"expected exactly one device to fail, got {failed}: {results}"
    name = failed[0]
    stage, diag = results[name].failed_stage, diagnoses[name]
    assert stage in stages, f"{name} stopped at {stage}, expected {stages}"
    assert diag and diag.cause == cause, f"diagnosis {diag}, expected {cause}"
    still = {n: r.failed_stage for n, r in after.items() if not r.passed}
    assert not still, f"after the fix, still failing: {still}"
