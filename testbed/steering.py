"""Router-assisted roaming: 802.11k (neighbor reports) and 802.11v (BSS transition requests).

Without these, a device decides alone when and where to move, and it only knows about the APs
it happened to find in its last scan. With them, the network helps:

- 802.11k, neighbor report: the device asks its AP "which other APs of this network are near
  you?" and gets a short list (BSSID, channel), so it can scan just those channels instead of
  all of them. Like asking a shop assistant which other branches are nearby.
- 802.11v, BSS Transition Management (BTM): the AP asks the device to move, and names where to
  ("please go to the living-room mesh point"). The device answers yes (status 0) and moves, or
  says no with a reason, and stays. Mesh systems use it for band and load steering.

hostapd provides both (`rrm_neighbor_report=1`, `bss_transition=1`); the list of neighbors is
filled in with `hostapd_cli set_neighbor`, and the request is sent with `hostapd_cli bss_tm_req`.
wpa_supplicant sends the neighbor request (`wpa_cli neighbor_rep_request`) and handles a BTM
request by itself. Both log what happened, which is what the tests read.
"""

from __future__ import annotations

import re

PHY_HT = 7  # 802.11n; every AP here runs ieee80211n=1


def op_class(channel: int) -> int:
    """Global operating class of a 20 MHz channel (IEEE 802.11 Annex E, table E-4)."""
    if 1 <= channel <= 13:
        return 81
    if 36 <= channel <= 48:
        return 115
    if 52 <= channel <= 64:
        return 118
    if 100 <= channel <= 144:
        return 121
    if 149 <= channel <= 165:
        return 125
    raise ValueError(f"no operating class for channel {channel}")


def neighbor_element(bssid: str, channel: int) -> str:
    """Hex body of a Neighbor Report element for `hostapd_cli set_neighbor ... nr=`:
    BSSID (6 bytes), BSSID information (4 bytes, 0 = nothing claimed), operating class,
    channel, PHY type."""
    return (bssid.replace(":", "").lower() + "00000000"
            + f"{op_class(channel):02x}{channel:02x}{PHY_HT:02x}")


def btm_candidate(bssid: str, channel: int, preference: int = 255) -> str:
    """`neighbor=` value for `hostapd_cli bss_tm_req`: BSSID, BSSID information, operating class,
    channel, PHY type, and a preference subelement (id 3, length 1, value) so the device knows
    this is the AP we want it on."""
    return f"{bssid.lower()},0x0000,{op_class(channel)},{channel},{PHY_HT},0301{preference:02x}"


_RE_NR = re.compile(r"RRM-NEIGHBOR-REP-RECEIVED bssid=([0-9a-f:]{17})(.*)", re.I)
_RE_KV = re.compile(r"(\w+)=(\S+)")
_RE_BTM_RESP = re.compile(r"BSS-TM-RESP ([0-9a-f:]{17})(.*)", re.I)


def parse_neighbor_reports(log_text: str) -> list[dict]:
    """Every neighbor the client was told about (wpa_supplicant log), in order received."""
    out = []
    for m in _RE_NR.finditer(log_text):
        entry = {"bssid": m.group(1).lower()}
        for k, v in _RE_KV.findall(m.group(2)):
            entry[k] = int(v, 0) if re.fullmatch(r"0x[0-9a-f]+|\d+", v, re.I) else v
        out.append(entry)
    return out


def parse_btm_responses(log_text: str, sta: str | None = None) -> list[dict]:
    """Each device's answer to a BSS transition request (hostapd log): status_code 0 = accepted,
    target_bssid = where it said it would go."""
    out = []
    for m in _RE_BTM_RESP.finditer(log_text):
        if sta and m.group(1).lower() != sta.lower():
            continue
        entry = {"sta": m.group(1).lower()}
        for k, v in _RE_KV.findall(m.group(2)):
            entry[k] = int(v) if v.isdigit() else v.lower()
        out.append(entry)
    return out


# Status codes a device can send back (IEEE 802.11 table 9-428), in plain words.
BTM_STATUS = {
    0: "accepted",
    1: "rejected, no reason given",
    2: "rejected, not enough beacons seen",
    3: "rejected, not enough capacity",
    4: "rejected, termination not wanted",
    5: "rejected, termination delay requested",
    6: "rejected, device offered its own candidate list",
    7: "rejected, no suitable candidate",
    8: "rejected, leaving the network",
}
