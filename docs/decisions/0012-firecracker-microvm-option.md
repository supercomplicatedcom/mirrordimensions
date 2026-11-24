# 0012. Firecracker microVMs for agents on hosts that can nest (Apple M3+, nested KVM)

Status: Accepted (owner) for building the option; the rest Proposed · Date: 2026-11-23 · Milestone: engine now (with M1); agents use it from M4

## Context

Decision 0010 runs agents as hardened containers inside the dedicated engine VM. The reason was that gVisor gives itself away, and a microVM per agent needs nested virtualization, which the owner's first-generation Apple Silicon Mac (M1) lacks. The owner asked for the microVM option to be built as well, for Macs that can nest. That gives an agent its own kernel, with hardware isolation from the engine and from twins, which is the strongest option short of separate machines.

Facts, checked while building this:

- **Lima 2.3** offers `nestedVirtualization`. With Apple's Virtualization.framework it works on **Apple M3 or later with macOS 15 or later**. On Linux it works when the host's KVM module allows nesting.
- **Firecracker** is run for containers through **Kata Containers 4.4.0**. Kata does not bundle the `firecracker` binary. It is tested with **Firecracker v1.17.0** (its `versions.yaml`), not the latest 1.18.0, and runs it through its Rust runtime (`runtime-rs`) with `configuration-rs-fc.toml`. Kata 4.4 refuses `KATA_CONF_FILE` unless it resolves to one of its default configuration paths, so provisioning links the first of them, `/etc/kata-containers/runtime-rs/configuration.toml`, to the shipped `configuration-rs-fc.toml` (found in CI, 2026-11-23). Its shipped Firecracker configuration also fails Kata's own validation (`dial_timeout_ms = 45000` with the default `reconnect_timeout_ms = 3000`); provisioning sets a 10 ms retry interval and a 45 s budget.
- **Firecracker has no shared file system**, so Kata needs container root file systems as block devices: containerd's **devmapper snapshotter** on a thin pool.
- **Kata's Docker support** uses its deprecated Go runtime and is tested only with QEMU. Firecracker is run through **containerd** (`ctr` or the containerd API), not Docker.
- Kata's static releases publish no checksums. They are pinned here on first download.

## Decision

1. **An opt-in engine capability:** `mirror engine setup --microvm`.
   - It checks the host first. On a Mac it reads the chip and the macOS version; on Linux, the KVM `nested` parameter.
   - On a host that cannot nest it refuses, naming the reason. On the M1: "Apple M1 Pro cannot run nested VMs; Apple M3 or later is needed".
   - When supported, it turns on Lima's `nestedVirtualization` (for an existing engine it stops the VM, edits its configuration and restarts it). It then applies `engine/provision/microvm.sh`.

2. **`microvm.sh`** installs, inside the engine:
   - Kata Containers 4.4.0 from its static release, pinned by SHA-256;
   - Firecracker v1.17.0 and its jailer from Firecracker's release, checked against the published SHA-256;
   - a shim, `containerd-shim-kata-fc-v2`, so containerd runs `io.containerd.kata-fc.v2` with Kata's Firecracker configuration;
   - a devmapper thin pool on sparse files, recreated at every boot by a systemd unit;
   - the devmapper snapshotter in containerd's configuration.

   containerd is restarted only when its configuration changes. The script uses only containerd, so it also runs directly on a Linux host.

3. **Twins and the sandbox infrastructure stay on Docker.** Only agent and browser workloads will use the microVM runtime. Running them is M4 work, when agent containers are launched at all. It will need:
   - the containerd socket forwarded like the Docker socket (decision 0003);
   - a typed client for it;
   - the microVM's network attached to `corp-lan`.

4. **`mirror engine check`** runs a workload in a Firecracker microVM through containerd and confirms it has its own kernel. It also scans `uname`, `/proc/cmdline` and `dmesg` inside the microVM for Kata and Firecracker tells. The guest kernel command line carries Kata's own parameters (`agent.*`, `systemd.unit=kata-containers.target`; tell 18). The owner chose to hide it: the runtime's shim adds `/proc/cmdline` to every microVM container's OCI `maskedPaths` before Kata reads the spec, so it reads as empty, and the check confirms it. Replacing it with an ordinary boot line is not possible, because Kata's agent, like runc, refuses mounts over it.

5. **Isolation.** A microVM agent reports boundary `microvm` inside the engine's `dedicated-vm`. The level is `full` when every suite passes.

## How it is verified without an M3

- **CI:** a job runs the same `microvm.sh` and the same checks directly on a GitHub-hosted Linux runner, which has `/dev/kvm`. That proves Kata, Firecracker, the thin pool and containerd on x64.
- **The M3 path** is unverified until someone runs `mirror engine setup --microvm` and `mirror engine check` on an M3 or later Mac with macOS 15 or later. It is labelled that way in `docs/platforms.md`.

## Consequences

- The strongest isolation option exists for capable hosts. Hosts that cannot nest keep 0010's design.
- Two container managers live in the engine: Docker for the world, containerd directly for microVM agents. Capture is unaffected, because microVM agents attach to the same agent network behind the same gateway, resolver and firewall.
- About 1 GB of extra download, and a thin pool of up to 40 GB (sparse) in the engine.

## Alternatives considered

- **Kata with QEMU or Cloud Hypervisor through Docker.** Simpler, since it uses shared file systems and Docker. But it isn't Firecracker, and Kata's Docker path is deprecated.
- **Firecracker without Kata** (build root file systems from images, boot them, attach taps). Fewer layers, but the agent would see whatever init we add. Kata keeps its agent outside the container's namespaces.

## To verify

- The M3 path end to end.
- Kata's guest kernel command line and boot messages inside the microVM, as seen by the workload. Seen in CI (tell 18); the command line is now masked and the boot messages restricted.
- Attaching a microVM's network to the `corp-lan` bridge with Kata's networking (M4).
