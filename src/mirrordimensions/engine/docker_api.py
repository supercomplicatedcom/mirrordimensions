# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The one wrapper around the Docker API. Nothing else talks to Docker directly.

It connects only to the engine's endpoint, never to the user's own Docker context.
"""

# The docker SDK is not fully typed.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportMissingTypeStubs=false

from __future__ import annotations

import contextlib
import io
import tarfile
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import docker
from docker import types as docker_types
from docker.errors import BuildError, DockerException, ImageNotFound, NotFound

from mirrordimensions.engine.base import DockerEndpoint
from mirrordimensions.errors import MirrorError


@dataclass
class ContainerSpec:
    """One container. Files are copied in before start (never mounted, decision 0003)."""

    name: str
    image: str
    networks: dict[str, str]  # network name -> IPv4 address; the first is attached at create
    command: list[str] | None = None
    files: dict[str, tuple[bytes, int]] = field(default_factory=dict[str, tuple[bytes, int]])
    dns: list[str] | None = None
    cap_add: list[str] = field(default_factory=list[str])
    sysctls: dict[str, str] = field(default_factory=dict[str, str])
    devices: list[str] = field(default_factory=list[str])
    labels: dict[str, str] = field(default_factory=dict[str, str])
    hostname: str | None = None
    network_mode: str | None = None
    user: str | None = None
    masked_paths: list[str] | None = None
    env: dict[str, str] = field(default_factory=dict[str, str])
    platform: str | None = None  # e.g. linux/amd64 for an image emulated under Rosetta
    working_dir: str | None = None
    volumes: dict[str, str] = field(default_factory=dict[str, str])  # named volume -> path
    # Network whose gateway becomes the container's default route (Docker's GwPriority).
    default_route: str | None = None
    entrypoint: list[str] | None = None
    # The engine's own in-kernel tracer only: it watches every container from outside them.
    # Nothing an agent can reach is ever given these.
    privileged: bool = False
    pid_mode: str | None = None  # "host"
    cgroupns: str | None = None  # "host"
    engine_binds: dict[str, str] = field(default_factory=dict[str, str])  # engine path -> path
    log_options: dict[str, str] = field(default_factory=dict[str, str])  # json-file rotation


@dataclass
class RunOutput:
    exit_code: int
    output: str


class Docker:
    def __init__(self, endpoint: DockerEndpoint) -> None:
        try:
            self._client: Any = docker.DockerClient(base_url=endpoint.url, timeout=120)
            self._client.ping()
        except DockerException as exc:
            raise MirrorError(
                "Cannot reach the engine's Docker API.",
                str(exc),
                "Run: mirror engine start",
            ) from exc

    def info(self) -> dict[str, Any]:
        return dict(self._client.info())

    def runtimes(self) -> list[str]:
        return sorted(self.info().get("Runtimes", {}))

    def run(
        self,
        image: str,
        command: list[str],
        *,
        runtime: str | None = None,
        platform: str | None = None,
        network: str | None = None,
    ) -> RunOutput:
        """Run a short-lived container and return its exit code and combined output."""
        container: Any = self._client.containers.run(
            image,
            command,
            runtime=runtime,
            platform=platform,
            network=network,
            detach=True,
        )
        try:
            result = container.wait(timeout=300)
            output = container.logs(stdout=True, stderr=True).decode("utf-8", "replace")
            return RunOutput(exit_code=int(result.get("StatusCode", -1)), output=output)
        finally:
            container.remove(force=True)

    def pull(self, image: str, platform: str | None = None) -> None:
        self._client.images.pull(image, platform=platform)

    def create_network(self, name: str, *, internal: bool = False) -> dict[str, Any]:
        net: Any = self._client.networks.create(name, driver="bridge", internal=internal)
        net.reload()
        return dict(net.attrs)

    def remove_network(self, name: str) -> None:
        for net in self._client.networks.list(names=[name]):
            if net.name == name:
                net.reload()
                for cid in list(net.attrs.get("Containers") or {}):
                    net.disconnect(cid, force=True)
                net.remove()

    def ensure_network(
        self,
        name: str,
        subnet: str,
        gateway: str,
        *,
        ipv6_subnet: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> None:
        if any(n.name == name for n in self._client.networks.list(names=[name])):
            return
        pools = [docker_types.IPAMPool(subnet=subnet, gateway=gateway)]
        if ipv6_subnet:
            pools.append(docker_types.IPAMPool(subnet=ipv6_subnet))
        self._client.networks.create(
            name,
            driver="bridge",
            ipam=docker_types.IPAMConfig(pool_configs=pools),
            enable_ipv6=bool(ipv6_subnet),
            labels=labels or {},
            # Never set com.docker.network.bridge.name: the engine firewall matches
            # Docker's own bridge names (br-*), and a custom name would bypass it.
        )

    def network_id(self, name: str) -> str:
        net: Any = self._client.networks.get(name)
        return str(net.id)

    def network_subnet(self, name: str) -> str:
        net: Any = self._client.networks.get(name)
        return str(net.attrs["IPAM"]["Config"][0]["Subnet"])

    def create(self, spec: ContainerSpec) -> None:
        """Create (not start) a container, attach its networks and copy its files in."""
        self.remove(spec.name)
        first, *rest = list(spec.networks.items()) or [(None, None)]
        networking: Any = None
        if first[0] is not None:
            endpoint = self._client.api.create_endpoint_config(ipv4_address=first[1])
            networking = self._client.api.create_networking_config({first[0]: endpoint})
        shares_network = (spec.network_mode or "").startswith("container:")
        host_config = self._client.api.create_host_config(
            cap_drop=None if spec.privileged else ["ALL"],
            cap_add=spec.cap_add or None,
            security_opt=["no-new-privileges"],
            dns=spec.dns,
            sysctls=spec.sysctls or None,
            devices=spec.devices or None,
            network_mode=spec.network_mode or (first[0] if first[0] else None),
            restart_policy={"Name": "no"},
            binds={
                **{vol: {"bind": path, "mode": "rw"} for vol, path in spec.volumes.items()},
                **{src: {"bind": path, "mode": "ro"} for src, path in spec.engine_binds.items()},
            }
            or None,
            privileged=spec.privileged,
            pid_mode=spec.pid_mode,
            log_config=docker_types.LogConfig(type="json-file", config=spec.log_options)
            if spec.log_options
            else None,
        )
        if spec.cgroupns:
            host_config["CgroupnsMode"] = spec.cgroupns
        if spec.masked_paths is not None:
            # Replaces Docker's default list, so callers pass the defaults too.
            host_config["MaskedPaths"] = spec.masked_paths
        self._client.api.create_container(
            spec.image,
            command=spec.command,
            name=spec.name,
            # A container sharing another's network namespace takes that one's host name.
            hostname=None if shares_network else spec.hostname or spec.name,
            entrypoint=spec.entrypoint,
            labels=spec.labels,
            host_config=host_config,
            networking_config=networking,
            user=spec.user,
            environment=spec.env or None,
            platform=spec.platform,
            working_dir=spec.working_dir,
        )
        for net, ip in rest:
            if net == spec.default_route:
                # docker-py has no gateway-priority argument; the Engine API takes it directly.
                endpoint_config = {"IPAMConfig": {"IPv4Address": ip}, "GwPriority": 100}
                response = self._client.api._post_json(  # pyright: ignore[reportPrivateUsage]
                    self._client.api._url("/networks/{0}/connect", net),  # pyright: ignore[reportPrivateUsage]
                    data={"Container": spec.name, "EndpointConfig": endpoint_config},
                )
                self._client.api._raise_for_status(response)  # pyright: ignore[reportPrivateUsage]
            else:
                self._client.api.connect_container_to_network(spec.name, net, ipv4_address=ip)
        if spec.files:
            self.put_files(spec.name, spec.files)

    def put_files(self, name: str, files: dict[str, tuple[bytes, int]]) -> None:
        """Copy files into a container through the archive API. Paths are absolute."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for path, (data, mode) in sorted(files.items()):
                info = tarfile.TarInfo(path.lstrip("/"))
                info.size = len(data)
                info.mode = mode
                info.mtime = int(time.time())
                tar.addfile(info, io.BytesIO(data))
        self._client.api.put_archive(name, "/", buf.getvalue())

    def read_file(self, name: str, path: str) -> bytes | None:
        """A file's bytes from a container, created or running; None when it does not exist."""
        try:
            stream, _ = self._client.api.get_archive(name, path)
        except NotFound:
            return None
        raw = b"".join(stream)
        with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
            member = next((m for m in tar.getmembers() if m.isfile()), None)
            if member is None:
                return None
            extracted = tar.extractfile(member)
            return extracted.read() if extracted else None

    def build(self, context: dict[str, bytes], tag: str, platform: str | None = None) -> str:
        """Build an image from files sent over the API (no shared folder); return its id."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for path, data in sorted(context.items()):
                info = tarfile.TarInfo(path)
                info.size = len(data)
                info.mode = 0o644
                info.mtime = 0  # the same context always builds the same layers
                tar.addfile(info, io.BytesIO(data))
        buf.seek(0)
        try:
            image, _ = self._client.images.build(
                fileobj=buf,
                custom_context=True,
                tag=tag,
                rm=True,
                platform=platform,
                pull=False,
                # Package installs happen at build time in the engine's own network namespace
                # (CLAUDE.md, Safety); container networks are sealed by the edge firewall.
                network_mode="host",
            )
        except BuildError as exc:
            lines = [
                str(chunk.get("stream", chunk.get("error", ""))).strip() for chunk in exc.build_log
            ]
            raise MirrorError(
                f"Building the image {tag} failed.",
                " / ".join(x for x in lines if x)[-400:],
                "Fix its Dockerfile, then try again.",
            ) from exc
        return str(image.id)

    def image_arch(self, image: str) -> str | None:
        """The architecture of a local image (amd64, arm64), or None if it is not present."""
        try:
            return str(self._client.images.get(image).attrs.get("Architecture"))
        except ImageNotFound:
            return None

    def start(self, name: str) -> None:
        self._client.api.start(name)

    def stop(self, name: str, timeout_s: int = 20) -> None:
        with contextlib.suppress(DockerException):
            self._client.api.stop(name, timeout=timeout_s)

    def wait(self, name: str, timeout_s: int = 600) -> RunOutput:
        """Wait for a container to exit; return its exit code and output."""
        result: Any = self._client.api.wait(name, timeout=timeout_s)
        logs = self._client.api.logs(name, stdout=True, stderr=True)
        return RunOutput(
            exit_code=int(result.get("StatusCode", -1)),
            output=bytes(logs).decode("utf-8", "replace"),
        )

    def logs(self, name: str, tail: int | None = None, stdout: bool = True) -> str:
        """A container's output so far (standard output and error), or its last `tail` lines;
        `stdout=False` for its diagnostics only."""
        try:
            raw = self._client.api.logs(name, stdout=stdout, stderr=True, tail=tail or "all")
        except DockerException:
            return ""
        return bytes(raw).decode("utf-8", "replace")

    def remove(self, name: str) -> None:
        with contextlib.suppress(DockerException):
            self._client.api.remove_container(name, force=True)

    def exec(
        self,
        name: str,
        command: list[str],
        *,
        user: str | None = None,
        env: dict[str, str] | None = None,
    ) -> RunOutput:
        result: Any = self._client.containers.get(name).exec_run(
            command, user=user or "", demux=False, environment=env
        )
        output = (result.output or b"").decode("utf-8", "replace")
        return RunOutput(exit_code=int(result.exit_code), output=output)

    def follow(self, name: str, since: int | None = None) -> Iterator[str]:
        """Lines a container writes to standard output, as they arrive."""
        stream: Any = self._client.api.logs(
            name, stdout=True, stderr=False, stream=True, follow=True, since=since
        )
        pending = b""
        for chunk in stream:
            pending += chunk
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                yield line.decode("utf-8", "replace")

    def remove_volume(self, name: str) -> None:
        with contextlib.suppress(DockerException):
            self._client.api.remove_volume(name, force=True)

    def changes(self, name: str) -> list[dict[str, Any]]:
        """Files added, changed or deleted in a container since it was created."""
        return list(self._client.api.diff(name) or [])

    def container_id(self, name: str) -> str | None:
        try:
            return str(self._client.api.inspect_container(name)["Id"])
        except DockerException:
            return None

    def is_running(self, name: str) -> bool:
        try:
            return bool(self._client.api.inspect_container(name)["State"]["Running"])
        except DockerException:
            return False
