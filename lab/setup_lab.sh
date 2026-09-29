#!/usr/bin/env bash
# Bring up the emulated radios: hwsim radio 0 -> ap0 (root namespace), radios 1..N -> staN,
# each in its own namespace ns-clientN so traffic must cross the emulated air and DHCP.
#
#   sudo lab/setup_lab.sh             # set up (tears down any previous lab first)
#   sudo ROAM=1 lab/setup_lab.sh      # also a second AP radio, ap1, for the roaming tests
#   sudo HOMENET=1 lab/setup_lab.sh   # home network: ap0 + mesh points ap1, ap2, and five
#                                     # device radios sta1..sta5 (a superset of ROAM=1)
#   sudo lab/setup_lab.sh --versions  # print software versions for inventory.yaml
set -euo pipefail

ROAM=${ROAM:-0}
HOMENET=${HOMENET:-0}
STAS=3        # client radios sta1..staN
EXTRA_APS=0   # AP radios besides ap0: ap1..apN, taken from the last radios
if [[ $ROAM == 1 ]]; then EXTRA_APS=1; fi
if [[ $HOMENET == 1 ]]; then STAS=5; EXTRA_APS=2; fi
RADIOS=${RADIOS:-$((1 + STAS + EXTRA_APS))}
LAST_STA=$((RADIOS - 1 - EXTRA_APS))
COUNTRY=${COUNTRY:-US}
AP_CIDR=${AP_CIDR:-192.168.50.1/24}
HERE=$(cd "$(dirname "$0")" && pwd)

versions() {
  echo "kernel:         $(uname -r)"
  echo "hostapd:        $(hostapd -v 2>&1 | head -1)"
  echo "wpa_supplicant: $(wpa_supplicant -v | head -1)"
  echo "dnsmasq:        $(dnsmasq --version | head -1)"
  echo "tshark:         $(tshark --version | head -1)"
}

if [[ ${1:-} == --versions ]]; then versions; exit 0; fi
[[ $EUID -eq 0 ]] || { echo "run as root: sudo $0" >&2; exit 1; }

bash "$HERE/teardown_lab.sh" >/dev/null 2>&1 || true

# Keep NetworkManager away from the emulated radios so it does not fight hostapd/wpa_supplicant.
if command -v nmcli >/dev/null; then
  cat > /etc/NetworkManager/conf.d/99-hwsim-unmanaged.conf <<'EOF'
[keyfile]
unmanaged-devices=driver:mac80211_hwsim
EOF
  systemctl reload NetworkManager 2>/dev/null || true
fi

iw reg set "$COUNTRY"
modprobe mac80211_hwsim radios="$RADIOS"
sleep 1

# hwsim interfaces in creation order (wlanX names depend on what else exists, so rename them).
mapfile -t IFACES < <(
  for d in /sys/class/net/*; do
    [[ -e $d/phy80211 ]] || continue
    [[ $(basename "$(readlink -f "$d/device/driver" 2>/dev/null)") == mac80211_hwsim ]] || continue
    echo "$(cat "$d/phy80211/index") $(basename "$d")"
  done | sort -n | awk '{print $2}'
)
(( ${#IFACES[@]} == RADIOS )) || { echo "expected $RADIOS hwsim interfaces, found ${#IFACES[@]}" >&2; exit 1; }

# Radio 0: access point side.
ip link set "${IFACES[0]}" down
ip link set "${IFACES[0]}" name ap0
ip addr add "$AP_CIDR" dev ap0
ip link set ap0 up

# Extra AP radios (roaming: ap1; home network: ap1, ap2 as mesh points). Root namespace, no IP:
# the tests bridge them with ap0 so every AP serves one network.
for j in $(seq 1 "$EXTRA_APS"); do
  ifc=${IFACES[$((LAST_STA + j))]}
  ip link set "$ifc" down
  ip link set "$ifc" name "ap$j"
  ip link set "ap$j" up
done

# Radios 1..LAST_STA: one client per namespace. The phy moves with its interface.
for i in $(seq 1 "$LAST_STA"); do
  ifc=${IFACES[$i]}
  ns=ns-client$i
  phy=$(cat "/sys/class/net/$ifc/phy80211/name")
  ip link set "$ifc" down
  ip link set "$ifc" name "sta$i"
  ip netns add "$ns"
  iw phy "$phy" set netns name "$ns"
  ip -n "$ns" link set lo up
  ip -n "$ns" link set "sta$i" up
  # `ip netns exec` bind-mounts this over /etc/resolv.conf, so dhclient never touches the host's.
  mkdir -p "/etc/netns/$ns"
  : > "/etc/netns/$ns/resolv.conf"
done

# hwsim0 sees every emulated 802.11 frame, with radiotap headers.
ip link set hwsim0 up
mkdir -p /run/testbed

echo "lab up:"
iw dev | awk '/Interface/{print "  root: "$2}'
for i in $(seq 1 "$LAST_STA"); do
  echo "  ns-client$i: $(ip -n ns-client$i -br link show sta$i)"
done
echo "  capture: hwsim0"
