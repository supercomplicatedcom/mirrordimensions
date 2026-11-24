# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Engine configuration, driver choice and host helpers, without starting a VM."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from mirrordimensions.engine import pins
from mirrordimensions.engine.base import Resources
from mirrordimensions.engine.lima import cache_entries, microvm_script, render_config
from mirrordimensions.engine.registry import ALLOWED, default_driver
from mirrordimensions.engine.wsl import WSL_CONF, WslEngine, docker_tls_dropin, provision_script
from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.awake import SleepDetector
from mirrordimensions.hostos.info import host_os

RESOURCES = Resources(cpus=4, memory_gb=6, disk_gb=40)


@pytest.fixture(params=[("aarch64", "vz"), ("x86_64", "qemu")])
def config(request: pytest.FixtureRequest) -> dict[str, object]:
    arch, vm_type = request.param
    return YAML(typ="safe").load(render_config(RESOURCES, arch, vm_type))


def test_nothing_from_the_host_is_shared(config: dict[str, object]) -> None:
    assert config["mounts"] == []
    assert config["hostResolver"] == {"hosts": {}}
    assert config["propagateProxyEnv"] is False


def test_only_the_docker_socket_is_forwarded(config: dict[str, object]) -> None:
    rules = config["portForwards"]
    assert isinstance(rules, list)
    sockets = [r for r in rules if "guestSocket" in r]
    assert sockets == [
        {"guestSocket": "/var/run/docker.sock", "hostSocket": "{{.Dir}}/sock/docker.sock"}
    ]
    ignored = {r["guestIP"] for r in rules if r.get("ignore")}
    assert ignored == {"0.0.0.0", "::", "127.0.0.1"}  # noqa: S104
    assert all(r["guestPortRange"] == [1, 65535] for r in rules if r.get("ignore"))


def test_image_is_pinned_by_digest(config: dict[str, object]) -> None:
    images = config["images"]
    assert isinstance(images, list)
    assert len(images) == 1
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", images[0]["digest"])


def test_rosetta_only_with_vz() -> None:
    vz = YAML(typ="safe").load(render_config(RESOURCES, "aarch64", "vz"))
    qemu = YAML(typ="safe").load(render_config(RESOURCES, "x86_64", "qemu"))
    assert vz["vmOpts"]["vz"]["rosetta"] == {"enabled": True, "binfmt": True}
    assert qemu["vmOpts"]["vz"]["rosetta"] == {"enabled": False, "binfmt": False}


def test_provision_script_firewall_and_no_raw_go_template_braces() -> None:
    text = render_config(RESOURCES, "aarch64", "vz")
    script = text[text.index("provision:") :]
    assert "table inet edge" in script
    assert 'log prefix "edge-drop egress "' in script
    # Lima treats provisioning scripts as Go templates; only {{.User}} may appear.
    assert re.findall(r"\{\{[^}]*\}\}", script) == ["{{.User}}"]


def test_lima_archives_are_pinned() -> None:
    for name, sha in pins.LIMA_ARCHIVES.values():
        assert pins.LIMA_VERSION in name
        assert re.fullmatch(r"[0-9a-f]{64}", sha)


def test_wsl_shares_nothing() -> None:
    assert "[automount]\nenabled = false" in WSL_CONF
    assert "[interop]\nenabled = false\nappendWindowsPath = false" in WSL_CONF
    assert "-H tcp://127.0.0.1:" in docker_tls_dropin()
    assert "--tlsverify" in docker_tls_dropin()
    assert "__ENGINE_USER__" not in provision_script()


def test_wsl_setup_is_refused_until_verified() -> None:
    with pytest.raises(MirrorError, match="experimental"):
        WslEngine().setup(RESOURCES)


def test_default_driver_for_this_host() -> None:
    assert default_driver() == ALLOWED[host_os()][0]


def test_sleep_detector() -> None:
    clock = {"wall": 1000.0, "mono": 50.0}
    detector = SleepDetector(
        threshold_s=2.0, wall=lambda: clock["wall"], mono=lambda: clock["mono"]
    )
    clock["wall"] += 60
    clock["mono"] += 60
    assert detector.slept_for() == 0.0
    clock["wall"] += 600  # the host slept for ten minutes: wall moves, monotonic does not
    assert detector.slept_for() == pytest.approx(600)


def test_destroy_removes_only_pinned_cache_entries() -> None:
    entries = cache_entries()
    assert len(entries) == len(pins.GUEST_IMAGES)
    # Known value: SHA-256 of the pinned arm64 image URL, as Lima names its cache folder.
    assert any(e.name.startswith("274d59968f7fc401") for e in entries)
    assert all(e.parent.name == "by-url-sha256" for e in entries)


def test_microvm_turns_on_nested_virtualization_and_adds_the_runtime() -> None:
    plain = YAML(typ="safe").load(render_config(RESOURCES, "aarch64", "vz"))
    nested_text = render_config(RESOURCES, "aarch64", "vz", nested=True)
    nested = YAML(typ="safe").load(nested_text)
    assert plain["nestedVirtualization"] is False
    assert nested["nestedVirtualization"] is True
    assert "containerd-shim-kata-fc-v2" in nested_text
    assert "__KATA_SHA256" not in nested_text
    assert "__FC_SHA256" not in nested_text
    script = nested_text[nested_text.index("provision:") :]
    assert re.findall(r"\{\{[^}]*\}\}", script) == ["{{.User}}"]


def _heredoc(script: str, name: str) -> str:
    match = re.search(rf"<<'{name}'\n(.*?)\n{name}\n", script, re.S)
    assert match, name
    return match[1]


def test_microvm_containers_get_proc_cmdline_masked(tmp_path: Path) -> None:
    """Tell 18: the guest kernel's command line names Kata, so the runtime masks it."""
    script = microvm_script()
    mask = tmp_path / "mask-cmdline.py"
    mask.write_text(_heredoc(script, "MASK"), encoding="utf-8")
    spec = tmp_path / "config.json"
    spec.write_text(
        json.dumps({"process": {"args": ["sh"]}, "linux": {"maskedPaths": ["/proc/kcore"]}}),
        encoding="utf-8",
    )
    for _ in range(2):  # a second start leaves it as it is
        subprocess.run([sys.executable, "-I", str(mask), str(spec)], check=True)
    loaded = json.loads(spec.read_text(encoding="utf-8"))
    assert loaded["linux"]["maskedPaths"] == ["/proc/kcore", "/proc/cmdline"]
    assert loaded["process"] == {"args": ["sh"]}
    bare = tmp_path / "bare.json"
    bare.write_text("{}", encoding="utf-8")
    subprocess.run([sys.executable, "-I", str(mask), str(bare)], check=True)
    assert json.loads(bare.read_text(encoding="utf-8")) == {
        "linux": {"maskedPaths": ["/proc/cmdline"]}
    }
    shim = _heredoc(script, "SHIM")
    assert shim.index("mask-cmdline.py") < shim.index("exec /opt/kata")
    assert "refusing to start" in shim


def test_kata_archives_are_pinned() -> None:
    assert set(pins.KATA_SHA256) == {"arm64", "amd64"}
    for sha in pins.KATA_SHA256.values():
        assert re.fullmatch(r"[0-9a-f]{64}", sha)
