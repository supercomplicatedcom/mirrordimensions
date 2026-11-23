# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""CI only: install the microVM runtime directly on a Linux runner with /dev/kvm and prove a
workload runs in a Firecracker microVM (decision 0012). The same provisioning script and the
same checks run inside the engine on Apple M3+ Macs.
"""

from __future__ import annotations

import subprocess
import sys

from mirrordimensions.engine.checks import _is_frame, microvm_checks  # pyright: ignore[reportPrivateUsage]
from mirrordimensions.engine.lima import microvm_script


def shell(*command: str, timeout: float = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command), capture_output=True, text=True, check=False, timeout=timeout
    )


def _without_backtraces(text: str) -> list[str]:
    lines = text.replace("\\\\n", "\n").replace("\\n", "\n").splitlines()
    keep: list[str] = []
    for line in lines:
        bare = line.strip()
        if not bare or _is_frame(bare):
            continue
        keep.append(line[:400])
    return keep


def main() -> int:
    done = subprocess.run(
        ["sudo", "bash", "-s"], input=microvm_script(), text=True, check=False, timeout=1800
    )
    if done.returncode != 0:
        print(f"FAIL  provisioning the microVM runtime exited with {done.returncode}")
        return 1
    results = microvm_checks(shell)
    for r in results:
        print(
            f"{'ok' if r.outcome == 'pass' else 'FAIL':<6}{r.name}"
            + (f"  ({r.detail})" if r.detail else "")
        )
    if all(r.outcome == "pass" for r in results):
        return 0
    # Diagnostics for the CI log: the runtime's own account of the failure, as an error
    # chain (Rust's "Caused by" lines) without the backtrace frames that bury it.
    for title, command in (
        (
            "containerd and Kata errors",
            ["sudo", "journalctl", "-u", "containerd", "--no-pager", "-n", "2000"],
        ),
        ("Kata shim", ["sudo", "journalctl", "-t", "kata", "--no-pager", "-n", "2000"]),
        ("devmapper pool", ["sudo", "dmsetup", "status"]),
        ("kvm and vhost", ["ls", "-l", "/dev/kvm", "/dev/vhost-vsock", "/dev/vhost-net"]),
    ):
        out = shell(*command, timeout=60)
        print(f"--- {title}")
        print("\n".join(_without_backtraces(out.stdout + out.stderr)[-80:]))
    return 1


if __name__ == "__main__":
    sys.exit(main())
