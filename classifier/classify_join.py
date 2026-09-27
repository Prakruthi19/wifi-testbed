"""Name the stage where a Wi-Fi join failed, from an 802.11 capture.

    python -m classifier.classify_join capture.pcap [--sta MAC] [--wpa-pwd PASS:SSID] [--json]

Output stage is one of: network_selection, authentication, association, key_exchange, dhcp, dns,
success, or undetermined (data frames are encrypted and no key was given, so DHCP/DNS cannot be
seen). Stages are listed in the order a join goes through them.

Reading the pcap (pyshark) is kept apart from the decision logic (`classify`), which works on
plain `Frame` records so it can be tested without tshark.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field

STAGES = ("network_selection", "authentication", "association", "key_exchange", "dhcp", "dns", "success",
          "undetermined")

AUTH_ALG = {0: "Open System", 1: "Shared Key", 2: "FT", 3: "SAE"}
# Status codes that do not end an attempt: success, SAE anti-clogging token, SAE H2E.
AUTH_OK = {0, 126}
AUTH_CONTINUE = {76}
DHCP_TYPES = {1: "Discover", 2: "Offer", 3: "Request", 4: "Decline", 5: "ACK", 6: "NAK", 7: "Release"}
BROADCAST = "ff:ff:ff:ff:ff:ff"

# (type, subtype) -> kind, from wlan.fc.type_subtype
MGMT_KINDS = {
    0x00: "assoc_req", 0x01: "assoc_resp", 0x02: "reassoc_req", 0x03: "reassoc_resp",
    0x04: "probe_req", 0x05: "probe_resp", 0x08: "beacon", 0x0A: "disassoc",
    0x0B: "auth", 0x0C: "deauth", 0x0D: "action",
}


@dataclass
class Frame:
    no: int
    time: float
    kind: str  # MGMT_KINDS values, "eapol", "dhcp", "dns", "data", "other"
    src: str | None = None
    dst: str | None = None
    bssid: str | None = None
    protected: bool = False
    status: int | None = None
    reason: int | None = None
    auth_alg: int | None = None
    auth_seq: int | None = None
    rsn: bool = False
    eapol_msg: int | None = None
    dhcp_type: int | None = None
    dhcp_client: str | None = None
    dns_id: int | None = None
    dns_response: bool | None = None
    dns_rcode: int | None = None
    dns_name: str | None = None
    retry: bool = False  # 802.11 Retry bit: this frame is a retransmission

    def describe(self) -> str:
        d = f"#{self.no} {self.kind}"
        if self.src:
            d += f" {self.src}->{self.dst}"
        if self.kind == "auth":
            d += f" alg={AUTH_ALG.get(self.auth_alg, self.auth_alg)} seq={self.auth_seq} status={self.status}"
        elif self.kind in ("assoc_resp", "reassoc_resp"):
            d += f" status={self.status}"
        elif self.kind in ("deauth", "disassoc"):
            d += f" reason={self.reason}"
        elif self.kind == "eapol":
            d += f" M{self.eapol_msg}"
        elif self.kind == "dhcp":
            d += f" {DHCP_TYPES.get(self.dhcp_type, self.dhcp_type)}"
        elif self.kind == "dns":
            d += f" {'response' if self.dns_response else 'query'} id={self.dns_id} {self.dns_name or ''}"
            if self.dns_response:
                d += f" rcode={self.dns_rcode}"
        return d


@dataclass
class Result:
    stage: str
    sta: str | None
    bssid: str | None
    summary: str
    evidence: list[Frame] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["evidence"] = [f.describe() for f in self.evidence]
        return d


def eapol_message(key_info: int) -> int:
    """4-way handshake message number from the EAPOL-Key Key Information field."""
    install, ack, mic, secure = (bool(key_info & b) for b in (0x0040, 0x0080, 0x0100, 0x0200))
    if ack and not mic:
        return 1
    if ack and mic:
        return 3
    if mic and secure:
        return 4
    return 2


# -- decision logic --------------------------------------------------------------------------

def guess_sta(frames: list[Frame]) -> str | None:
    """The client of interest: last station to send an auth/assoc request, else a probing one."""
    for kinds in (("auth", "assoc_req", "reassoc_req"), ("probe_req",)):
        for f in reversed(frames):
            if f.kind not in kinds or not f.src or f.src == f.bssid:
                continue
            if f.kind == "auth" and f.auth_seq not in (1, 3, None):
                continue  # seq 2/4 come from the AP (except SAE, where both sides send 1 and 2)
            return f.src
    return None


def link_events(frames: list[Frame], sta: str) -> dict:
    """Disconnects and retransmissions involving `sta`, independent of the join verdict.

    disconnects: (frame no, "deauth"/"disassoc", who sent it: "client" or "ap", reason code)
    retries: frames with the Retry bit set, out of `frames_seen` frames to or from the client.
    """
    sta = sta.lower()
    fs = [f for f in frames if sta in (f.src, f.dst)]
    disconnects = [(f.no, f.kind, "client" if f.src == sta else "ap", f.reason)
                   for f in fs if f.kind in ("deauth", "disassoc")]
    return {"disconnects": disconnects, "retries": sum(f.retry for f in fs), "frames_seen": len(fs)}


def link_notes(frames: list[Frame], sta: str) -> list[str]:
    ev = link_events(frames, sta)
    notes = [f"{kind} from {who}, reason {reason} (frame #{no})"
             for no, kind, who, reason in ev["disconnects"]]
    if ev["retries"]:
        notes.append(f"retransmissions: {ev['retries']} of {ev['frames_seen']} frames "
                     f"({100 * ev['retries'] / ev['frames_seen']:.1f}%)")
    return notes


def classify(frames: list[Frame], sta: str | None = None) -> Result:
    sta = (sta or guess_sta(frames) or "").lower() or None
    if not sta:
        return Result("network_selection", None, None, "no client activity found in capture")

    def mine(f: Frame) -> bool:
        if f.kind == "dhcp":
            return f.dhcp_client == sta or f.src == sta
        return sta in (f.src, f.dst)

    fs = [f for f in frames if mine(f)]
    from_sta = [f for f in fs if f.src == sta]
    to_sta = [f for f in fs if f.dst == sta]
    bssid = next((f.bssid for f in fs if f.kind in ("auth", "assoc_req") and f.bssid), None)
    deauths = [f for f in fs if f.kind in ("deauth", "disassoc")]

    def result(stage: str, summary: str, evidence: list[Frame], notes: list[str] | None = None):
        ev = sorted({f.no: f for f in evidence + deauths}.values(), key=lambda f: f.no)
        return Result(stage, sta, bssid, summary, ev[-12:], (notes or []) + link_notes(fs, sta))

    # 1. Network selection: the client never chose this BSS --------------------------------
    auth = [f for f in fs if f.kind == "auth"]
    assoc_reqs = [f for f in from_sta if f.kind in ("assoc_req", "reassoc_req")]
    if not auth and not assoc_reqs:
        probes = [f for f in fs if f.kind in ("probe_req", "probe_resp")]
        return result(
            "network_selection",
            "client never attempted authentication or association",
            probes[-4:],
            ["The client scanned but rejected the network during selection. Typical causes: "
             "no AKM in common (e.g. WPA2-only client, WPA3-only AP) or PMF required by one "
             "side and unsupported by the other. Check the RSN IE in the probe response. "
             "(If the client does send an Association Request and the AP rejects it, e.g. "
             "status 31, that is an association failure instead.)"],
        )
    # 2. Authentication (Open System or SAE commit/confirm) -------------------------------
    if auth:
        ap_auth = [f for f in auth if f.dst == sta]
        sae = any(f.auth_alg == 3 for f in auth)
        if sae:
            ap_commit = [f for f in ap_auth if f.auth_seq == 1 and f.status in AUTH_OK]
            ap_confirm = [f for f in ap_auth if f.auth_seq == 2 and f.status == 0]
            if not ap_confirm:
                rejected = [f for f in ap_auth if f.status not in AUTH_OK | AUTH_CONTINUE]
                if rejected:
                    why = f"AP rejected SAE with status {rejected[-1].status}"
                elif ap_commit:
                    why = "SAE commit exchanged but the AP never sent Confirm (password mismatch)"
                else:
                    why = "AP never answered the SAE Commit"
                return result("authentication", why, auth)
        elif not any(f.status == 0 for f in ap_auth):
            if ap_auth:
                why = f"AP rejected Open System authentication with status {ap_auth[-1].status}"
            else:
                why = "no authentication response from the AP"
            return result("authentication", why, auth)

    # 3. Association ----------------------------------------------------------------------
    assoc_resps = [f for f in to_sta if f.kind in ("assoc_resp", "reassoc_resp")]
    if not any(f.status == 0 for f in assoc_resps):
        if assoc_resps:
            why = f"AP rejected association with status {assoc_resps[-1].status}"
        elif assoc_reqs:
            why = "association request got no response"
        else:
            why = "authenticated but never sent an association request"
        return result("association", why, assoc_reqs + assoc_resps)

    # 4. 4-way handshake ------------------------------------------------------------------
    eapol = [f for f in fs if f.kind == "eapol"]
    rsn = bool(eapol) or any(f.rsn for f in assoc_reqs)
    if rsn:
        msgs = {f.eapol_msg for f in eapol}
        if 4 not in msgs:
            if not msgs:
                why = "associated with RSN but no EAPOL-Key frames followed"
            elif 3 not in msgs:
                why = "4-way handshake stopped after message 2: AP did not send message 3 (MIC failure, wrong PSK)"
            else:
                why = "client never sent message 4"
            reasons = [f.reason for f in deauths if f.reason is not None]
            notes = [f"deauth/disassoc reason codes: {reasons}"] if reasons else []
            return result("key_exchange", why, eapol, notes)

    # 5. DHCP -----------------------------------------------------------------------------
    dhcp = [f for f in fs if f.kind == "dhcp"]
    types = {f.dhcp_type for f in dhcp}
    if 5 not in types:
        encrypted = [f for f in fs if f.kind == "data" and f.protected]
        if not dhcp and encrypted:
            return result("undetermined", "join completed at layer 2 but data frames are encrypted",
                          eapol[-2:], ["Re-run with --wpa-pwd PASSPHRASE:SSID (WPA2-PSK) to decrypt."])
        if not dhcp:
            why = "no DHCP traffic after the join"
        elif 6 in types:
            why = "DHCP server answered with NAK"
        elif 2 not in types:
            why = "DHCP Discover sent, no Offer received"
        else:
            why = "DHCP Offer received but no ACK"
        return result("dhcp", why, dhcp)

    # 6. DNS ------------------------------------------------------------------------------
    dns = [f for f in fs if f.kind == "dns"]
    queries = [f for f in dns if f.src == sta and not f.dns_response]
    answers = [f for f in dns if f.dst == sta and f.dns_response]
    if queries and not any(f.dns_rcode == 0 for f in answers):
        if answers:
            why = f"DNS answered with error rcode {answers[-1].dns_rcode}"
        else:
            why = "DNS queries sent, no answer received"
        return result("dns", why, queries + answers)

    notes = [] if queries else ["no DNS queries in the capture; DNS not exercised"]
    return result("success", "joined, leased an address" + (", resolved DNS" if queries else ""),
                  [f for f in eapol if f.eapol_msg == 4][-1:] + [f for f in dhcp if f.dhcp_type == 5][-1:]
                  + answers[-1:], notes)


# -- pcap reading (pyshark) ------------------------------------------------------------------

def _field(pkt, *names: str) -> str | None:
    """First value found for any of `names` (full Wireshark field names) in any layer."""
    for name in names:
        for layer in pkt.layers:
            try:
                value = layer.get_field(name)
            except Exception:
                value = None
            if value is not None and str(value) != "":
                return str(value)
    return None


def _int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value, 0)
    except ValueError:
        try:
            return int(float(value))
        except ValueError:
            return None


def _bool(value: str | None) -> bool:
    return str(value).strip().lower() in ("1", "true")


def _mac(value: str | None) -> str | None:
    return value.lower() if value else None


def frame_from_packet(pkt) -> Frame:
    layers = {layer.layer_name for layer in pkt.layers}
    subtype = _int(_field(pkt, "wlan.fc.type_subtype"))
    ftype = _int(_field(pkt, "wlan.fc.type"))
    f = Frame(
        no=int(pkt.number),
        time=float(pkt.sniff_timestamp),
        kind="other",
        src=_mac(_field(pkt, "wlan.sa", "wlan.ta")),
        dst=_mac(_field(pkt, "wlan.da", "wlan.ra")),
        bssid=_mac(_field(pkt, "wlan.bssid")),
        protected=_bool(_field(pkt, "wlan.fc.protected")),
        retry=_bool(_field(pkt, "wlan.fc.retry")),
    )
    if ftype == 0 and subtype in MGMT_KINDS:
        f.kind = MGMT_KINDS[subtype]
        f.status = _int(_field(pkt, "wlan.fixed.status_code"))
        f.reason = _int(_field(pkt, "wlan.fixed.reason_code"))
        f.auth_alg = _int(_field(pkt, "wlan.fixed.auth.alg"))
        f.auth_seq = _int(_field(pkt, "wlan.fixed.auth_seq"))
        f.rsn = _field(pkt, "wlan.rsn.version") is not None
    elif "eapol" in layers:
        f.kind = "eapol"
        msg = _int(_field(pkt, "wlan_rsna_eapol.keydes.msgnr"))
        key_info = _int(_field(pkt, "wlan_rsna_eapol.keydes.key_info", "eapol.keydes.key_info"))
        f.eapol_msg = msg or (eapol_message(key_info) if key_info is not None else None)
    elif "dhcp" in layers or "bootp" in layers:
        f.kind = "dhcp"
        f.dhcp_type = _int(_field(pkt, "dhcp.option.dhcp", "bootp.option.dhcp"))
        f.dhcp_client = _mac(_field(pkt, "dhcp.hw.mac_addr", "bootp.hw.mac_addr"))
    elif "dns" in layers:
        f.kind = "dns"
        f.dns_id = _int(_field(pkt, "dns.id"))
        f.dns_response = _bool(_field(pkt, "dns.flags.response"))
        f.dns_rcode = _int(_field(pkt, "dns.flags.rcode"))
        f.dns_name = _field(pkt, "dns.qry.name")
    elif ftype == 2:
        f.kind = "data"
    return f


def read_frames(pcap: str, wpa_pwd: str | None = None) -> list[Frame]:
    import pyshark

    kwargs = {}
    if wpa_pwd:
        kwargs = {"decryption_key": wpa_pwd, "encryption_type": "WPA-PWD"}
    cap = pyshark.FileCapture(
        pcap,
        keep_packets=False,
        display_filter="wlan.fc.type != 1 && wlan.fc.type_subtype != 0x0008",  # drop control + beacons
        **kwargs,
    )
    try:
        return [frame_from_packet(pkt) for pkt in cap]
    finally:
        cap.close()


def classify_pcap(pcap: str, sta: str | None = None, wpa_pwd: str | None = None) -> Result:
    return classify(read_frames(pcap, wpa_pwd), sta)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pcap")
    p.add_argument("--sta", help="client MAC (default: guessed from auth/assoc requests)")
    p.add_argument("--wpa-pwd", help="PASSPHRASE:SSID to decrypt WPA2-PSK data frames")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    res = classify_pcap(args.pcap, args.sta, args.wpa_pwd)
    if args.json:
        print(json.dumps(res.to_dict(), indent=2))
    else:
        print(f"stage:   {res.stage}\nclient:  {res.sta}\nbssid:   {res.bssid}\nsummary: {res.summary}")
        for note in res.notes:
            print(f"note:    {note}")
        print("evidence:")
        for f in res.evidence:
            print(f"  {f.describe()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
