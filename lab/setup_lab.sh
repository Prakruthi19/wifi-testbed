#!/usr/bin/env bash
# Bring up the emulated radios: hwsim radio 0 -> ap0 (root namespace), radios 1..N -> staN,
# each in its own namespace ns-clientN so traffic must cross the emulated air and DHCP.
#
#   sudo lab/setup_lab.sh             # set up (tears down any previous lab first)
#   sudo lab/setup_lab.sh --versions  # print software versions for inventory.yaml
set -euo pipefail

RADIOS=${RADIOS:-4}
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

# Radios 1..N: one client per namespace. The phy moves with its interface.
for i in $(seq 1 $((RADIOS - 1))); do
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
for i in $(seq 1 $((RADIOS - 1))); do
  echo "  ns-client$i: $(ip -n ns-client$i -br link show sta$i)"
done
echo "  capture: hwsim0"
