#!/bin/bash
# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
# Provision the engine guest: Docker Engine, gVisor, and the edge firewall.
# The same script serves the lima and wsl drivers. Idempotent. Runs as root.
set -eux -o pipefail
export DEBIAN_FRONTEND=noninteractive
STATE=/var/lib/engine
# Filled in by the driver: the guest user whose session forwards the Docker socket.
ENGINE_USER="__ENGINE_USER__"
mkdir -p "$STATE"

if [ ! -f "$STATE/packages" ]; then
  apt-get update -q
  apt-get install -y -q ca-certificates curl gnupg nftables
  install -m 0755 -d /etc/apt/keyrings
  # Docker's apt repository (key fingerprint checked below).
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  gpg --show-keys --with-colons /etc/apt/keyrings/docker.asc | grep -q "^fpr:::::::::9DC858229FC7DD38854AE2D88D81803C0EBFCD88:"
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list
  # gVisor's apt repository (key fingerprint checked below).
  curl -fsSL https://gvisor.dev/archive.key -o /etc/apt/keyrings/gvisor.asc
  gpg --show-keys --with-colons /etc/apt/keyrings/gvisor.asc | grep -q "^fpr:::::::::6F1DF85E3A71C24918E727D56FC6D554E32BD943:"
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/gvisor.asc] https://storage.googleapis.com/gvisor/releases release main" > /etc/apt/sources.list.d/gvisor.list
  apt-get update -q
  apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-compose-plugin runsc
  touch "$STATE/packages"
fi

# Register gVisor with Docker, without overwriting other daemon settings.
runsc install
# The default Lima user may use the Docker socket; the host reaches it only through
# Lima's forward of that one socket.
if [ -n "$ENGINE_USER" ] && id -u "$ENGINE_USER" >/dev/null 2>&1; then
  usermod -aG docker "$ENGINE_USER"
  mkdir -p /etc/systemd/system/docker.socket.d
  printf '[Socket]\nSocketUser=%s\nSocketMode=0600\n' "$ENGINE_USER" > /etc/systemd/system/docker.socket.d/override.conf
  systemctl daemon-reload
fi
systemctl enable --now docker.socket docker
systemctl restart docker.socket docker

# The edge firewall (decision 0004). Containers may not reach the host, the guest's own
# services, or anything beyond the engine, except addresses explicitly allowed for one
# source network. Everything dropped is logged.
cat > /etc/nftables.d-edge.nft <<'NFT'
table inet edge
delete table inet edge
table inet edge {
  set egress_allow {
    type ipv4_addr . ipv4_addr
    flags interval
  }
  chain forward {
    type filter hook forward priority -10; policy accept;
    ct state established,related accept
    meta nfproto ipv6 iifname { "docker0", "br-*" } log prefix "edge-drop ipv6 " drop
    iifname { "docker0", "br-*" } ip daddr { 192.168.5.0/24, 169.254.0.0/16 } log prefix "edge-drop host " drop
    iifname { "docker0", "br-*" } oifname { "docker0", "br-*" } accept
    iifname { "docker0", "br-*" } ip saddr . ip daddr @egress_allow accept
    iifname { "docker0", "br-*" } log prefix "edge-drop egress " drop
  }
  chain input {
    type filter hook input priority -10; policy accept;
    ct state established,related accept
    iifname { "docker0", "br-*" } log prefix "edge-drop engine " drop
  }
}
NFT
nft -f /etc/nftables.d-edge.nft
cat > /etc/systemd/system/edge-firewall.service <<'UNIT'
[Unit]
Description=Edge firewall for container networks
After=network-pre.target docker.service
[Service]
Type=oneshot
ExecStart=/usr/sbin/nft -f /etc/nftables.d-edge.nft
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable edge-firewall.service

touch "$STATE/provisioned"
