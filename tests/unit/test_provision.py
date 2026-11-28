# SPDX-License-Identifier: Apache-2.0
"""The provisioning script must survive a brand-new guest, where Docker's files do not exist."""

from __future__ import annotations

import re
import subprocess
import sys
from importlib.resources import files

import pytest


@pytest.mark.skipif(sys.platform == "win32", reason="bash on Windows runners is the WSL launcher")
def test_config_checksum_lines_tolerate_missing_files() -> None:
    script = files("mirrordimensions.engine.provision").joinpath("provision.sh").read_text("utf-8")
    lines = [ln for ln in script.splitlines() if re.match(r'^(before|after)="\$\(', ln)]
    assert len(lines) == 2
    for line in lines:
        # Run the line exactly as written, under the script's own options, with files absent.
        absent = line.replace("/etc/docker/daemon.json", "/nonexistent/a")
        absent = absent.replace(
            "/etc/systemd/system/docker.socket.d/override.conf", "/nonexistent/b"
        )
        probe = "set -eu -o pipefail\n" + absent + "\necho ok\n"
        done = subprocess.run(["bash", "-c", probe], capture_output=True, text=True, check=False)
        assert done.returncode == 0, done.stderr
        assert done.stdout.strip().endswith("ok")


def test_every_sandbox_ipv6_network_is_inside_the_firewalls_own_range() -> None:
    import ipaddress
    from dataclasses import asdict

    from mirrordimensions.network.sandbox import Address

    script = files("mirrordimensions.engine.provision").joinpath("provision.sh").read_text("utf-8")
    allowed = re.search(r"ip6 daddr != \{[^}]*?(fd[0-9a-f:]+/\d+) \}", script)
    assert allowed, "the prerouting IPv6 rule names the sandbox's range"
    sandbox_range = ipaddress.ip_network(allowed.group(1))
    v6 = [v for k, v in asdict(Address()).items() if k.endswith("_v6")]
    assert v6
    for net in v6:
        inner = ipaddress.ip_network(net)
        assert isinstance(inner, ipaddress.IPv6Network)
        assert isinstance(sandbox_range, ipaddress.IPv6Network)
        assert inner.subnet_of(sandbox_range), net
