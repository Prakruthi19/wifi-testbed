#!/usr/bin/env bash
# Over-the-air capture with a real USB Wi-Fi adapter in monitor mode.
#
# DESIGNED, NOT RUN: written without a monitor-capable adapter. Unlike hwsim0, a real sniffer
# only hears one channel at a time, misses frames (weak signal, collisions, its own limits), and
# must match the AP's channel and width or it sees nothing useful.
#
#   sudo lab/monitor_capture.sh <iface> <channel> [HT20|HT40+|HT40-|80MHz] [out.pcap] [seconds]
#   sudo lab/monitor_capture.sh wlx00c0ca123456 36 80MHz /tmp/ota.pcap 60
#
# Then classify it like any lab capture (--sta = the device's MAC; WPA2 only for decryption):
#   .venv/bin/python -m classifier.classify_join /tmp/ota.pcap --sta <mac> --wpa-pwd PASS:SSID
set -euo pipefail

iface=${1:?usage: $0 <iface> <channel> [width] [out.pcap] [seconds]}
channel=${2:?channel required}
width=${3:-HT20}
out=${4:-/tmp/ota-$(date +%Y%m%d-%H%M%S).pcap}
seconds=${5:-60}

# NetworkManager would take the adapter back out of monitor mode.
nmcli device set "$iface" managed no 2>/dev/null || true

ip link set "$iface" down
iw dev "$iface" set type monitor
ip link set "$iface" up
iw dev "$iface" set channel "$channel" "$width"
iw dev "$iface" info

echo "capturing ${seconds}s on $iface ch$channel $width -> $out"
# Write to /tmp first: dumpcap drops privileges and may not be able to write into a home folder.
tmp=$(mktemp /tmp/ota-XXXXXX.pcap)
dumpcap -q -P -i "$iface" -a "duration:$seconds" -w "$tmp"
mv "$tmp" "$out"
echo "done: $out ($(stat -c %s "$out") bytes)"

# Put the adapter back in managed mode.
ip link set "$iface" down
iw dev "$iface" set type managed
ip link set "$iface" up
nmcli device set "$iface" managed yes 2>/dev/null || true
