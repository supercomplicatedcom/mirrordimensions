# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The wsl driver's command lines against a stand-in wsl.exe, and the engine's Docker TLS.

Nothing here needs Windows: the driver is unverified on hardware (decision 0006), so these
pin down what it asks WSL to do.
"""

from __future__ import annotations

import socket
import ssl
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from mirrordimensions.engine import docker_tls, wsl
from mirrordimensions.engine.base import Resources
from mirrordimensions.engine.wsl import DISTRIBUTION, WslEngine, install_tls_script
from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.files import owner_only_problem

REAL_RUN = subprocess.run
RESOURCES = Resources(cpus=4, memory_gb=8, disk_gb=40)


class FakeWsl:
    """Answers wsl.exe the way WSL documents, and records every call."""

    def __init__(self, root: Path, registered: bool = False, ours: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.stdin: dict[str, str] = {}
        self.registered = registered
        self.running = False
        self.vhdx = root / "wsl" / DISTRIBUTION / "ext4.vhdx"
        if ours:
            self.vhdx.parent.mkdir(parents=True)
            self.vhdx.write_bytes(b"")

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if argv[0] != "wsl.exe":  # e.g. icacls, for owner-only files on Windows
            return REAL_RUN(argv, **kwargs)
        assert kwargs["env"]["WSL_UTF8"] == "1"
        args = argv[1:]
        self.calls.append(args)
        out = ""
        if args[:1] == ["--import"]:
            self.registered = True
            self.vhdx.parent.mkdir(parents=True, exist_ok=True)
            self.vhdx.write_bytes(b"")
        elif args[:2] == ["--list", "--quiet"]:
            names = [DISTRIBUTION] if self.registered else []
            if "--running" in args and not self.running:
                names = []
            out = "\n".join(["Ubuntu", *names]) + "\n"
        elif args[:1] == ["--terminate"]:
            self.running = False
        elif args[:1] == ["-d"]:
            self.running = True
            command = args[args.index("--exec") + 1 :]
            if kwargs.get("input"):
                self.stdin[" ".join(command)[:40]] = kwargs["input"]
            if command[:2] == ["systemctl", "is-active"]:
                out = "active\n"
            elif command[:1] == ["date"]:
                import time

                out = f"{time.time():.6f}\n"
            elif command[:2] == ["sh", "-c"]:
                out = "kernel=6.6.87.2-microsoft-standard-WSL2\ndocker=29.10.1\n"
        return subprocess.CompletedProcess(argv, 0, out, "")


@pytest.fixture
def fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeWsl:
    stand_in = FakeWsl(tmp_path)
    monkeypatch.setattr(wsl.subprocess, "run", stand_in)
    monkeypatch.setattr(wsl, "download", lambda _url, dest: dest.write_bytes(b"rootfs"))
    monkeypatch.setattr(wsl, "sha256_of", lambda _path: wsl.pins.WSL_ROOTFS[1])
    monkeypatch.setattr(WslEngine, "_keep_alive", lambda self: None)
    monkeypatch.setattr(WslEngine, "_keepalive_alive", lambda self: True)
    return stand_in


def test_setup_imports_hardens_provisions_and_secures_docker(tmp_path: Path, fake: FakeWsl) -> None:
    status = WslEngine(root=tmp_path).setup(RESOURCES, experimental=True)
    assert status.state == "running" and status.boundary == "shared-vm"
    plain = [" ".join(c) for c in fake.calls if c[:1] != ["-d"] and c[:1] != ["--list"]]
    assert plain[0] == "--version"
    assert plain[1].startswith(f"--import {DISTRIBUTION} ") and plain[1].endswith(" --version 2")
    assert plain[2] == f"--terminate {DISTRIBUTION}"  # wsl.conf applies at the next start
    inside = [c[c.index("--exec") + 1 :] for c in fake.calls if c[:1] == ["-d"]]
    assert all(
        c[: c.index("--exec")][:4] == ["-d", DISTRIBUTION, "-u", "root"]
        for c in fake.calls
        if c[:1] == ["-d"]
    )
    scripts = [c[2] for c in inside if c[:2] == ["bash", "-c"]]
    assert scripts[0] == "cat > /etc/wsl.conf"
    assert "provision.sh" in scripts[1] and "tls" in scripts[2]
    assert scripts[3] == "systemctl daemon-reload && systemctl restart docker"
    assert fake.stdin["bash -c cat > /etc/wsl.conf"] == wsl.WSL_CONF
    # The client's key stays on the host, owner-only; the server's went into the engine.
    assert docker_tls.client_files(tmp_path / "docker-tls") is not None
    sent = fake.stdin[" ".join(["bash", "-c", scripts[2]])[:40]]
    assert sent.count("-----BEGIN CERTIFICATE-----") == 2 and "PRIVATE KEY" in sent


def test_setup_never_touches_a_distribution_it_did_not_make(tmp_path: Path, fake: FakeWsl) -> None:
    fake.registered = True  # same name, but not imported into the mirror's folder
    with pytest.raises(MirrorError, match="did not create it"):
        WslEngine(root=tmp_path).setup(RESOURCES, experimental=True)
    assert not [c for c in fake.calls if c[:1] in (["--import"], ["--unregister"], ["-d"])]
    WslEngine(root=tmp_path).destroy()
    assert not [c for c in fake.calls if c[:1] == ["--unregister"]]


def test_destroy_unregisters_only_its_own(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stand_in = FakeWsl(tmp_path, registered=True, ours=True)
    monkeypatch.setattr(wsl.subprocess, "run", stand_in)
    WslEngine(root=tmp_path).destroy()
    assert ["--unregister", DISTRIBUTION] in stand_in.calls
    assert not (tmp_path / "wsl" / DISTRIBUTION).exists()


def test_microvm_is_refused_on_wsl(tmp_path: Path, fake: FakeWsl) -> None:
    with pytest.raises(MirrorError, match="lima engine"):
        WslEngine(root=tmp_path).setup(RESOURCES, experimental=True, microvm=True)


@pytest.mark.skipif(sys.platform == "win32", reason="a POSIX shell script, run in the engine")
def test_the_server_files_land_where_the_drop_in_expects_them(tmp_path: Path) -> None:
    server = docker_tls.create(tmp_path / "client")
    script = (
        install_tls_script()
        .replace("/etc/docker/tls", str(tmp_path / "tls"))
        .replace("/etc/systemd/system", str(tmp_path / "systemd"))
        .replace("/run/engine-tls.pem", str(tmp_path / "in.pem"))
    )
    subprocess.run(
        ["bash", "-c", script], input=server.ca + server.cert + server.key, text=True, check=True
    )
    assert (tmp_path / "tls" / "ca.pem").read_text() == server.ca
    assert (tmp_path / "tls" / "server.pem").read_text() == server.cert
    assert (tmp_path / "tls" / "server-key.pem").read_text() == server.key
    assert (tmp_path / "tls" / "server-key.pem").stat().st_mode & 0o077 == 0
    dropin = (tmp_path / "systemd" / "docker.service.d" / "tls.conf").read_text()
    assert "--tlsverify" in dropin and "-H tcp://127.0.0.1:" in dropin


def test_docker_tls_requires_the_client_certificate(tmp_path: Path) -> None:
    """A real handshake on loopback: with the client certificate it connects; without, the
    server refuses."""
    server = docker_tls.create(tmp_path / "client")
    for name, text in (("ca", server.ca), ("cert", server.cert), ("key", server.key)):
        (tmp_path / f"server-{name}.pem").write_text(text)
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(tmp_path / "server-cert.pem", tmp_path / "server-key.pem")
    context.load_verify_locations(tmp_path / "server-ca.pem")
    context.verify_mode = ssl.CERT_REQUIRED
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(2)
    port = listener.getsockname()[1]
    outcomes: list[str] = []

    def serve() -> None:
        for _ in range(2):
            conn, _ = listener.accept()
            try:
                with context.wrap_socket(conn, server_side=True) as tls:
                    tls.sendall(b"ok")
                    outcomes.append("accepted")
            except (ssl.SSLError, OSError):
                outcomes.append("refused")

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    files = docker_tls.client_files(tmp_path / "client")
    assert files is not None
    ca, cert, key = files
    good = ssl.create_default_context(cafile=ca)
    good.load_cert_chain(cert, key)
    with (
        socket.create_connection(("127.0.0.1", port)) as raw,
        good.wrap_socket(raw, server_hostname="127.0.0.1") as tls,
    ):
        assert tls.recv(2) == b"ok"
    bare = ssl.create_default_context(cafile=ca)
    with (
        pytest.raises((ssl.SSLError, OSError)),
        socket.create_connection(("127.0.0.1", port)) as raw,
        bare.wrap_socket(raw, server_hostname="127.0.0.1") as tls,
    ):
        tls.recv(2)
    thread.join(5)
    listener.close()
    assert outcomes == ["accepted", "refused"]
    assert owner_only_problem(tmp_path / "client" / "key.pem") is None


@pytest.mark.parametrize("required", [True, False])
def test_the_engine_check_sees_whether_a_client_certificate_is_required(
    tmp_path: Path, required: bool
) -> None:
    from mirrordimensions.engine.checks import tls_refuses_without_certificate

    server = docker_tls.create(tmp_path / "client")
    for name, text in (("ca", server.ca), ("cert", server.cert), ("key", server.key)):
        (tmp_path / f"server-{name}.pem").write_text(text)
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(tmp_path / "server-cert.pem", tmp_path / "server-key.pem")
    context.load_verify_locations(tmp_path / "server-ca.pem")
    context.verify_mode = ssl.CERT_REQUIRED if required else ssl.CERT_NONE
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)

    def serve() -> None:
        conn, _ = listener.accept()
        try:
            with context.wrap_socket(conn, server_side=True) as tls:
                tls.recv(64)
                tls.sendall(b"HTTP/1.1 200 OK\r\n\r\nOK")
        except (ssl.SSLError, OSError):
            pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    ca = str(tmp_path / "client" / docker_tls.CA_FILE)
    assert tls_refuses_without_certificate("127.0.0.1", listener.getsockname()[1], ca) is required
    thread.join(5)
    listener.close()
