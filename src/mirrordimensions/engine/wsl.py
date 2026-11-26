# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The wsl engine driver: a dedicated WSL2 distribution on Windows 11 (decision 0002).

EXPERIMENTAL: written against WSL's documented commands and unit-tested, but not yet run on
a Windows machine (decision 0006, docs/platforms/windows-verification.md). Setup runs only
with `--experimental`.

- The distribution is imported from Ubuntu's pinned WSL root file system into the mirror's
  own data folder, under a name of its own. A distribution of that name the mirror did not
  import is never touched.
- Its `/etc/wsl.conf` shares nothing with Windows: no drives, no Windows programs, no
  Windows `PATH` (decision 0004). The user's global `.wslconfig` is never read or changed,
  so the engine's CPUs and memory are those WSL gives every distribution.
- Provisioning is the same script as the lima driver's.
- Docker listens on the distribution's loopback with mutual TLS, reached from Windows
  through WSL's localhost forwarding (decision 0003). Only the holder of the client key,
  kept owner-only in the host data folder, can use it.
- WSL stops a distribution with nothing running in it, so a detached `sleep` keeps the
  engine up from `start` until `stop`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from importlib.resources import files
from pathlib import Path

from mirrordimensions.engine import docker_tls, pins
from mirrordimensions.engine.base import (
    DockerEndpoint,
    EgressEntry,
    EngineStatus,
    Resources,
    UpdateOutcome,
    egress_allow_commands,
)
from mirrordimensions.engine.lima import (
    UPDATE_SCRIPT,
    VERSIONS_SCRIPT,
    StepFn,
    download,
    parse_versions,
    sha256_of,
)
from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.dirs import data_dir
from mirrordimensions.hostos.files import make_dir, write_text

DISTRIBUTION = "mirrordimensions-engine"
DOCKER_PORT = 23760
# Windows process flags for the keep-alive: no console, its own process group, detached.
DETACHED = 0x00000008 | 0x00000200 | 0x08000000

WSL_CONF = """\
# Written by mirror engine setup. Nothing from Windows is shared with the engine.
[automount]
enabled = false
mountFsTab = false

[interop]
enabled = false
appendWindowsPath = false

[boot]
systemd = true

[network]
generateHosts = false
"""


def provision_script() -> str:
    script = files("mirrordimensions.engine.provision").joinpath("provision.sh").read_text("utf-8")
    # No forwarded socket in WSL: Docker listens on loopback with mutual TLS (decision 0003).
    return script.replace("__ENGINE_USER__", "")


def docker_tls_dropin(port: int = DOCKER_PORT) -> str:
    """systemd drop-in: Docker on the engine's loopback only, mutual TLS required."""
    return (
        "[Service]\n"
        "ExecStart=\n"
        "ExecStart=/usr/bin/dockerd -H fd:// "
        f"-H tcp://127.0.0.1:{port} --tlsverify "
        "--tlscacert=/etc/docker/tls/ca.pem --tlscert=/etc/docker/tls/server.pem "
        "--tlskey=/etc/docker/tls/server-key.pem "
        "--containerd=/run/containerd/containerd.sock\n"
    )


def install_tls_script() -> str:
    """Root shell script: the server's files (read from stdin as three PEM blocks in order:
    CA, certificate, key) into /etc/docker/tls, and the drop-in that requires them."""
    return (
        "set -e; umask 077; mkdir -p /etc/docker/tls "
        "/etc/systemd/system/docker.service.d; "
        "cat > /run/engine-tls.pem; "
        "awk 'BEGIN{n=0} /-----BEGIN/{n++} "
        '{print > (n==1 ? "/etc/docker/tls/ca.pem" : n==2 ? "/etc/docker/tls/server.pem" '
        ': "/etc/docker/tls/server-key.pem")}\' /run/engine-tls.pem; '
        "rm -f /run/engine-tls.pem; chmod 0644 /etc/docker/tls/ca.pem /etc/docker/tls/server.pem; "
        "cat > /etc/systemd/system/docker.service.d/tls.conf <<'UNIT'\n"
        f"{docker_tls_dropin()}"
        "UNIT\n"
    )


def _env() -> dict[str, str]:
    # wsl.exe writes its own messages in UTF-16 unless asked for UTF-8.
    return {**os.environ, "WSL_UTF8": "1"}


class WslEngine:
    name = "wsl"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or data_dir()
        self.tls_dir = self.root / "docker-tls"
        self.distro_dir = self.root / "wsl" / DISTRIBUTION
        self.keepalive_file = self.root / "wsl-keepalive.pid"

    # -- wsl.exe ---------------------------------------------------------------

    def _wsl(
        self, *args: str, stdin: str | None = None, timeout: float | None = 300
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["wsl.exe", *args],
                input=stdin,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=_env(),
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise MirrorError(
                "WSL is not installed.",
                "The Windows engine runs in a WSL2 distribution.",
                "Run in PowerShell: wsl --install --no-distribution, restart, then setup again.",
            ) from exc

    def shell(
        self, *command: str, stdin: str | None = None, timeout: float = 120
    ) -> subprocess.CompletedProcess[str]:
        """Run a command in the engine as root, for the host admin and the engine's checks."""
        return self._wsl(
            "-d", DISTRIBUTION, "-u", "root", "--cd", "/", "--exec", *command,
            stdin=stdin, timeout=timeout,
        )  # fmt: skip

    def _root_script(self, script: str, what: str, stdin: str | None = None) -> str:
        done = self.shell("bash", "-c", script, stdin=stdin, timeout=1800)
        if done.returncode != 0:
            raise MirrorError(
                f"The engine could not {what}.",
                (done.stderr or done.stdout).strip()[-400:],
                "Run mirror engine setup --experimental again; if it repeats, "
                "mirror engine destroy, then setup.",
            )
        return done.stdout

    def _distributions(self, running: bool = False) -> list[str]:
        args = ["--list", "--quiet"] + (["--running"] if running else [])
        done = self._wsl(*args, timeout=60)
        if done.returncode != 0:
            return []
        return [line.strip().strip("\x00") for line in done.stdout.splitlines() if line.strip()]

    def _ours(self) -> bool:
        """Registered, and imported by the mirror into its own folder."""
        return DISTRIBUTION in self._distributions() and (self.distro_dir / "ext4.vhdx").is_file()

    # -- the Engine protocol ---------------------------------------------------

    def setup(
        self,
        resources: Resources,
        on_step: StepFn = None,
        experimental: bool = False,
        microvm: bool = False,
    ) -> EngineStatus:
        if not experimental:
            raise MirrorError(
                "The Windows engine is experimental.",
                "It is not yet verified on real hardware (docs/platforms/windows-verification.md).",
                "To try it anyway: mirror engine setup --experimental",
            )
        if microvm:
            raise MirrorError(
                "microVM agents need the lima engine.",
                "Firecracker needs nested virtualization, which WSL does not offer.",
                "Run mirror engine setup --experimental without --microvm.",
            )
        version = self._wsl("--version", timeout=60)
        if version.returncode != 0:
            raise MirrorError(
                "This Windows has no current WSL.",
                (version.stderr or version.stdout).strip()[-300:] or "wsl --version failed.",
                "Run in PowerShell: wsl --update (or wsl --install --no-distribution), then "
                "setup again.",
            )
        if DISTRIBUTION in self._distributions() and not self._ours():
            raise MirrorError(
                f"A WSL distribution named {DISTRIBUTION} already exists.",
                "The mirror did not create it, so it will not change it.",
                "Rename or remove that distribution yourself, then run setup again.",
            )
        _note(
            on_step,
            "WSL gives every distribution the same CPUs and memory; the engine uses those "
            f"(asked for {resources.cpus} CPUs, {resources.memory_gb} GB; .wslconfig is left "
            "as it is)",
        )
        make_dir(self.root, owner_only=True)
        if not self._ours():
            self._import(on_step)
        _note(on_step, "Sharing nothing with Windows (wsl.conf)")
        self._root_script("cat > /etc/wsl.conf", "write its wsl.conf", stdin=WSL_CONF)
        self._wsl("--terminate", DISTRIBUTION, timeout=120)  # wsl.conf applies at next start
        _note(on_step, "Installing Docker Engine and gVisor")
        self._root_script(
            "cat > /run/provision.sh && bash /run/provision.sh",
            "be provisioned",
            stdin=provision_script(),
        )
        _note(on_step, "Docker on the engine's loopback, client certificate required")
        server = docker_tls.create(self.tls_dir)
        self._root_script(
            install_tls_script(), "install Docker's TLS", stdin=server.ca + server.cert + server.key
        )
        self._root_script(
            "systemctl daemon-reload && systemctl restart docker", "restart Docker with TLS"
        )
        return self.start(on_step)

    def _import(self, on_step: StepFn) -> None:
        url, digest = pins.WSL_ROOTFS
        downloads = self.root / "downloads"
        make_dir(downloads, owner_only=True)
        archive = downloads / url.rsplit("/", 1)[-1]
        if not archive.is_file() or sha256_of(archive) != digest:
            _note(on_step, f"Downloading {pins.GUEST_OS} for WSL")
            download(url, archive)
        actual = sha256_of(archive)
        if actual != digest:
            archive.unlink(missing_ok=True)
            raise MirrorError(
                "The engine's root file system failed its checksum.",
                f"Expected {digest}, got {actual}.",
                "Run mirror engine setup --experimental again; if it repeats, report it "
                "(see SECURITY.md).",
            )
        _note(on_step, "Importing the engine distribution")
        make_dir(self.distro_dir, owner_only=True)
        done = self._wsl(
            "--import", DISTRIBUTION, str(self.distro_dir), str(archive), "--version", "2",
            timeout=1200,
        )  # fmt: skip
        if done.returncode != 0:
            raise MirrorError(
                "WSL could not import the engine distribution.",
                (done.stderr or done.stdout).strip()[-400:],
                "Check that virtualization is on and WSL is current (wsl --update), then setup "
                "again.",
            )

    def start(self, on_step: StepFn = None) -> EngineStatus:
        if not self._ours():
            raise MirrorError(
                "There is no engine yet.",
                f"No {DISTRIBUTION} distribution made by the mirror.",
                "Run: mirror engine setup --experimental",
            )
        if DISTRIBUTION not in self._distributions(running=True) or not self._keepalive_alive():
            self._keep_alive()
        for _ in range(60):
            done = self.shell("systemctl", "is-active", "docker", timeout=30)
            if done.stdout.strip() == "active":
                break
            time.sleep(1)
        else:
            raise MirrorError(
                "Docker did not start in the engine.",
                "systemctl is-active docker never reported active.",
                "Run mirror engine stop, then mirror engine start.",
            )
        return self.status()

    def _keepalive_alive(self) -> bool:
        if not self.keepalive_file.is_file():
            return False
        pid = self.keepalive_file.read_text("utf-8").strip()
        done = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        return pid in done.stdout

    def _keep_alive(self) -> None:
        process = subprocess.Popen(
            ["wsl.exe", "-d", DISTRIBUTION, "-u", "root", "--exec", "sleep", "infinity"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=_env(),
            creationflags=DETACHED,
        )
        write_text(self.keepalive_file, f"{process.pid}\n", owner_only=True)

    def stop(self) -> None:
        if self._ours():
            self._wsl("--terminate", DISTRIBUTION, timeout=120)
        self.keepalive_file.unlink(missing_ok=True)

    def destroy(self) -> None:
        if self._ours():
            self._wsl("--unregister", DISTRIBUTION, timeout=300)
        for path in (self.distro_dir, self.tls_dir, self.root / "downloads"):
            shutil.rmtree(path, ignore_errors=True)
        self.keepalive_file.unlink(missing_ok=True)

    def docker_endpoint(self) -> DockerEndpoint:
        return DockerEndpoint(url=f"tcp://127.0.0.1:{DOCKER_PORT}", tls_dir=str(self.tls_dir))

    def update(self) -> UpdateOutcome:
        """Install the guest's pending updates now. The caller makes sure the sandbox is down."""
        out = self._root_script(UPDATE_SCRIPT, "install its updates")
        lines = [line.strip() for line in out.splitlines() if line.strip()]
        return UpdateOutcome(
            upgraded=[line for line in lines if line != "REBOOT"],
            # WSL's kernel is Microsoft's and updates with WSL itself, not with the guest.
            reboot_required=False,
            kernel=self._versions().get("kernel", ""),
        )

    def set_egress_allow(self, entries: list[EgressEntry]) -> None:
        for command in egress_allow_commands(entries):
            done = self.shell(*command, timeout=60)
            if done.returncode != 0:
                raise MirrorError(
                    "The engine's firewall refused the model routes.",
                    (done.stderr or done.stdout).strip()[-300:],
                    "Run: mirror engine setup --experimental (it reinstalls the firewall).",
                )

    def clock_offset(self) -> float:
        """Guest clock minus host clock, in seconds, corrected for half the round trip."""
        before = time.time()
        done = self.shell("date", "+%s.%N", timeout=30)
        after = time.time()
        return float(done.stdout.strip()) - (before + after) / 2

    def status(self) -> EngineStatus:
        if not self._ours():
            return EngineStatus(driver=self.name, state="absent", boundary="shared-vm")
        running = DISTRIBUTION in self._distributions(running=True)
        status = EngineStatus(
            driver=self.name,
            state="running" if running else "stopped",
            arch="x64",
            boundary="shared-vm",
        )
        if running:
            status.versions = self._versions()
            status.clock_offset_s = round(self.clock_offset(), 3)
        status.versions["status"] = "experimental"
        return status

    def _versions(self) -> dict[str, str]:
        return parse_versions(self.shell("sh", "-c", VERSIONS_SCRIPT).stdout)


def _note(on_step: StepFn, text: str) -> None:
    if on_step is not None:
        on_step(text)
