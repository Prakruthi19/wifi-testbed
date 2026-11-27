"""Turn a packet capture into the summary the Capture page shows.

    python -m testbed.pcap_analysis capture.pcap [--wpa-pwd PASS:SSID] [--limit N] [--out result.json]

Two halves, like classifier/classify_join.py:
  * read_packets() reads the pcap with pyshark (tshark underneath) into plain Packet records;
  * analyse() works only on those records, so it is tested without tshark.

What it reports: how many frames of each kind, the networks heard (beacons), one row per client
device with the join stage the classifier names for it (locate-the-stage), every deauthentication
or disassociation with what its reason code means, each 4-way handshake, the DHCP and DNS
exchanges (only visible when data frames are not encrypted, or are decrypted), and retries.

Captures from the lab are taken on hwsim0, the emulated radio medium: they are emulated frames,
not radio traffic from real hardware.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from classifier.classify_join import DHCP_TYPES, Frame, _field, _int, classify, frame_from_packet

MAX_FRAMES = 20_000  # pyshark reads roughly a few thousand frames a second; past this, stop and say so
MAX_EVENTS = 300     # rows in the "key frames" table

FRAME_TYPES = {0: "management", 1: "control", 2: "data"}
KIND_LABEL = {
    "beacon": "Beacon", "probe_req": "Probe request", "probe_resp": "Probe response",
    "auth": "Authentication", "assoc_req": "Association request", "assoc_resp": "Association response",
    "reassoc_req": "Reassociation request", "reassoc_resp": "Reassociation response",
    "deauth": "Deauthentication", "disassoc": "Disassociation", "action": "Action",
    "eapol": "EAPOL key (4-way handshake)", "eap": "EAP (802.1X login)", "dhcp": "DHCP", "dns": "DNS",
    "data": "Other data", "control": "Control (ACK, RTS, CTS...)", "other": "Other",
}
# 802.11 reason codes (IEEE 802.11-2020 table 9-49): why a deauth or disassoc was sent.
REASONS = {
    1: "Unspecified reason",
    2: "Previous authentication no longer valid",
    3: "Sender is leaving the network (deauthenticated)",
    4: "Disassociated because of inactivity",
    5: "AP cannot handle all the associated devices",
    6: "Class 2 frame from a device that is not authenticated",
    7: "Class 3 frame from a device that is not associated",
    8: "Sender is leaving the network (disassociated)",
    9: "Device asked to (re)associate before authenticating",
    13: "Invalid element in the frame",
    14: "Message integrity code (MIC) failure",
    15: "4-way handshake timeout",
    16: "Group key handshake timeout",
    17: "Security element in the handshake differs from the association request",
    18: "Invalid group cipher",
    19: "Invalid pairwise cipher",
    20: "Invalid key management (AKM)",
    23: "802.1X authentication failed",
    24: "Cipher suite rejected by security policy",
    34: "Too many frames not acknowledged (poor channel)",
}
STAGE_LABEL = {
    "network_selection": "Never tried to join", "authentication": "Failed at authentication",
    "association": "Failed at association", "eap": "Failed at 802.1X login",
    "key_exchange": "Failed at 4-way handshake", "dhcp": "Failed at DHCP (no address)",
    "dns": "Failed at DNS", "success": "Joined and got an address",
    "undetermined": "Joined (data encrypted, DHCP not visible)",
}


@dataclass
class Packet:
    """One frame: the classifier's Frame plus what this summary needs on top of it."""
    frame: Frame
    ftype: int | None = None    # 0 management, 1 control, 2 data
    ssid: str | None = None     # from beacons, probe responses, association requests
    signal: int | None = None   # received signal in dBm, from the radiotap header
    ip_src: str | None = None
    ip_dst: str | None = None
    dhcp_ip: str | None = None  # "your IP" in an Offer or ACK: the address handed out
    dns_answer: str | None = None
    extra: dict = field(default_factory=dict)


# -- reading (pyshark) --------------------------------------------------------------------------

def _ssid(value: str | None) -> str | None:
    """tshark gives the SSID as hex bytes ("6c:61:62"); turn it back into text."""
    if value is None:
        return None
    try:
        return bytes.fromhex(value.replace(":", "")).decode("utf-8", "replace")
    except ValueError:
        return value


def packet_from_pyshark(pkt) -> Packet:
    f = frame_from_packet(pkt)
    ftype = _int(_field(pkt, "wlan.fc.type"))
    if ftype == 1:
        f.kind = "control"
    return Packet(
        frame=f, ftype=ftype,
        ssid=_ssid(_field(pkt, "wlan.ssid")),
        signal=_int(_field(pkt, "radiotap.dbm_antsignal", "wlan_radio.signal_dbm")),
        ip_src=_field(pkt, "ip.src"), ip_dst=_field(pkt, "ip.dst"),
        dhcp_ip=_field(pkt, "dhcp.ip.your", "bootp.ip.your"),
        dns_answer=_field(pkt, "dns.a"),
    )


def read_packets(pcap: str, wpa_pwd: str | None = None, limit: int = MAX_FRAMES) -> tuple[list[Packet], bool]:
    """Packets from a pcap, at most `limit`. Returns (packets, truncated). wpa_pwd="PASSPHRASE:SSID"
    decrypts WPA2-PSK data frames, if the capture holds that device's 4-way handshake."""
    import pyshark

    kwargs = {"decryption_key": wpa_pwd, "encryption_type": "WPA-PWD"} if wpa_pwd else {}
    cap = pyshark.FileCapture(pcap, keep_packets=False, **kwargs)
    out: list[Packet] = []
    truncated = False
    try:
        for pkt in cap:
            if len(out) >= limit:
                truncated = True
                break
            out.append(packet_from_pyshark(pkt))
    finally:
        cap.close()
    return out, truncated


# -- analysis (no tshark needed) -----------------------------------------------------------------

def _avg(values: list[int]) -> int | None:
    return round(sum(values) / len(values)) if values else None


def analyse(packets: list[Packet], truncated: bool = False) -> dict:
    frames = [p.frame for p in packets]
    t0 = frames[0].time if frames else 0.0
    rel = lambda f: round(f.time - t0, 3)  # seconds since the first frame

    by_type = Counter(FRAME_TYPES.get(p.ftype, "other") for p in packets)
    by_kind = Counter(f.kind for f in frames)

    # Networks: who sends beacons (or answers probes), with the name they announce.
    nets: dict[str, dict] = {}
    for p in packets:
        f = p.frame
        if f.kind in ("beacon", "probe_resp") and f.src:
            n = nets.setdefault(f.src, {"bssid": f.src, "ssid": None, "beacons": 0, "secured": False, "_sig": []})
            n["ssid"] = n["ssid"] or p.ssid
            n["beacons"] += f.kind == "beacon"
            n["secured"] = n["secured"] or f.rsn
            if p.signal is not None:
                n["_sig"].append(p.signal)
    aps = set(nets)
    # Any address that answers an authentication or association is an AP too, even with no beacons.
    aps |= {f.src for f in frames if f.kind in ("assoc_resp", "reassoc_resp") and f.src}

    # Clients: devices that probe, authenticate, associate or ask for an address, and are not APs.
    clients: list[str] = []
    for f in frames:
        who = f.dhcp_client if f.kind == "dhcp" and f.dhcp_client else f.src
        starts = f.kind in ("probe_req", "assoc_req", "reassoc_req") or (f.kind == "auth" and f.auth_seq in (1, None)) \
            or (f.kind == "dhcp" and f.dhcp_type in (1, 3))
        if starts and who and who not in aps and who != "ff:ff:ff:ff:ff:ff" and who not in clients:
            clients.append(who)

    devices = []
    for sta in clients:
        mine = [p for p in packets if sta in (p.frame.src, p.frame.dst)
                or (p.frame.kind == "dhcp" and p.frame.dhcp_client == sta)]
        sent = [p for p in mine if p.frame.src == sta]
        verdict = classify(frames, sta)
        ack = [p for p in mine if p.frame.kind == "dhcp" and p.frame.dhcp_type == 5 and p.dhcp_ip]
        ssid = next((p.ssid for p in mine if p.frame.kind in ("assoc_req", "reassoc_req") and p.ssid), None)
        if ssid is None and verdict.bssid in nets:
            ssid = nets[verdict.bssid]["ssid"]
        devices.append({
            "mac": sta, "bssid": verdict.bssid, "ssid": ssid,
            "stage": verdict.stage, "stage_label": STAGE_LABEL.get(verdict.stage, verdict.stage),
            "summary": verdict.summary, "notes": verdict.notes,
            "frames_sent": len(sent), "frames_received": len(mine) - len(sent),
            "retries": sum(p.frame.retry for p in sent),
            "signal_dbm": _avg([p.signal for p in sent if p.signal is not None]),
            "ip": ack[-1].dhcp_ip if ack else None,
            "dns_names": sorted({p.frame.dns_name for p in mine if p.frame.kind == "dns" and p.frame.dns_name}),
        })

    disconnects = [{
        "no": f.no, "t": rel(f), "kind": f.kind, "from": f.src, "to": f.dst,
        "sender": "ap" if f.src in aps else ("client" if f.src in clients else "unknown"),
        "reason": f.reason, "meaning": REASONS.get(f.reason, "Reason code not in the common list"),
    } for f in frames if f.kind in ("deauth", "disassoc")]

    # Handshakes: the EAPOL-Key messages seen between each client and its AP, in order.
    hs: dict[tuple[str, str], list[Frame]] = defaultdict(list)
    for f in frames:
        if f.kind == "eapol" and f.src and f.dst:
            sta, ap = (f.dst, f.src) if f.src in aps or f.eapol_msg in (1, 3) else (f.src, f.dst)
            hs[(sta, ap)].append(f)
    handshakes = [{
        "client": sta, "bssid": ap, "messages": [f.eapol_msg for f in fs],
        "complete": {1, 2, 3, 4} <= {f.eapol_msg for f in fs},
        "duration_ms": round(1000 * (fs[-1].time - fs[0].time), 1),
        "retries": sum(f.retry for f in fs),
    } for (sta, ap), fs in hs.items()]

    dhcp = [{
        "no": p.frame.no, "t": rel(p.frame), "type": DHCP_TYPES.get(p.frame.dhcp_type, str(p.frame.dhcp_type)),
        "client": p.frame.dhcp_client, "ip": p.dhcp_ip if p.dhcp_ip and p.dhcp_ip != "0.0.0.0" else None,
        "server": p.ip_src if p.frame.dhcp_type in (2, 5, 6) else None,
    } for p in packets if p.frame.kind == "dhcp"]
    dns = [{
        "no": p.frame.no, "t": rel(p.frame), "response": bool(p.frame.dns_response), "name": p.frame.dns_name,
        "rcode": p.frame.dns_rcode if p.frame.dns_response else None, "answer": p.dns_answer,
        "from": p.ip_src, "to": p.ip_dst,
    } for p in packets if p.frame.kind == "dns"]

    # Key frames: everything except the background noise (beacons, control, plain data).
    events = [{"no": f.no, "t": rel(f), "kind": f.kind, "label": KIND_LABEL.get(f.kind, f.kind), "text": f.describe()}
              for f in frames if f.kind not in ("beacon", "control", "data", "other")]

    notes = []
    if truncated:
        notes.append(f"Only the first {len(packets)} frames were analysed.")
    encrypted = sum(1 for f in frames if f.kind == "data" and f.protected)
    if encrypted and not dhcp and not dns:
        notes.append(f"{encrypted} data frames are encrypted, so DHCP and DNS cannot be seen. Pick the lab "
                     "network to decrypt (WPA2 only, and the device's 4-way handshake must be in the capture).")
    if not packets:
        notes.append("The capture is empty. hwsim0 only carries frames while the lab's radios are in use: "
                     "start a run, then capture during it.")
    elif not clients:
        notes.append("No client tried to join during the capture, so there is no per-device verdict.")

    retries = sum(f.retry for f in frames)
    return {
        "frames": len(packets), "truncated": truncated,
        "duration_s": round(frames[-1].time - t0, 3) if frames else 0.0,
        "by_type": {k: by_type.get(k, 0) for k in ("management", "control", "data", "other")},
        "by_kind": [{"kind": k, "label": KIND_LABEL.get(k, k), "count": n} for k, n in by_kind.most_common()],
        "retries": retries, "retry_pct": round(100 * retries / len(frames), 1) if frames else 0.0,
        "networks": [{k: v for k, v in n.items() if k != "_sig"} | {"signal_dbm": _avg(n["_sig"])}
                     for n in nets.values()],
        "devices": devices, "disconnects": disconnects, "handshakes": handshakes,
        "dhcp": dhcp, "dns": dns, "events": events[:MAX_EVENTS], "events_total": len(events),
        "notes": notes,
    }


def analyse_pcap(pcap: str, wpa_pwd: str | None = None, limit: int = MAX_FRAMES) -> dict:
    packets, truncated = read_packets(pcap, wpa_pwd, limit)
    return analyse(packets, truncated)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pcap")
    p.add_argument("--wpa-pwd", help="PASSPHRASE:SSID to decrypt WPA2-PSK data frames")
    p.add_argument("--limit", type=int, default=MAX_FRAMES)
    p.add_argument("--out", help="write the JSON here instead of printing it")
    args = p.parse_args(argv)
    result = json.dumps(analyse_pcap(args.pcap, args.wpa_pwd, args.limit), indent=1)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(result)
    else:
        print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
