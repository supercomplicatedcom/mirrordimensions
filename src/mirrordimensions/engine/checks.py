# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Engine checks for M0.5: check the engine from the outside.

Each check starts real containers in the engine and tries what must fail. Every
"must fail" check also runs a positive control, so a check that cannot fail is caught.
"""

from __future__ import annotations

import os
import re
import socket
import stat
import subprocess
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Literal

from pydantic import BaseModel

from mirrordimensions.engine import docker_tls
from mirrordimensions.engine.docker_api import Docker
from mirrordimensions.engine.lima import LimaEngine
from mirrordimensions.engine.wsl import DOCKER_PORT, WslEngine
from mirrordimensions.hostos.files import owner_only_problem

CheckedEngine = LimaEngine | WslEngine

PROBE_IMAGE = "alpine:3.22"
HOST_ALIASES = (
    "host.lima.internal",
    "host.docker.internal",
    "gateway.docker.internal",
    "192.168.5.2",
)
ROSETTA_MOUNT = "/mnt/lima-rosetta"
OUTSIDE_TARGET = "1.1.1.1"
OTHER_TARGET = "9.9.9.9"


class CheckResult(BaseModel):
    name: str
    outcome: Literal["pass", "fail", "skip"]
    detail: str = ""


@contextmanager
def host_listener(port: int = 0) -> Generator[int]:
    """A TCP listener on the host's loopback; any connection to it is recorded. `port`
    asks for a particular port (0: any free one)."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", port))
    server.listen(8)
    server.settimeout(0.5)
    port = server.getsockname()[1]
    stop = threading.Event()

    def accept() -> None:
        while not stop.is_set():
            try:
                conn, _ = server.accept()
                conn.close()
            except OSError:
                continue

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        stop.set()
        server.close()
        thread.join(timeout=2)


def _endpoint_check(engine: CheckedEngine) -> CheckResult:
    name = "Docker endpoint is owner-only"
    if isinstance(engine, LimaEngine):
        sock = engine.socket_path
        mode = stat.S_IMODE(sock.stat().st_mode)
        dir_mode = stat.S_IMODE(sock.parent.stat().st_mode)
        ok = mode & 0o077 == 0 and dir_mode & 0o077 == 0
        return CheckResult(
            name=name,
            outcome="pass" if ok else "fail",
            detail=f"socket {oct(mode)}, folder {oct(dir_mode)}",
        )
    # TCP with mutual TLS: the client key is the owner's alone, and the daemon refuses a
    # connection that offers no client certificate.
    found = docker_tls.client_files(engine.tls_dir)
    if found is None:
        return CheckResult(name=name, outcome="fail", detail="no client certificate")
    problem = owner_only_problem(engine.tls_dir / docker_tls.KEY_FILE)
    refused = tls_refuses_without_certificate("127.0.0.1", DOCKER_PORT, found[0])
    ok = problem is None and refused
    detail = "client key owner-only; a connection without the client certificate is refused"
    if problem is not None:
        detail = f"client key: {problem}"
    elif not refused:
        detail = "the daemon accepted a connection without a client certificate"
    return CheckResult(name=name, outcome="pass" if ok else "fail", detail=detail)


def tls_refuses_without_certificate(host: str, port: int, ca_file: str) -> bool:
    """True if a TLS server that requires client certificates turns away one without."""
    import ssl

    context = ssl.create_default_context(cafile=ca_file)
    try:
        with (
            socket.create_connection((host, port), timeout=10) as raw,
            context.wrap_socket(raw, server_hostname=host) as tls,
        ):
            # TLS 1.3 reports a missing certificate only at the first read.
            tls.sendall(b"GET /_ping HTTP/1.1\r\nHost: docker\r\n\r\n")
            return not tls.recv(16)
    except (ssl.SSLError, OSError):
        return True


def _nc(docker: Docker, target: str, port: int, network: str | None = None) -> bool:
    """True if a container can open a TCP connection to target:port."""
    out = docker.run(PROBE_IMAGE, ["sh", "-c", f"nc -z -w 3 {target} {port}"], network=network)
    return out.exit_code == 0


def run_checks(engine: CheckedEngine) -> list[CheckResult]:
    results: list[CheckResult] = []
    docker = Docker(engine.docker_endpoint())
    docker.pull(PROBE_IMAGE)

    # 1. gVisor runs containers.
    runtimes = docker.runtimes()
    if "runsc" in runtimes:
        out = docker.run(PROBE_IMAGE, ["dmesg"], runtime="runsc")
        if out.exit_code != 0 and "not permitted" in out.output:
            # gVisor release-20261123.1 and later refuse the kernel log without CAP_SYSLOG,
            # as Linux does with dmesg_restrict. This throwaway probe is given it to look.
            out = docker.run(PROBE_IMAGE, ["dmesg"], runtime="runsc", cap_add=["SYSLOG"])
        ok = out.exit_code == 0 and "gVisor" in out.output
        results.append(
            CheckResult(
                name="gVisor runs a container",
                outcome="pass" if ok else "fail",
                detail="runsc registered" if ok else out.output[-300:],
            )
        )
    else:
        results.append(
            CheckResult(
                name="gVisor runs a container",
                outcome="fail",
                detail=f"runtimes: {', '.join(runtimes)}",
            )
        )

    # 2. Rosetta runs amd64 images on Apple Silicon.
    info = docker.info()
    if info.get("Architecture") == "aarch64":
        docker.pull(PROBE_IMAGE, platform="linux/amd64")
        out = docker.run(PROBE_IMAGE, ["uname", "-m"], platform="linux/amd64")
        ok = out.exit_code == 0 and out.output.strip() == "x86_64"
        results.append(
            CheckResult(
                name="An amd64 image runs under Rosetta",
                outcome="pass" if ok else "fail",
                detail=out.output.strip()[-200:],
            )
        )
    else:
        results.append(
            CheckResult(
                name="An amd64 image runs under Rosetta", outcome="skip", detail="engine is x64"
            )
        )

    # 3. The Docker endpoint is the owner's alone.
    results.append(_endpoint_check(engine))

    # 4. No host folder is visible in the engine or a container.
    mounts = engine.shell("cat", "/proc/mounts").stdout
    shared = [
        line
        for line in mounts.splitlines()
        if any(k in line for k in ("virtiofs", "9p", "sshfs", "/Users", "/mnt/c", "/mnt/wsl"))
    ]
    # The one allowed share: Apple's Rosetta runtime, which Virtualization.framework
    # exposes so amd64 programs can run. It holds two Apple binaries and must not be
    # writable, even by root in the guest (decision 0004).
    rosetta = [line for line in shared if line.startswith(f"vz-rosetta {ROSETTA_MOUNT} ")]
    others = [line for line in shared if line not in rosetta]
    writable = (
        bool(rosetta)
        and engine.shell(
            "sudo",
            "sh",
            "-c",
            f"touch {ROSETTA_MOUNT}/.write-probe && rm -f {ROSETTA_MOUNT}/.write-probe",
        ).returncode
        == 0
    )
    if others or writable:
        detail = "; ".join(others)[:300] or f"{ROSETTA_MOUNT} is writable from the guest"
        results.append(
            CheckResult(name="No host folder in the engine", outcome="fail", detail=detail)
        )
    else:
        detail = "only the read-only Rosetta runtime share" if rosetta else "no shares"
        results.append(
            CheckResult(name="No host folder in the engine", outcome="pass", detail=detail)
        )

    # 5. The host's loopback and host aliases are unreachable from containers.
    host = engine.host_address()
    with host_listener() as port:
        control = engine.shell("sh", "-c", f"nc -z -w 3 {host} {port}").returncode == 0
        aliases = (*HOST_ALIASES, host) if host not in HOST_ALIASES else HOST_ALIASES
        reached = [alias for alias in aliases if _nc(docker, alias, port)]
    if not control and isinstance(engine, WslEngine):
        # WSL does not forward the guest to Windows' loopback in every networking mode, so
        # there may be no positive control. Unverified on hardware: see the checklist.
        results.append(
            CheckResult(
                name="Host loopback unreachable from containers",
                outcome="fail" if reached else "skip",
                detail=f"reached via {', '.join(reached)}"
                if reached
                else f"the guest itself cannot reach Windows' loopback at {host}, so "
                "containers cannot either; no positive control in this networking mode",
            )
        )
    elif not control:
        results.append(
            CheckResult(
                name="Host loopback unreachable from containers",
                outcome="fail",
                detail="positive control failed: the guest itself could not reach the "
                "listener, so the check proves nothing",
            )
        )
    else:
        results.append(
            CheckResult(
                name="Host loopback unreachable from containers",
                outcome="fail" if reached else "pass",
                detail=f"reached via {', '.join(reached)}"
                if reached
                else "guest reaches it; containers do not",
            )
        )

    # 6. Only allow-listed egress, from one network, leaves the engine; drops are logged.
    results.extend(_egress_checks(engine, docker))

    # 7. The optional microVM runtime (decision 0012), when installed.
    if engine.has_microvm():
        results.extend(microvm_checks(engine.shell))
    else:
        results.append(
            CheckResult(
                name="Firecracker microVM runtime",
                outcome="skip",
                detail="not installed (mirror engine setup --microvm, Apple M3+)",
            )
        )
    return results


MICROVM_IMAGE = (
    "docker.io/library/alpine:3.22"
    "@sha256:49340b346798875b5592e5d420241f2f9cfba5f47e62ebb1446a1b34734e898f"
)
KATA_TELLS = ("kata", "agent.", "firecracker", "virtio_mmio", "systemd.unit=kata")


def _is_frame(line: str) -> bool:
    """A backtrace frame (`12: <std::thread::...>`, `at /rustc/...`), not a numbered cause."""
    bare = line.strip()
    return bare.startswith("at ") or bool(re.match(r"^\d+: .*(::|<)", bare))


def _first_error(text: str) -> str:
    """The part of a failure worth reading: the first error line and the causes under it,
    not a backtrace's last frames."""
    lines = [ln.strip() for ln in text.replace("\\n", "\n").splitlines() if ln.strip()]
    lines = [ln for ln in lines if not _is_frame(ln)]
    for i, ln in enumerate(lines):
        if any(w in ln.lower() for w in ("error", "failed", "fatal")):
            causes = [c for c in lines[i + 1 :] if re.match(r"^\d+: ", c)]
            return " / ".join([ln, *causes[:4]])[:600]
    return (lines[0] if lines else "no output")[:400]


def microvm_checks(shell: Callable[..., subprocess.CompletedProcess[str]]) -> list[CheckResult]:
    """Run a workload in a Firecracker microVM through containerd, and look at what it sees."""
    out: list[CheckResult] = []
    pull = shell(
        "sudo",
        "ctr",
        "image",
        "pull",
        "--local",
        "--snapshotter",
        "devmapper",
        MICROVM_IMAGE,
        timeout=600,
    )
    if pull.returncode != 0:
        return [
            CheckResult(
                name="Firecracker microVM runtime",
                outcome="fail",
                detail=_first_error(pull.stderr or pull.stdout),
            )
        ]
    script = (
        "uname -r; echo ---; cat /proc/cmdline; echo ---; dmesg 2>&1 | head -5; echo ---; uname -m"
    )
    run = shell(
        "sudo",
        "ctr",
        "run",
        "--rm",
        "--runtime",
        "io.containerd.kata-fc.v2",
        "--snapshotter",
        "devmapper",
        MICROVM_IMAGE,
        f"fc-check-{os.getpid()}",
        "sh",
        "-c",
        script,
        timeout=600,
    )
    host_kernel = shell("uname", "-r").stdout.strip()
    if run.returncode != 0:
        return [
            CheckResult(
                name="Firecracker microVM runtime",
                outcome="fail",
                detail=_first_error(run.stderr or run.stdout),
            )
        ]
    parts = run.stdout.split("---")
    guest_kernel = parts[0].strip()
    own_kernel = guest_kernel != host_kernel
    out.append(
        CheckResult(
            name="A workload runs in a Firecracker microVM",
            outcome="pass" if own_kernel else "fail",
            detail=f"its own kernel {guest_kernel} (engine: {host_kernel})",
        )
    )
    cmdline = parts[1].strip() if len(parts) > 1 else "(not read)"
    out.append(
        CheckResult(
            name="The guest kernel command line is hidden",
            outcome="pass" if not cmdline else "fail",
            detail="/proc/cmdline is masked" if not cmdline else cmdline[:200],
        )
    )
    seen = run.stdout.lower()
    tells = [t for t in KATA_TELLS if t in seen]
    out.append(
        CheckResult(
            name="The microVM shows no Kata or Firecracker tells",
            outcome="fail" if tells else "pass",
            detail=f"found {', '.join(tells)} in uname, /proc/cmdline or dmesg" if tells else "",
        )
    )
    return out


def _egress_checks(engine: CheckedEngine, docker: Docker) -> list[CheckResult]:
    out: list[CheckResult] = []
    name = "uplink-check"
    docker.remove_network(name)
    net = docker.create_network(name)
    try:
        subnet = net["IPAM"]["Config"][0]["Subnet"]
        blocked_default = not _nc(docker, OUTSIDE_TARGET, 443)
        blocked_before = not _nc(docker, OUTSIDE_TARGET, 443, network=name)
        engine.shell(
            "sudo",
            "nft",
            "add",
            "element",
            "inet",
            "edge",
            "egress_allow",
            f"{{ {subnet} . {OUTSIDE_TARGET} . 443 }}",
        )
        allowed = _nc(docker, OUTSIDE_TARGET, 443, network=name)
        other_blocked = not _nc(docker, OTHER_TARGET, 443, network=name)
        engine.shell(
            "sudo",
            "nft",
            "delete",
            "element",
            "inet",
            "edge",
            "egress_allow",
            f"{{ {subnet} . {OUTSIDE_TARGET} . 443 }}",
        )
        logged = (
            "edge-drop egress"
            in engine.shell("sudo", "journalctl", "-k", "--since", "-5min", "--no-pager").stdout
        )
    finally:
        docker.remove_network(name)
    ok = blocked_default and blocked_before and allowed and other_blocked
    out.append(
        CheckResult(
            name="Only allow-listed egress leaves the engine",
            outcome="pass" if ok else "fail",
            detail=(
                f"default network blocked={blocked_default}; "
                f"before allow blocked={blocked_before}; "
                f"after allow reached={allowed}; other address blocked={other_blocked}"
            ),
        )
    )
    out.append(CheckResult(name="Dropped egress is logged", outcome="pass" if logged else "fail"))
    return out
