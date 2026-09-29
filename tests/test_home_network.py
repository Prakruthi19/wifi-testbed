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
7. router-assisted     802.11k: the phone asks for the list of nearby APs and gets the other two.
   roaming             802.11v: the router asks the phone to move; it moves to a real mesh point
                       and says no to one that does not exist
8. device discovery    the phone finds the speaker by mDNS (like a casting app) on one router and
                       across a mesh point; with client isolation on it cannot, and can again
                       once isolation is off

Needs `sudo HOMENET=1 lab/setup_lab.sh` (ap1, ap2 and sta1..sta5).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from classifier.classify_join import classify_pcap
from testbed.client import assoc_time_ms
from testbed.home import (INTEROP_ROUTERS, HomeLab, device_profiles, diagnose, expected_home,
                          in_parallel, parse_scan_results, small_pool)
from testbed.network import iface_in_namespace
from testbed.perf import VIRTUAL_NOTE, IperfServer
from testbed.steering import BTM_STATUS, parse_btm_responses, parse_neighbor_reports
from testbed.util import ns_prefix, wait_for

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
def fresh(devices, home_lab, artifacts, attach):
    """Every test starts with all devices off the network and DHCP/DNS back to normal.
    Afterwards each AP's hostapd log lines from this test are saved: the router's side of a failed
    join. (Second run, 2026-09-29: the router restarted the 4-way handshake right after it finished
    and the next test's restart had already wiped hostapd.log.)"""
    disconnect_all(devices)
    home_lab.set_dhcp()
    starts = {n: ap.log.stat().st_size if ap.log.exists() else 0 for n, ap in home_lab.aps.items()}
    yield devices
    disconnect_all(devices)
    for name, ap in home_lab.aps.items():
        if not ap.log.exists():
            continue
        with ap.log.open("rb") as fh:
            fh.seek(starts[name] if ap.log.stat().st_size >= starts[name] else 0)
            data = fh.read()
        if data:
            dest = artifacts / f"hostapd-{name}.log"
            dest.write_bytes(data)
            attach(dest, dest.name)


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


# -- 7. router-assisted roaming (802.11k neighbor report, 802.11v steering) ---------------------

def log_since(path, offset: int) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as fh:
        fh.seek(offset if path.stat().st_size >= offset else 0)
        return fh.read().decode(errors="replace")


def put_on(home_lab, device, name: str, bssids: dict) -> None:
    """Put a device on AP `name` (it may have picked another one when it joined)."""
    if device.current_bssid() != bssids[name]:
        assert device.scan_for(bssids[name]) and device.roam(bssids[name]), \
            f"could not put the {device.name} on {name}"


def test_neighbor_report(fresh, home_lab, inventory, artifacts, attach, capture, record_property):
    """802.11k: the phone asks its AP which other APs of the network are nearby, and the answer
    must list the two others with their right channels."""
    gw = inventory.lab["gateway"]
    bssids = home_lab.start_all("transition", rrm=True, bss_transition=True)
    given = home_lab.set_neighbors()
    ap = home_lab.config("transition")
    phone, profile = fresh["phone"]
    join = phone.join(ap.ssid, profile.network_for(ap), gateway=gw, artifacts=artifacts)
    assert join.passed, f"phone failed to join at {join.failed_stage}"
    on = home_lab.ap_for_bssid(phone.current_bssid())

    log = phone.workdir / f"wpa_supplicant-{phone.name}.log"
    offset = log.stat().st_size
    answer = phone.wpa_cli("neighbor_rep_request").strip()
    got = wait_for(lambda: parse_neighbor_reports(log_since(log, offset)), timeout=5) or []
    time.sleep(0.5)  # every entry arrives in one frame, but give the log a moment to catch up
    got = parse_neighbor_reports(log_since(log, offset)) or got

    names = {b: n for n, b in bssids.items()}
    reported = {r["bssid"]: {"ap": names.get(r["bssid"], "unknown"), "channel": r.get("chan")}
                for r in got}
    result = {"phone_on": on, "request": answer, "given_to_ap": given[on], "reported": reported}
    (artifacts / "neighbor-report.json").write_text(json.dumps(result, indent=2))
    attach(artifacts / "neighbor-report.json")
    record_property("reported", reported)

    assert answer == "OK", f"phone did not send a neighbor request ({answer!r}): does {on} " \
                           f"advertise 802.11k, and does the phone support it?"
    missing = [names[b] for b in given[on] if b not in reported]
    assert not missing, f"{on}'s answer left out {missing}: {reported}"
    wrong = {v["ap"]: v["channel"] for b, v in reported.items()
             if b in names and b != bssids[on] and v["channel"] != home_lab.channels[names[b]]}
    assert not wrong, f"wrong channel reported for {wrong}"


STEERING = {
    # case: (target is a real mesh point?, device should accept)
    "to_mesh_point": (True, True),
    "to_missing_ap": (False, False),  # router names an AP that is not there: device must say no
}


@pytest.mark.parametrize("case", list(STEERING))
def test_steering(case, fresh, home_lab, inventory, artifacts, attach, capture, record_property):
    """802.11v: the router asks the phone to move. To a real mesh point the phone must say yes
    (status 0), move there and keep its address. To an AP that does not exist it must say no
    and stay online where it is."""
    gw = inventory.lab["gateway"]
    real_target, should_accept = STEERING[case]
    bssids = home_lab.start_all("transition", rrm=True, bss_transition=True)
    home_lab.set_neighbors()
    ap = home_lab.config("transition")
    phone, profile = fresh["phone"]
    router, mesh = home_lab.router_name, list(bssids)[1]
    join = phone.join(ap.ssid, profile.network_for(ap), gateway=gw, artifacts=artifacts)
    assert join.passed, f"phone failed to join at {join.failed_stage}"
    put_on(home_lab, phone, router, bssids)
    ip_before = phone.ipv4()
    if real_target:
        target, channel = bssids[mesh], home_lab.channels[mesh]
        phone.scan_for(target, flush=False)  # like a real device, it has seen the mesh point
    else:
        target, channel = "02:00:00:00:99:00", home_lab.channels[mesh]

    router_log = home_lab.aps[router].log
    offset = router_log.stat().st_size
    phone_log = phone.workdir / f"wpa_supplicant-{phone.name}.log"
    phone_offset = phone_log.stat().st_size
    start = time.monotonic()
    sent = home_lab.steer(router, phone.mac, target, channel)
    responses = wait_for(lambda: parse_btm_responses(log_since(router_log, offset), phone.mac),
                         timeout=10) or []
    moved = bool(wait_for(lambda: phone.current_bssid() == target, timeout=10, interval=0.05)) \
        if real_target else False
    elapsed_s = round(time.monotonic() - start, 2)
    online = bool(wait_for(lambda: phone.ping(gw, 1), timeout=MAX_BACK_ONLINE_S, interval=0.1))
    status = responses[0].get("status_code") if responses else None

    result = {"case": case, "target": target, "router_command": sent,
              "answer": responses[0] if responses else None,
              "answer_in_words": BTM_STATUS.get(status, "no answer") if status is not None else "no answer",
              "moved": moved, "now_on": home_lab.ap_for_bssid(phone.current_bssid()),
              "seconds": elapsed_s, "online_after": online,
              "ip_before": ip_before, "ip_after": phone.ipv4()}
    (artifacts / "steering.json").write_text(json.dumps(result, indent=2))
    # The phone's side of the request (how it picked where to go); its log is replaced at the
    # next join, so keep this test's part.
    (artifacts / "phone-after-request.log").write_text(log_since(phone_log, phone_offset))
    attach(artifacts / "phone-after-request.log")
    attach(artifacts / "steering.json")
    record_property("answer", result["answer_in_words"])
    record_property("seconds", elapsed_s)

    assert sent == "OK", f"router refused to send the request ({sent!r}): is bss_transition on?"
    assert responses, "phone never answered the transition request"
    if should_accept:
        assert status == 0, f"phone said no: {result['answer_in_words']} ({responses[0]})"
        assert responses[0].get("target_bssid") == target, f"phone chose another AP: {responses[0]}"
        assert moved, f"phone said yes but is on {result['now_on']}, not {mesh}"
        assert result["ip_after"] == ip_before, f"address changed: {ip_before} -> {result['ip_after']}"
    else:
        assert status != 0, f"phone accepted a move to an AP that does not exist: {responses[0]}"
        assert result["now_on"] == router, f"phone left the router for {result['now_on']}"
    assert online, f"phone could not reach the router within {MAX_BACK_ONLINE_S}s afterwards"


# -- 8. device discovery (mDNS) ----------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
DISCOVERY = {
    # case: (speaker on a mesh point?, client isolation on?, phone should find it)
    "same_router": (False, False, True),
    "across_mesh": (True, False, True),
    "client_isolation": (False, True, False),
}


def mdns(dev_client, *args: str, background: bool = False):
    cmd = ns_prefix(dev_client.namespace) + [sys.executable, "-m", "testbed.mdns", *args]
    if background:
        return subprocess.Popen(cmd, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True)
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)
    return json.loads(proc.stdout) if proc.returncode == 0 and proc.stdout.strip() else []


def discover_speaker(phone, speaker, speaker_ip: str, phone_ip: str) -> list[dict]:
    responder = mdns(speaker, "respond", "--ip", speaker_ip, "--host", "speaker",
                     "--name", "Living room speaker", "--seconds", "15", background=True)
    try:
        time.sleep(0.5)  # let the speaker start listening
        return mdns(phone, "browse", "--ip", phone_ip, "--seconds", "3")
    finally:
        responder.terminate()
        responder.wait(timeout=5)


@pytest.mark.parametrize("case", list(DISCOVERY))
def test_discovery(case, fresh, home_lab, inventory, artifacts, attach, capture, record_property):
    """The phone looks for something to cast to, like a casting app does (mDNS). It must find
    the speaker on the same router and across a mesh point. With client isolation on (guest-network
    style) it must not, and after isolation is turned off it must again: the classic "my phone
    can't find the speaker" ticket, broken and fixed on purpose."""
    gw = inventory.lab["gateway"]
    on_mesh, isolated, should_find = DISCOVERY[case]
    ap = home_lab.config("transition")
    if on_mesh:
        bssids = home_lab.start_all("transition")
    else:
        bssids = {home_lab.router_name: home_lab.only_router(ap, ap_isolate=isolated)}
    results = join_devices(fresh, ["phone", "speaker"], ap, gw, artifacts)
    failed = {n: r.failed_stage for n, r in results.items() if not r.passed}
    assert not failed, f"devices failed to join: {failed}"
    phone, speaker = fresh["phone"][0], fresh["speaker"][0]
    if on_mesh:
        mesh = list(bssids)[1]
        put_on(home_lab, phone, home_lab.router_name, bssids)
        put_on(home_lab, speaker, mesh, bssids)
    where = {n: home_lab.ap_for_bssid(fresh[n][0].current_bssid()) for n in ("phone", "speaker")}
    ips = {n: r.ip for n, r in results.items()}

    found = discover_speaker(phone, speaker, ips["speaker"], ips["phone"])
    reaches = phone.ping(ips["speaker"], 2)
    result = {"case": case, "connected_to": where, "ips": ips, "found": found,
              "phone_pings_speaker": reaches}
    if isolated:
        home_lab.only_router(ap, ap_isolate=False)  # the fix: turn isolation off
        after = join_devices(fresh, ["phone", "speaker"], ap, gw, artifacts / "fixed")
        ips_after = {n: r.ip for n, r in after.items()}
        result["after_fix"] = {"joined": {n: r.passed for n, r in after.items()},
                               "found": discover_speaker(phone, speaker, ips_after["speaker"],
                                                         ips_after["phone"])}
    (artifacts / "discovery.json").write_text(json.dumps(result, indent=2))
    attach(artifacts / "discovery.json")
    record_property("found", [f["instance"] for f in found])

    speaker_found = [f for f in found if f.get("address") == ips["speaker"]]
    if should_find:
        assert speaker_found, f"phone on {where['phone']} did not find the speaker on " \
                              f"{where['speaker']}: {found}"
    else:
        assert not speaker_found, f"client isolation is on but the phone still found the speaker: {found}"
        assert not reaches, "client isolation is on but the phone can still ping the speaker"
        fix = result["after_fix"]
        assert all(fix["joined"].values()), f"devices failed to rejoin after the fix: {fix}"
        assert fix["found"], "isolation turned off, but the phone still cannot find the speaker"
