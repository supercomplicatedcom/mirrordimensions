# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""CI only: install the microVM runtime directly on a Linux runner with /dev/kvm and prove a
workload runs in a Firecracker microVM (decision 0012). The same provisioning script and the
same checks run inside the engine on Apple M3+ Macs.
"""

from __future__ import annotations

import subprocess
import sys

from mirrordimensions.engine.checks import microvm_checks
from mirrordimensions.engine.lima import microvm_script


def shell(*command: str, timeout: float = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command), capture_output=True, text=True, check=False, timeout=timeout
    )


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
    return 0 if all(r.outcome == "pass" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
