# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The lima engine driver: macOS (Virtualization.framework) and Linux (QEMU with KVM).

Lima runs from the mirror's own folders: a pinned, checksum-verified `limactl` and a
private `LIMA_HOME`, so the user's own Lima instances are never listed or changed.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import time
import urllib.request
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path
from typing import Any

from mirrordimensions.engine import pins
from mirrordimensions.engine.base import DockerEndpoint, EngineStatus, Resources
from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.dirs import data_dir
from mirrordimensions.hostos.files import make_dir, set_owner_only, write_text
from mirrordimensions.hostos.info import host_arch, host_os

INSTANCE = "engine"
StepFn = Callable[[str], None] | None


def _note(on_step: StepFn, text: str) -> None:
    if on_step is not None:
        on_step(text)


def render_config(resources: Resources, guest_arch: pins.GuestArch, vm_type: str) -> str:
    """The Lima configuration for the engine VM."""
    template = files("mirrordimensions.engine.provision").joinpath("lima.yaml").read_text("utf-8")
    script = files("mirrordimensions.engine.provision").joinpath("provision.sh").read_text("utf-8")
    # Lima expands Go templates in provisioning scripts; {{.User}} is the guest user.
    script = script.replace("__ENGINE_USER__", "{{.User}}")
    location, digest = pins.GUEST_IMAGES[guest_arch]
    images = f'  - location: "{location}"\n    arch: "{guest_arch}"\n    digest: "{digest}"'
    provision = "\n".join(f"      {line}" if line else "" for line in script.splitlines())
    values = {
        "@@VM_TYPE@@": vm_type,
        "@@CPUS@@": str(resources.cpus),
        "@@MEMORY_GIB@@": str(resources.memory_gb),
        "@@DISK_GIB@@": str(resources.disk_gb),
        "@@IMAGES@@": images,
        "@@ROSETTA@@": "true" if vm_type == "vz" else "false",
        "@@PROVISION@@": provision,
    }
    for key, value in values.items():
        template = template.replace(key, value)
    return template


def default_resources() -> Resources:
    cpus = max(2, min(4, (os.cpu_count() or 4) // 2))
    return Resources(cpus=cpus, memory_gb=6, disk_gb=40)


class LimaEngine:
    name = "lima"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or data_dir()
        self.lima_home = self.root / "lima-home"
        self.lima_dir = self.root / "lima" / pins.LIMA_VERSION
        self.config_path = self.root / "engine.lima.yaml"

    # -- paths -----------------------------------------------------------------

    @property
    def limactl(self) -> Path:
        return self.lima_dir / "bin" / "limactl"

    @property
    def instance_dir(self) -> Path:
        return self.lima_home / INSTANCE

    @property
    def socket_path(self) -> Path:
        return self.instance_dir / "sock" / "docker.sock"

    # -- Lima itself -----------------------------------------------------------

    def ensure_lima(self, on_step: StepFn = None) -> None:
        if self.limactl.is_file():
            return
        key = (host_os(), host_arch())
        if key not in pins.LIMA_ARCHIVES:
            raise MirrorError(
                "The lima engine does not support this host.",
                f"No pinned Lima build for {key[0]} on {key[1]}.",
                "Use a supported host; see docs/platforms.md.",
            )
        name, sha256 = pins.LIMA_ARCHIVES[key]
        downloads = self.root / "downloads"
        make_dir(downloads, owner_only=True)
        archive = downloads / name
        if not archive.is_file() or _sha256(archive) != sha256:
            _note(on_step, f"Downloading Lima {pins.LIMA_VERSION}")
            _download(pins.lima_url(name), archive)
        actual = _sha256(archive)
        if actual != sha256:
            archive.unlink(missing_ok=True)
            raise MirrorError(
                "The Lima download failed its checksum.",
                f"Expected {sha256}, got {actual}.",
                "Run mirror engine setup again; if it repeats, report it (see SECURITY.md).",
            )
        make_dir(self.lima_dir, owner_only=True)
        with tarfile.open(archive) as tar:
            tar.extractall(self.lima_dir, filter="data")
        self.limactl.chmod(0o700)

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["LIMA_HOME"] = str(self.lima_home)
        return env

    def _limactl(
        self, *args: str, timeout: float | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.limactl), *args],
            env=self._env(),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )

    def _instance(self) -> dict[str, Any] | None:
        if not self.limactl.is_file():
            return None
        done = self._limactl("list", "--json")
        for line in done.stdout.splitlines():
            if not line.strip():
                continue
            data: dict[str, Any] = json.loads(line)
            if data.get("name") == INSTANCE:
                return data
        return None

    # -- the Engine protocol ---------------------------------------------------

    def setup(self, resources: Resources, on_step: StepFn = None) -> EngineStatus:
        make_dir(self.root, owner_only=True)
        make_dir(self.lima_home, owner_only=True)
        self.ensure_lima(on_step)
        vm_type = "vz" if host_os() == "macos" else "qemu"
        guest_arch: pins.GuestArch = "aarch64" if host_arch() == "arm64" else "x86_64"
        write_text(self.config_path, render_config(resources, guest_arch, vm_type), owner_only=True)
        done = self._limactl("validate", str(self.config_path))
        if done.returncode != 0:
            raise MirrorError(
                "The engine configuration is not valid.",
                done.stderr.strip(),
                "Report this as a bug.",
            )
        if self._instance() is None:
            _note(on_step, "Creating the engine VM (first run downloads Ubuntu and packages)")
            done = self._limactl(
                "start", f"--name={INSTANCE}", "--tty=false", str(self.config_path), timeout=1800
            )
            if done.returncode != 0:
                raise _start_error(done)
        return self.start(on_step)

    def start(self, on_step: StepFn = None) -> EngineStatus:
        inst = self._instance()
        if inst is None:
            raise MirrorError(
                "No engine on this machine.",
                "The engine VM has not been created.",
                "Run: mirror engine setup",
            )
        if inst.get("status") != "Running":
            _note(on_step, "Starting the engine")
            done = self._limactl("start", INSTANCE, "--tty=false", timeout=900)
            if done.returncode != 0:
                raise _start_error(done)
        self._restrict_socket()
        self._reprovision_if_changed(on_step)
        return self.status()

    def provision_script(self) -> str:
        script = (
            files("mirrordimensions.engine.provision").joinpath("provision.sh").read_text("utf-8")
        )
        user = self.shell("id", "-un").stdout.strip()
        return script.replace("__ENGINE_USER__", user)

    def _reprovision_if_changed(self, on_step: StepFn = None) -> None:
        """Re-apply provisioning when this version's script differs from the engine's."""
        script = self.provision_script()
        wanted = hashlib.sha256(script.encode()).hexdigest()
        have = self.shell("sudo", "cat", "/var/lib/engine/applied.sha").stdout.strip()
        if have == wanted:
            return
        _note(on_step, "Updating the engine's configuration")
        done = subprocess.run(
            [str(self.limactl), "shell", "--workdir", "/", INSTANCE, "--", "sudo", "bash", "-s"],
            input=script,
            env=self._env(),
            capture_output=True,
            text=True,
            check=False,
            timeout=1200,
        )
        if done.returncode != 0:
            raise MirrorError(
                "Updating the engine failed.",
                "\n".join(done.stderr.strip().splitlines()[-5:]),
                "Run mirror engine setup again. If it repeats: mirror engine destroy, then setup.",
            )
        self.shell("sudo", "sh", "-c", f"echo {wanted} > /var/lib/engine/applied.sha")

    def stop(self) -> None:
        if self._instance() is not None:
            self._limactl("stop", INSTANCE, timeout=300)

    def destroy(self) -> None:
        if self._instance() is not None:
            self._limactl("delete", "--force", INSTANCE, timeout=300)
        for path in (self.lima_home, self.root / "lima", self.root / "downloads"):
            shutil.rmtree(path, ignore_errors=True)
        self.config_path.unlink(missing_ok=True)
        # Lima's download cache is shared with any Lima the user has; remove only the
        # entries for images the engine pinned.
        for entry in cache_entries():
            shutil.rmtree(entry, ignore_errors=True)

    def docker_endpoint(self) -> DockerEndpoint:
        return DockerEndpoint(url=f"unix://{self.socket_path}")

    def shell(self, *command: str, timeout: float = 120) -> subprocess.CompletedProcess[str]:
        """Run a command in the guest, for the host admin and the engine's own checks."""
        return self._limactl("shell", "--workdir", "/", INSTANCE, "--", *command, timeout=timeout)

    def clock_offset(self) -> float:
        """Guest clock minus host clock, in seconds, corrected for half the round trip."""
        before = time.time()
        done = self.shell("date", "+%s.%N", timeout=30)
        after = time.time()
        guest = float(done.stdout.strip())
        return guest - (before + after) / 2

    def status(self) -> EngineStatus:
        inst = self._instance()
        if inst is None:
            return EngineStatus(driver=self.name, state="absent")
        state = "running" if inst.get("status") == "Running" else "stopped"
        resources = Resources(
            cpus=int(inst.get("cpus", 0)),
            memory_gb=int(inst.get("memory", 0)) // 2**30,
            disk_gb=int(inst.get("disk", 0)) // 2**30,
        )
        arch = "arm64" if inst.get("arch") == "aarch64" else "x64"
        status = EngineStatus(
            driver=self.name, state=state, arch=arch, boundary="dedicated-vm", resources=resources
        )
        if state == "running":
            status.versions = self._versions()
            status.clock_offset_s = round(self.clock_offset(), 3)
        status.versions["lima"] = pins.LIMA_VERSION
        return status

    # -- helpers ---------------------------------------------------------------

    def _versions(self) -> dict[str, str]:
        script = (
            "printf 'kernel=%s\\n' \"$(uname -r)\"; "
            "printf 'docker=%s\\n' "
            "\"$(docker version --format '{{.Server.Version}}' 2>/dev/null)\"; "
            "printf 'runsc=%s\\n' \"$(runsc --version 2>/dev/null | head -1 | awk '{print $3}')\"; "
            ". /etc/os-release; printf 'guest=%s\\n' \"$PRETTY_NAME\""
        )
        done = self.shell("sh", "-c", script)
        out: dict[str, str] = {}
        for line in done.stdout.splitlines():
            key, _, value = line.partition("=")
            if key and value:
                out[key] = value
        return out

    def _restrict_socket(self) -> None:
        sock_dir = self.socket_path.parent
        if sock_dir.is_dir():
            set_owner_only(sock_dir)
        if self.socket_path.exists():
            self.socket_path.chmod(0o600)


def lima_cache_dir() -> Path:
    """Where Lima caches downloads: Go's os.UserCacheDir() joined with "lima"."""
    if host_os() == "macos":
        return Path.home() / "Library" / "Caches" / "lima"
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "lima"


def cache_entries() -> list[Path]:
    """The cache entries for the pinned guest images (Lima keys them by SHA-256 of the URL)."""
    root = lima_cache_dir() / "download" / "by-url-sha256"
    return [
        root / hashlib.sha256(url.encode()).hexdigest() for url, _ in pins.GUEST_IMAGES.values()
    ]


def _start_error(done: subprocess.CompletedProcess[str]) -> MirrorError:
    tail = "\n".join((done.stderr or done.stdout).strip().splitlines()[-5:])
    return MirrorError(
        "The engine VM did not start.",
        tail or f"limactl exited with code {done.returncode}.",
        "See the guest log: mirror engine shell, then sudo tail /var/log/cloud-init-output.log",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "mirrordimensions-engine-setup"})  # noqa: S310
    with urllib.request.urlopen(request, timeout=120) as response, tmp.open("wb") as out:  # noqa: S310
        shutil.copyfileobj(response, out)
    tmp.replace(dest)
