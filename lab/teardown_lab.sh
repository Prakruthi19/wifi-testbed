#!/usr/bin/env bash
# Remove everything setup_lab.sh and the tests create. Safe to run repeatedly.
set -uo pipefail
[[ $EUID -eq 0 ]] || { echo "run as root: sudo $0" >&2; exit 1; }

pkill -f 'hostapd .*reports/run' 2>/dev/null
pkill -f 'dnsmasq -C .*reports/run' 2>/dev/null
pkill wpa_supplicant 2>/dev/null
pkill -f 'dhclient .*sta[0-9]' 2>/dev/null
pkill -f 'dumpcap .*hwsim0' 2>/dev/null

nft delete table inet labfw 2>/dev/null
for l in br-lab.10 br-lab.20 br-lab.30 br-lab br-roam; do ip link del "$l" 2>/dev/null; done

for ns in $(ip netns list | awk '/^ns-client/{print $1}'); do
  ip netns del "$ns"
  rm -rf "/etc/netns/$ns"
done

modprobe -r mac80211_hwsim 2>/dev/null
rm -rf /run/testbed
echo "lab down"
