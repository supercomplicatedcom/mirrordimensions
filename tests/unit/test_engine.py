# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Engine configuration, driver choice and host helpers, without starting a VM."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from mirrordimensions.engine import pins
from mirrordimensions.engine.base import EngineStatus, Resources, UpdateOutcome
from mirrordimensions.engine.lima import (
    APPLIED_MARKER,
    LimaEngine,
    cache_entries,
    microvm_script,
    render_config,
)
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


def test_the_firewall_is_brought_up_to_date_before_routes_are_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lima re-runs the engine's original provisioning at every boot, so the record of
    what was applied must not outlive a boot, and mirror up checks it before opening."""
    assert APPLIED_MARKER.startswith("/run/")
    engine = LimaEngine(root=tmp_path)
    calls: list[str] = []

    def provision(on_step: object = None) -> None:
        calls.append("provision")

    monkeypatch.setattr(engine, "_reprovision_if_changed", provision)

    def shell(*command: str, timeout: float = 60) -> object:
        calls.append(" ".join(command[1:3]))
        return type("Done", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(engine, "shell", shell)
    engine.set_egress_allow([("10.42.0.10", "160.79.104.10", 443)])
    assert calls[0] == "provision" and calls[1:] == ["nft flush", "nft add"]


# -- updates: only when asked (decision 0019) -------------------------------------------


def test_the_engine_never_installs_updates_by_itself() -> None:
    text = render_config(RESOURCES, "aarch64", "vz")
    assert YAML(typ="safe").load(text)["upgradePackages"] is False
    script = text[text.index("provision:") :]
    assert "systemctl disable --now apt-daily.timer apt-daily-upgrade.timer" in script
    assert "unattended-upgrades.service" in script
    assert 'APT::Periodic::Unattended-Upgrade "0"' in script
    assert 'date -u +%Y-%m-%d > "$STATE/updated"' in script  # the first install counts


def test_update_age_and_the_note_it_gives() -> None:
    from datetime import date

    from mirrordimensions.engine.base import UPDATE_DAYS, update_age_days, update_note

    today = date(2026, 11, 24)
    assert update_age_days({"updated": "2026-11-10"}, today) == 14
    assert update_age_days({}, today) is None
    assert update_note({"updated": "2026-11-10", "reboot": "no"}, today) is None  # 14 days: fine
    late = update_note({"updated": "2026-11-09", "reboot": "no"}, today)
    assert late is not None and f"{UPDATE_DAYS + 1} days ago" in late
    assert "mirror engine update" in late
    due = update_note({"updated": "2026-11-24", "reboot": "yes"}, today)
    assert due is not None and "restarts" in due
    assert update_note({"updated": "not a date"}, today) is None


class _Engine:
    """Just enough of an engine to update, recording what was asked of it."""

    name = "lima"

    def __init__(self, running: int, reboot: bool) -> None:
        self.running = running
        self.reboot = reboot
        self.calls: list[str] = []

    def status(self) -> EngineStatus:
        return EngineStatus(driver="lima", state="running", versions={"kernel": "7.0.0-44"})

    def docker_endpoint(self) -> object:
        return object()

    def update(self) -> UpdateOutcome:
        self.calls.append("update")
        return UpdateOutcome(
            upgraded=["linux-image 7.0.0-45"], reboot_required=self.reboot, kernel="7.0.0-44"
        )

    def stop(self) -> None:
        self.calls.append("stop")

    def start(self, on_step: object = None) -> EngineStatus:
        self.calls.append("start")
        return EngineStatus(
            driver="lima", state="running", versions={"kernel": "7.0.0-45", "reboot": "no"}
        )


@pytest.fixture
def fake_engine(monkeypatch: pytest.MonkeyPatch) -> Callable[..., _Engine]:
    from mirrordimensions.service import engine as svc

    made: dict[str, _Engine] = {}

    def install(running: int = 0, reboot: bool = False) -> _Engine:
        engine = _Engine(running, reboot)
        made["engine"] = engine
        monkeypatch.setattr(svc, "get_engine", lambda: engine)

        class _Docker:
            def __init__(self, _endpoint: object) -> None:
                pass

            def info(self) -> dict[str, int]:
                return {"ContainersRunning": engine.running}

        monkeypatch.setattr("mirrordimensions.engine.docker_api.Docker", _Docker)
        return engine

    return install


def test_an_update_is_refused_while_anything_runs_in_the_engine(
    fake_engine: Callable[..., _Engine],
) -> None:
    from mirrordimensions.service import engine as svc

    engine = fake_engine(running=3)
    with pytest.raises(MirrorError, match="3 container"):
        svc.update_engine()
    assert engine.calls == []


def test_an_update_restarts_the_engine_only_when_asked_and_needed(
    fake_engine: Callable[..., _Engine],
) -> None:
    from mirrordimensions.service import engine as svc

    engine = fake_engine(reboot=True)
    outcome = svc.update_engine()
    assert engine.calls == ["update"] and outcome.reboot_required
    engine = fake_engine(reboot=True)
    outcome = svc.update_engine(restart=True)
    assert engine.calls == ["update", "stop", "start"]
    assert outcome.kernel == "7.0.0-45" and not outcome.reboot_required
    engine = fake_engine(reboot=False)
    svc.update_engine(restart=True)
    assert engine.calls == ["update"]  # nothing to restart for


def test_the_host_driver_leaves_updates_to_the_host() -> None:
    from mirrordimensions.engine.host import HostEngine

    with pytest.raises(MirrorError, match="no guest of its own"):
        HostEngine().update()


def test_the_engine_client_uses_nothing_from_the_users_docker_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Registry credentials, credential helpers and proxies in ~/.docker/config.json are the
    user's: they must not reach the engine's Docker, its builds, or any container."""
    import docker as docker_sdk

    from mirrordimensions.engine import docker_api

    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "auths": {"registry.example.test": {"auth": "dXNlcjpwYXNz"}},
                "credHelpers": {"gcr.io": "gcloud"},
                "proxies": {"default": {"httpProxy": "http://proxy.example.test:3128"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path))
    api = docker_sdk.APIClient(base_url="unix:///nonexistent.sock", version="1.45")
    assert api._auth_configs.auths and api._proxy_configs.http  # pyright: ignore[reportPrivateUsage]
    docker_api._forget_user_config(api)  # pyright: ignore[reportPrivateUsage]
    assert not api._auth_configs.auths and not api._proxy_configs.http  # pyright: ignore[reportPrivateUsage]
    headers: dict[str, str] = {}
    api._set_auth_headers(headers)  # pyright: ignore[reportPrivateUsage]
    assert headers == {}  # nothing is read back from the file for a build
    environment = api._proxy_configs.inject_proxy_environment(["A=1"])  # pyright: ignore[reportPrivateUsage]
    assert environment == ["A=1"]


# -- Lima's home: short enough for its sockets ----------------------------------------


def test_lima_home_is_short_enough_for_a_long_username(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The per-user data folder on macOS leaves room for usernames of only eight characters
    under the 104-byte socket path limit; the engine's own folder must not depend on it."""
    from mirrordimensions.engine import lima

    home = Path("/Users/alexandra.petrovskaya")
    monkeypatch.setattr(lima, "engine_vm_dir", lambda: home / ".mirrordimensions" / "lima")
    monkeypatch.setattr(
        lima, "data_dir", lambda: home / "Library" / "Application Support" / "mirrordimensions"
    )
    assert not lima.fits(lima.data_dir() / "lima-home")
    engine = lima.LimaEngine()
    assert engine.lima_home == home / ".mirrordimensions" / "lima"
    assert lima.fits(engine.lima_home)


def test_an_engine_set_up_at_the_earlier_path_stays_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mirrordimensions.engine import lima

    data = tmp_path / "d"
    (data / "lima-home" / lima.INSTANCE).mkdir(parents=True)
    monkeypatch.setattr(lima, "data_dir", lambda: data)
    monkeypatch.setattr(lima, "engine_vm_dir", lambda: tmp_path / "short")
    monkeypatch.setattr(lima, "fits", lambda _home: True)  # pytest's own folders are long
    assert lima.LimaEngine().lima_home == data / "lima-home"


def test_setup_refuses_a_home_too_long_for_the_sockets(tmp_path: Path) -> None:
    from mirrordimensions.engine import lima
    from mirrordimensions.engine.base import Resources
    from mirrordimensions.errors import MirrorError

    engine = lima.LimaEngine(root=tmp_path / ("x" * 90))
    with pytest.raises(MirrorError, match="too long a path"):
        engine.setup(Resources(cpus=2, memory_gb=4, disk_gb=30))
    assert not engine.lima_home.exists()
