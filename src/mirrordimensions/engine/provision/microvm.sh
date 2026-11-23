#!/bin/bash
# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
# Optional microVM runtime for agents (decision 0012): Kata Containers with the Firecracker
# hypervisor, driven through containerd with the devmapper snapshotter (Firecracker has no
# shared file system, so container root file systems must be block devices).
#
# Needs /dev/kvm in the guest: nested virtualization on Apple M3 or later (macOS 15+),
# or a Linux host whose KVM allows nesting. Idempotent. Runs as root. Uses only containerd,
# so it can also run directly on a Linux host (the CI job does this).
set -eux -o pipefail
export DEBIAN_FRONTEND=noninteractive
STATE=/var/lib/engine
mkdir -p "$STATE"

KATA_VERSION="4.4.0"
# Kata 4.4 is tested with Firecracker v1.17.0 (its versions.yaml) and does not bundle it.
FC_VERSION="v1.17.0"
case "$(uname -m)" in
  aarch64) KATA_ARCH=arm64; KATA_SHA256="__KATA_SHA256_ARM64__"; FC_ARCH=aarch64; FC_SHA256="__FC_SHA256_AARCH64__" ;;
  x86_64)  KATA_ARCH=amd64; KATA_SHA256="__KATA_SHA256_AMD64__"; FC_ARCH=x86_64; FC_SHA256="__FC_SHA256_X86_64__" ;;
  *) echo "microVM runtime: unsupported architecture $(uname -m)" >&2; exit 1 ;;
esac

if [ ! -c /dev/kvm ]; then
  echo "microVM runtime: /dev/kvm is missing; nested virtualization is not available" >&2
  exit 3
fi

command -v zstd >/dev/null || apt-get install -y -q zstd
command -v dmsetup >/dev/null || apt-get install -y -q dmsetup thin-provisioning-tools

# 1. Kata Containers (static release, checksum pinned on first download).
if [ ! -x /opt/kata/runtime-rs/bin/containerd-shim-kata-v2 ] || [ "$(cat "$STATE/kata.version" 2>/dev/null)" != "$KATA_VERSION" ]; then
  archive="/var/cache/kata-static-${KATA_VERSION}-${KATA_ARCH}.tar.zst"
  if [ ! -f "$archive" ] || ! echo "$KATA_SHA256  $archive" | sha256sum --check --status; then
    curl -fsSL -o "$archive.part" "https://github.com/kata-containers/kata-containers/releases/download/${KATA_VERSION}/kata-static-${KATA_VERSION}-${KATA_ARCH}.tar.zst"
    mv "$archive.part" "$archive"
  fi
  echo "$KATA_SHA256  $archive" | sha256sum --check --strict
  rm -rf /opt/kata
  zstd -dc "$archive" | tar -xf - -C /
  echo "$KATA_VERSION" > "$STATE/kata.version"
fi

# Firecracker and its jailer, where Kata's configuration expects them (/opt/kata/bin).
if [ "$(/opt/kata/bin/firecracker --version 2>/dev/null | head -1 | awk '{print $2}')" != "$FC_VERSION" ]; then
  fc="/var/cache/firecracker-${FC_VERSION}-${FC_ARCH}.tgz"
  curl -fsSL -o "$fc" "https://github.com/firecracker-microvm/firecracker/releases/download/${FC_VERSION}/firecracker-${FC_VERSION}-${FC_ARCH}.tgz"
  echo "$FC_SHA256  $fc" | sha256sum --check --strict
  tmp=$(mktemp -d)
  tar -xzf "$fc" -C "$tmp"
  install -m 0755 "$tmp/release-${FC_VERSION}-${FC_ARCH}/firecracker-${FC_VERSION}-${FC_ARCH}" /opt/kata/bin/firecracker
  install -m 0755 "$tmp/release-${FC_VERSION}-${FC_ARCH}/jailer-${FC_VERSION}-${FC_ARCH}" /opt/kata/bin/jailer
  rm -rf "$tmp"
fi
/opt/kata/bin/firecracker --version | head -1

# containerd finds runtime io.containerd.kata-fc.v2 as the binary containerd-shim-kata-fc-v2.
# Kata 4.4 runs Firecracker through its Rust runtime (runtime-rs).
# Kata 4.4 accepts a configuration only at one of its default paths (KATA_CONF_FILE
# elsewhere is refused), so the first of them names the shipped Firecracker one.
mkdir -p /etc/kata-containers/runtime-rs
ln -sfn /opt/kata/share/defaults/kata-containers/runtime-rs/configuration-rs-fc.toml \
  /etc/kata-containers/runtime-rs/configuration.toml
test -f /etc/kata-containers/runtime-rs/configuration.toml
cat > /usr/local/bin/containerd-shim-kata-fc-v2 <<'SHIM'
#!/bin/sh
exec /opt/kata/runtime-rs/bin/containerd-shim-kata-v2 "$@"
SHIM
chmod 0755 /usr/local/bin/containerd-shim-kata-fc-v2

# 2. A devmapper thin pool on sparse files, recreated at every boot.
POOL_DIR=/var/lib/containerd/devmapper
mkdir -p "$POOL_DIR"
cat > /usr/local/sbin/engine-thinpool <<'POOL'
#!/bin/bash
set -eu
POOL_DIR=/var/lib/containerd/devmapper
dmsetup status engine-thinpool >/dev/null 2>&1 && exit 0
[ -f "$POOL_DIR/data" ] || truncate -s 40G "$POOL_DIR/data"
[ -f "$POOL_DIR/meta" ] || truncate -s 2G "$POOL_DIR/meta"
DATA=$(losetup --find --show "$POOL_DIR/data")
META=$(losetup --find --show "$POOL_DIR/meta")
SECTORS=$(($(blockdev --getsize64 "$DATA") / 512))
dmsetup create engine-thinpool --table "0 $SECTORS thin-pool $META $DATA 128 32768 1 skip_block_zeroing"
POOL
chmod 0755 /usr/local/sbin/engine-thinpool
cat > /etc/systemd/system/engine-thinpool.service <<'UNIT'
[Unit]
Description=Thin pool for microVM container images
Before=containerd.service
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/engine-thinpool
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable engine-thinpool.service
/usr/local/sbin/engine-thinpool

# 3. containerd: the devmapper snapshotter, added in the format the existing file uses.
#    Docker's containerd package ships an unversioned (version 1) file that disables "cri"
#    by its short name; adding a version line would make that name invalid, so an
#    unversioned file gets the version 1 section name, and a versioned file the full one.
#    containerd is restarted only if the configuration changed.
mkdir -p /etc/containerd
CONF=/etc/containerd/config.toml
touch "$CONF"
before="$(sha256sum "$CONF")"
if ! grep -qE 'io.containerd.snapshotter.v1.devmapper|plugins.devmapper' "$CONF"; then
  if grep -q '^version *=' "$CONF"; then
    section='[plugins."io.containerd.snapshotter.v1.devmapper"]'
  else
    section='[plugins.devmapper]'
  fi
  cat >> "$CONF" <<TOML

$section
  pool_name = "engine-thinpool"
  root_path = "/var/lib/containerd/devmapper"
  base_image_size = "8GB"
  discard_blocks = true
TOML
fi
after="$(sha256sum "$CONF")"
if [ "$before" != "$after" ]; then
  systemctl restart containerd || { journalctl -u containerd --no-pager | tail -30; exit 1; }
fi
ctr plugins ls | grep -E 'devmapper +linux/[a-z0-9]+ +ok'

touch "$STATE/microvm"
