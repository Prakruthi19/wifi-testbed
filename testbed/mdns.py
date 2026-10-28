"""Device discovery with mDNS (multicast DNS), the way a phone finds a speaker or printer at home.

A device that offers a service (a speaker you can cast to) listens on the multicast address
224.0.0.251, port 5353. A phone that wants to find one sends a question to that same address:
"who offers _googlecast._tcp.local?". Every device on the network hears it, and the speaker
answers with its name, its host name and its address. No server is involved, so discovery only
works if the network passes multicast between the two devices. A guest network or "client
isolation" usually does not, which is why "my phone can't find the speaker" is a classic
home-network ticket.

Standard library only (no avahi, which needs a system-wide daemon and D-Bus: awkward in one
network namespace per device). It implements just the records discovery needs (PTR, SRV, A),
not the whole of RFC 6762: no probing for name conflicts, no caching, no known-answer lists.

    python -m testbed.mdns respond --ip 192.168.50.20 --host speaker --name "Living room speaker"
    python -m testbed.mdns browse --ip 192.168.50.10 --seconds 3
"""

from __future__ import annotations

import argparse
import json
import socket
import struct
import time
from dataclasses import asdict, dataclass

GROUP = "224.0.0.251"
PORT = 5353
CAST = "_googlecast._tcp.local"

TYPE_A, TYPE_PTR, TYPE_SRV = 1, 12, 33
CLASS_IN = 1
CACHE_FLUSH = 0x8000  # top bit of the class in an answer: "replace what you had for this name"
TTL = 120


@dataclass
class Record:
    name: str
    rtype: int
    ttl: int
    data: object  # PTR: target name; SRV: (priority, weight, port, target); A: "a.b.c.d"


@dataclass
class Found:
    """One service instance a browse turned up."""
    instance: str
    host: str | None = None
    port: int | None = None
    address: str | None = None
    answered_by: str | None = None  # source IP of the answer


# -- wire format -------------------------------------------------------------------------------

def encode_name(name: str) -> bytes:
    out = b""
    for label in name.rstrip(".").split("."):
        raw = label.encode()
        out += bytes([len(raw)]) + raw
    return out + b"\x00"


def decode_name(data: bytes, offset: int) -> tuple[str, int]:
    """Read a (possibly compressed) name; returns (name, offset just after it)."""
    labels, end, hops = [], None, 0
    while True:
        length = data[offset]
        if length & 0xC0 == 0xC0:  # pointer to a name earlier in the message
            if end is None:
                end = offset + 2
            offset = ((length & 0x3F) << 8) | data[offset + 1]
            hops += 1
            if hops > 20:
                raise ValueError("name compression loop")
            continue
        offset += 1
        if length == 0:
            break
        labels.append(data[offset:offset + length].decode(errors="replace"))
        offset += length
    return ".".join(labels), end if end is not None else offset


def build_query(name: str, qtype: int = TYPE_PTR) -> bytes:
    header = struct.pack("!HHHHHH", 0, 0, 1, 0, 0, 0)
    return header + encode_name(name) + struct.pack("!HH", qtype, CLASS_IN)


def _rdata(rec: Record) -> bytes:
    if rec.rtype == TYPE_PTR:
        return encode_name(rec.data)
    if rec.rtype == TYPE_SRV:
        prio, weight, port, target = rec.data
        return struct.pack("!HHH", prio, weight, port) + encode_name(target)
    if rec.rtype == TYPE_A:
        return socket.inet_aton(rec.data)
    raise ValueError(f"unsupported record type {rec.rtype}")


def build_response(answers: list[Record], additional: list[Record] = ()) -> bytes:
    """An mDNS answer: id 0, flags 0x8400 (a response, and authoritative)."""
    out = struct.pack("!HHHHHH", 0, 0x8400, 0, len(answers), 0, len(additional))
    for rec in list(answers) + list(additional):
        cls = CLASS_IN if rec.rtype == TYPE_PTR else CLASS_IN | CACHE_FLUSH  # PTR is shared
        rdata = _rdata(rec)
        out += encode_name(rec.name) + struct.pack("!HHIH", rec.rtype, cls, rec.ttl, len(rdata)) + rdata
    return out


def parse_message(data: bytes) -> tuple[bool, list[tuple[str, int]], list[Record]]:
    """Returns (is_response, questions as (name, type), every answer/authority/additional record)."""
    _id, flags, qd, an, ns, ar = struct.unpack("!HHHHHH", data[:12])
    offset, questions, records = 12, [], []
    for _ in range(qd):
        name, offset = decode_name(data, offset)
        qtype, _qclass = struct.unpack("!HH", data[offset:offset + 4])
        offset += 4
        questions.append((name, qtype))
    for _ in range(an + ns + ar):
        name, offset = decode_name(data, offset)
        rtype, _cls, ttl, rdlen = struct.unpack("!HHIH", data[offset:offset + 10])
        offset += 10
        rdata_at, offset = offset, offset + rdlen
        if rtype == TYPE_PTR:
            value = decode_name(data, rdata_at)[0]
        elif rtype == TYPE_SRV:
            prio, weight, port = struct.unpack("!HHH", data[rdata_at:rdata_at + 6])
            value = (prio, weight, port, decode_name(data, rdata_at + 6)[0])
        elif rtype == TYPE_A and rdlen == 4:
            value = socket.inet_ntoa(data[rdata_at:offset])
        else:
            value = data[rdata_at:offset]
        records.append(Record(name, rtype, ttl, value))
    return bool(flags & 0x8000), questions, records


def found_from(records: list[Record], service: str, source: str | None = None) -> list[Found]:
    """Turn the records of one answer into service instances (PTR -> SRV -> A)."""
    srv = {r.name.lower(): r.data for r in records if r.rtype == TYPE_SRV}
    addr = {r.name.lower(): r.data for r in records if r.rtype == TYPE_A}
    out = []
    for r in records:
        if r.rtype != TYPE_PTR or r.name.lower() != service.lower():
            continue
        item = Found(r.data, answered_by=source)
        if r.data.lower() in srv:
            _p, _w, item.port, item.host = srv[r.data.lower()]
            item.address = addr.get(item.host.lower())
        out.append(item)
    return out


# -- sockets -----------------------------------------------------------------------------------

def open_socket(ip: str) -> socket.socket:
    """UDP socket on port 5353 that has joined the mDNS group on the interface that owns `ip`."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", PORT))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                    socket.inet_aton(GROUP) + socket.inet_aton(ip))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
    return sock


def respond(ip: str, host: str, instance: str, service: str = CAST, port: int = 8009,
            seconds: float = 30) -> int:
    """Answer questions about `service` (and our host name) until `seconds` pass. Returns how
    many answers were sent."""
    host_name = f"{host}.local"
    full = f"{instance}.{service}"
    ptr = Record(service, TYPE_PTR, TTL, full)
    srv = Record(full, TYPE_SRV, TTL, (0, 0, port, host_name))
    a = Record(host_name, TYPE_A, TTL, ip)
    sock = open_socket(ip)
    sent, deadline = 0, time.monotonic() + seconds
    while (left := deadline - time.monotonic()) > 0:
        sock.settimeout(left)
        try:
            data, _src = sock.recvfrom(9000)
        except socket.timeout:
            break
        try:
            is_response, questions, _ = parse_message(data)
        except (ValueError, struct.error, IndexError):
            continue
        if is_response:
            continue
        wanted = {n.lower() for n, _t in questions}
        if service.lower() in wanted:
            reply = build_response([ptr], [srv, a])
        elif host_name.lower() in wanted:
            reply = build_response([a])
        else:
            continue
        sock.sendto(reply, (GROUP, PORT))
        sent += 1
    sock.close()
    return sent


def browse(ip: str, service: str = CAST, seconds: float = 3, asks: int = 3) -> list[Found]:
    """Ask who offers `service` (a few times, as real devices do) and collect every answer."""
    sock = open_socket(ip)
    query = build_query(service)
    found: dict[str, Found] = {}
    deadline = time.monotonic() + seconds
    next_ask, asked = 0.0, 0
    while (now := time.monotonic()) < deadline:
        if asked < asks and now >= next_ask:
            sock.sendto(query, (GROUP, PORT))
            asked += 1
            next_ask = now + seconds / asks
        sock.settimeout(max(0.05, min(deadline, next_ask) - time.monotonic()))
        try:
            data, src = sock.recvfrom(9000)
        except socket.timeout:
            continue
        try:
            is_response, _q, records = parse_message(data)
        except (ValueError, struct.error, IndexError):
            continue
        if is_response:
            for item in found_from(records, service, src[0]):
                found.setdefault(item.instance, item)
    sock.close()
    return list(found.values())


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Minimal mDNS responder and browser")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("respond")
    r.add_argument("--ip", required=True)
    r.add_argument("--host", required=True)
    r.add_argument("--name", required=True, help="instance name, e.g. 'Living room speaker'")
    r.add_argument("--service", default=CAST)
    r.add_argument("--port", type=int, default=8009)
    r.add_argument("--seconds", type=float, default=30)
    b = sub.add_parser("browse")
    b.add_argument("--ip", required=True)
    b.add_argument("--service", default=CAST)
    b.add_argument("--seconds", type=float, default=3)
    args = parser.parse_args(argv)
    if args.cmd == "respond":
        print(json.dumps({"answers_sent": respond(args.ip, args.host, args.name, args.service,
                                                  args.port, args.seconds)}), flush=True)
    else:
        print(json.dumps([asdict(f) for f in browse(args.ip, args.service, args.seconds)]), flush=True)


if __name__ == "__main__":
    main()
