# SPDX-License-Identifier: Apache-2.0
"""Copy twin volumes to and from snapshot volumes, without leaving the engine.

A throwaway helper container with no network mounts the live volume and its snapshot and
copies one onto the other. Twins are stopped while their volumes are copied, so the copy is
consistent. Snapshots never cross to the host; the project keeps only their index.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from mirrordimensions.engine.docker_api import ContainerSpec, Docker
from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.files import write_text

HELPER_IMAGE = "alpine:3.22@sha256:49340b346798875b5592e5d420241f2f9cfba5f47e62ebb1446a1b34734e898f"


class SnapshotInfo(BaseModel):
    name: str
    volumes: list[str]
    digest: str
    created: str
    seconds: float


def snapshot_volume(name: str, volume: str) -> str:
    return f"snap-{name}-{volume}"


def _copy(docker: Docker, source: str, target: str) -> str:
    """Make `target` an exact copy of `source`; return a digest of the copied tree."""
    spec = ContainerSpec(
        name=f"ops-sync-{hashlib.sha256(target.encode()).hexdigest()[:8]}",
        image=HELPER_IMAGE,
        command=[
            "sh",
            "-c",
            "set -e; rm -rf /dst/..?* /dst/.[!.]* /dst/* ; cp -a /src/. /dst/; "
            "cd /dst && find . -type f -exec sha256sum {} + | sort | sha256sum | cut -c1-16",
        ],
        network_mode="none",
        networks={},
        volumes={source: "/src", target: "/dst"},
        cap_add=["CHOWN", "DAC_OVERRIDE", "FOWNER", "FSETID"],
    )
    docker.pull(HELPER_IMAGE)
    docker.create(spec)
    docker.start(spec.name)
    result = docker.wait(spec.name, timeout_s=600)
    docker.remove(spec.name)
    if result.exit_code != 0:
        raise MirrorError(
            "Copying a volume failed.",
            f"{source} -> {target}: {result.output.strip()[-200:]}",
            "Free disk in the engine (mirror engine status) and try again.",
        )
    return result.output.strip().splitlines()[-1] if result.output.strip() else ""


def save(
    docker: Docker, name: str, volumes: list[str], containers: list[str], index: Path
) -> SnapshotInfo:
    started = time.time()
    for c in containers:
        docker.stop(c)
    digests = [_copy(docker, v, snapshot_volume(name, v)) for v in volumes]
    info = SnapshotInfo(
        name=name,
        volumes=volumes,
        digest=hashlib.sha256("".join(digests).encode()).hexdigest()[:16],
        created=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        seconds=round(time.time() - started, 1),
    )
    current: dict[str, Any] = (
        json.loads(index.read_text(encoding="utf-8")) if index.is_file() else {}
    )
    current[name] = info.model_dump()
    write_text(index, json.dumps(current, indent=2, sort_keys=True) + "\n")
    return info


def restore(docker: Docker, name: str, index: Path, containers: list[str]) -> float:
    current: dict[str, Any] = (
        json.loads(index.read_text(encoding="utf-8")) if index.is_file() else {}
    )
    if name not in current:
        raise MirrorError(
            f"No snapshot called {name!r}.",
            f"Snapshots: {', '.join(current) or 'none'}.",
            "Run: mirror build, or mirror snapshot list",
        )
    info = SnapshotInfo.model_validate(current[name])
    started = time.time()
    for c in containers:
        docker.stop(c)
    for volume in info.volumes:
        _copy(docker, snapshot_volume(name, volume), volume)
    return time.time() - started
