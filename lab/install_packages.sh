#!/usr/bin/env bash
# One-time VM setup (Ubuntu 24.04): packages the lab and tests need, plus the Python venv.
set -euo pipefail
cd "$(dirname "$0")/.."

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  hostapd wpasupplicant iw iproute2 dnsmasq tshark wireshark \
  isc-dhcp-client bind9-dnsutils netcat-openbsd nftables iperf3 \
  python3-venv "linux-modules-extra-$(uname -r)"

# The distro services would grab the radios / port 53 on their own; the tests start them.
sudo systemctl disable --now hostapd dnsmasq 2>/dev/null || true

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
echo "done: now run sudo lab/setup_lab.sh"
