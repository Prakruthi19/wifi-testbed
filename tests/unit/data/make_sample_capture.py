"""Writes sample_capture.pcap: a small MADE-UP 802.11 capture for tests and the demo page.

    python tests/unit/data/make_sample_capture.py   (needs scapy; the pcap is committed, so tests do not)

It is synthetic, not recorded from the lab. It tells two short stories that the capture analysis
must find:
  * client 02:00:00:00:01:00 joins the open network "lab-open": auth, association, DHCP
    (Discover, Offer, Request, ACK) and a DNS lookup of gw.lab, all in the clear;
  * client 02:00:00:00:02:00 joins "lab-wpa2", the 4-way handshake stops after message 3
    (message 4 never comes, and message 3 is resent once with the Retry bit), and the AP sends
    a deauthentication with reason 15 (4-way handshake timeout).
Beacons from both APs and a probe request fill in the background.
"""

from pathlib import Path

from scapy.all import (BOOTP, DHCP, DNS, DNSQR, DNSRR, EAPOL, IP, LLC, SNAP, UDP, Dot11,
                       Dot11AssoReq, Dot11AssoResp, Dot11Auth, Dot11Beacon, Dot11Deauth, Dot11Elt,
                       Dot11ProbeReq, RadioTap, wrpcap)

AP_OPEN, AP_WPA2 = "02:00:00:00:00:00", "02:00:00:00:03:00"
STA1, STA2 = "02:00:00:00:01:00", "02:00:00:00:02:00"
BCAST = "ff:ff:ff:ff:ff:ff"
RSN = bytes.fromhex("0100000fac040100000fac040100000fac020c00")  # WPA2-PSK, CCMP, MFP capable

RATES = Dot11Elt(ID=1, info=bytes([0x82, 0x84, 0x8b, 0x96]))


def rt(dbm: int):
    return RadioTap(present="Flags+Rate+Channel+dBm_AntSignal", Flags=0, Rate=12,
                    ChannelFrequency=2437, ChannelFlags=0xA0, dBm_AntSignal=dbm)


def mgmt(sub: int, a1: str, a2: str, a3: str, retry: bool = False):
    return Dot11(type=0, subtype=sub, addr1=a1, addr2=a2, addr3=a3, FCfield=0x08 if retry else 0)


def data(a1: str, a2: str, a3: str, to_ds: bool):
    return Dot11(type=2, subtype=0, addr1=a1, addr2=a2, addr3=a3, FCfield=0x01 if to_ds else 0x02)


def eapol_key(msg: int) -> bytes:
    # Key Information: version 2 (HMAC-SHA1/AES), pairwise; plus ACK / MIC / install / secure per message.
    info = 0x0002 | 0x0008 | {1: 0x0080, 2: 0x0100, 3: 0x0080 | 0x0100 | 0x0040 | 0x0200 | 0x1000,
                                4: 0x0100 | 0x0200}[msg]
    body = bytes([2]) + info.to_bytes(2, "big") + (16).to_bytes(2, "big") + (msg).to_bytes(8, "big")
    body += (bytes(32) if msg == 4 else bytes([msg]) * 32) + bytes(16) + bytes(8) + bytes(8) + bytes(16) + (0).to_bytes(2, "big")
    return body


def build():
    pkts, t = [], 1_790_000_000.0

    def add(p, dt=0.01):
        nonlocal t
        t += dt
        p.time = t
        pkts.append(p)

    def beacon(ap, ssid, rsn):
        p = rt(-40) / mgmt(8, BCAST, ap, ap) / Dot11Beacon(cap=0x0011 if rsn else 0x0001) / Dot11Elt(ID=0, info=ssid)
        return p / Dot11Elt(ID=48, info=RSN) if rsn else p

    for _ in range(3):
        add(beacon(AP_OPEN, b"lab-open", False), 0.1)
        add(beacon(AP_WPA2, b"lab-wpa2", True), 0.002)
    add(rt(-55) / mgmt(4, BCAST, STA1, BCAST) / Dot11ProbeReq() / Dot11Elt(ID=0, info=b""))

    # Story 1: open network, full join with DHCP and DNS.
    add(rt(-52) / mgmt(11, AP_OPEN, STA1, AP_OPEN) / Dot11Auth(algo=0, seqnum=1, status=0))
    add(rt(-41) / mgmt(11, STA1, AP_OPEN, AP_OPEN) / Dot11Auth(algo=0, seqnum=2, status=0))
    add(rt(-52) / mgmt(0, AP_OPEN, STA1, AP_OPEN) / Dot11AssoReq(cap=0x0001) / Dot11Elt(ID=0, info=b"lab-open"))
    add(rt(-41) / mgmt(1, STA1, AP_OPEN, AP_OPEN) / Dot11AssoResp(cap=0x0001, status=0, AID=1) / RATES)
    mac1 = bytes.fromhex(STA1.replace(":", ""))
    for kind, src, dst, ip_src, ip_dst, yi in [
        ("discover", STA1, BCAST, "0.0.0.0", "255.255.255.255", "0.0.0.0"),
        ("offer", AP_OPEN, STA1, "192.168.50.1", "192.168.50.100", "192.168.50.100"),
        ("request", STA1, BCAST, "0.0.0.0", "255.255.255.255", "0.0.0.0"),
        ("ack", AP_OPEN, STA1, "192.168.50.1", "192.168.50.100", "192.168.50.100"),
    ]:
        to_ds = src == STA1
        hdr = data(AP_OPEN, STA1, dst, True) if to_ds else data(STA1, AP_OPEN, AP_OPEN, False)
        sport, dport = (68, 67) if to_ds else (67, 68)
        opts = [("message-type", kind)] + ([("server_id", "192.168.50.1")] if kind != "discover" else []) + ["end"]
        add(rt(-50 if to_ds else -41) / hdr / LLC() / SNAP() / IP(src=ip_src, dst=ip_dst) / UDP(sport=sport, dport=dport)
            / BOOTP(op=1 if to_ds else 2, chaddr=mac1, xid=0x1234, yiaddr=yi) / DHCP(options=opts), 0.05)
    add(rt(-50) / data(AP_OPEN, STA1, AP_OPEN, True) / LLC() / SNAP() / IP(src="192.168.50.100", dst="192.168.50.1")
        / UDP(sport=40000, dport=53) / DNS(id=7, rd=1, qd=DNSQR(qname="gw.lab")))
    add(rt(-41) / data(STA1, AP_OPEN, AP_OPEN, False) / LLC() / SNAP() / IP(src="192.168.50.1", dst="192.168.50.100")
        / UDP(sport=53, dport=40000) / DNS(id=7, qr=1, aa=1, rd=1, ra=1, qd=DNSQR(qname="gw.lab"),
                                           an=DNSRR(rrname="gw.lab", rdata="192.168.50.1")))

    # Story 2: WPA2, handshake stops after message 3, AP gives up with reason 15.
    add(rt(-67) / mgmt(11, AP_WPA2, STA2, AP_WPA2) / Dot11Auth(algo=0, seqnum=1, status=0), 0.2)
    add(rt(-40) / mgmt(11, STA2, AP_WPA2, AP_WPA2) / Dot11Auth(algo=0, seqnum=2, status=0))
    add(rt(-67) / mgmt(0, AP_WPA2, STA2, AP_WPA2) / Dot11AssoReq(cap=0x0011) / Dot11Elt(ID=0, info=b"lab-wpa2")
        / Dot11Elt(ID=48, info=RSN))
    add(rt(-40) / mgmt(1, STA2, AP_WPA2, AP_WPA2) / Dot11AssoResp(cap=0x0011, status=0, AID=1) / RATES)
    for msg, retry in [(1, False), (2, False), (3, False), (3, True)]:
        from_ap = msg != 2
        hdr = data(STA2, AP_WPA2, AP_WPA2, False) if from_ap else data(AP_WPA2, STA2, AP_WPA2, True)
        if retry:
            hdr.FCfield |= 0x08  # Retry bit
        add(rt(-40 if from_ap else -67) / hdr / LLC() / SNAP(code=0x888E) / EAPOL(version=2, type=3) / eapol_key(msg),
            1.0 if retry else 0.01)
    add(rt(-40) / mgmt(12, STA2, AP_WPA2, AP_WPA2) / Dot11Deauth(reason=15), 1.0)
    add(beacon(AP_OPEN, b"lab-open", False), 0.1)
    return pkts


if __name__ == "__main__":
    out = Path(__file__).with_name("sample_capture.pcap")
    wrpcap(str(out), build())
    print(f"wrote {out}")
