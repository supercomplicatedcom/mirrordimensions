#!/bin/bash
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
  date -u +%Y-%m-%d > "$STATE/updated"
fi

# Updates are installed only when asked (`mirror engine update`), never by themselves:
# an update could restart Docker during a run, and two runs should not differ by a kernel
# nobody chose. `mirror doctor` says when the last update is more than 14 days old.
systemctl disable --now apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true
systemctl disable --now unattended-upgrades.service 2>/dev/null || true
printf 'APT::Periodic::Update-Package-Lists "0";\nAPT::Periodic::Unattended-Upgrade "0";\n' \
  > /etc/apt/apt.conf.d/20auto-upgrades
if command -v snap >/dev/null 2>&1; then
  snap refresh --hold >/dev/null 2>&1 || true
fi

# Docker is restarted only if its configuration changed, so re-applying this script
# never stops a running world without cause.
before="$({ cat /etc/docker/daemon.json /etc/systemd/system/docker.socket.d/override.conf 2>/dev/null || true; } | sha256sum)"
# Register gVisor with Docker (opt-in runtime, decision 0010), keeping other settings.
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
after="$({ cat /etc/docker/daemon.json /etc/systemd/system/docker.socket.d/override.conf 2>/dev/null || true; } | sha256sum)"
if [ "$before" != "$after" ] || [ ! -f "$STATE/provisioned" ]; then
  systemctl restart docker.socket docker
fi

# The edge firewall (decision 0004). Containers may not reach the host, the guest's own
# services, or anything beyond the engine, except addresses explicitly allowed for one
# source network. Everything dropped is logged.
cat > /etc/nftables.d-edge.nft <<'NFT'
table inet edge
delete table inet edge
table inet edge {
  # (source network, destination, TCP port) allowed out: the model routes, nothing else.
  set egress_allow {
    type ipv4_addr . ipv4_addr . inet_service
    flags interval
  }
  # IPv6 beyond the sandbox's own range is logged and dropped here, before routing:
  # whether the guest has an IPv6 route, or forwards IPv6 at all, differs between hosts
  # (none on macOS; a default route on Linux), and either way a packet dropped later
  # would go unrecorded. IPv4 with no route out is likewise dropped before the forward
  # hook, so it is logged here too.
  chain prerouting {
    type filter hook prerouting priority -160; policy accept;
    iifname { "docker0", "br-*" } ip6 daddr != { fe80::/10, ff00::/8, fd4a:4000::/32 } fib daddr type != local log prefix "edge-drop egress " drop
    iifname { "docker0", "br-*" } ip daddr != { 224.0.0.0/4, 255.255.255.255 } fib daddr type != local fib daddr oif missing log prefix "edge-drop egress " drop
  }
  chain forward {
    type filter hook forward priority -10; policy accept;
    ct state established,related accept
    meta nfproto ipv6 iifname { "docker0", "br-*" } log prefix "edge-drop ipv6 " drop
    iifname { "docker0", "br-*" } ip daddr { 192.168.5.0/24, 169.254.0.0/16 } log prefix "edge-drop host " drop
    iifname { "docker0", "br-*" } oifname { "docker0", "br-*" } accept
    iifname { "docker0", "br-*" } ip saddr . ip daddr . tcp dport @egress_allow accept
    iifname { "docker0", "br-*" } log prefix "edge-drop egress " drop
  }
  chain input {
    type filter hook input priority -10; policy accept;
    ct state established,related accept
    # Neighbour discovery must work, or a container's packets never leave it and
    # attempts go unrecorded. Link-local multicast cannot be routed: drop it quietly.
    iifname { "docker0", "br-*" } icmpv6 type { nd-neighbor-solicit, nd-neighbor-advert } accept
    iifname { "docker0", "br-*" } ip daddr { 224.0.0.0/4, 255.255.255.255 } drop
    iifname { "docker0", "br-*" } ip6 daddr ff00::/8 drop
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

sha256sum "$0" 2>/dev/null | cut -d" " -f1 > "$STATE/provision.sha" || true
touch "$STATE/provisioned"
