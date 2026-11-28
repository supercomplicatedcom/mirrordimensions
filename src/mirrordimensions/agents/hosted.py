# SPDX-License-Identifier: Apache-2.0
"""A hosted agent: the company's own image, unchanged, on the office network (build spec,
"Agent modes").

It gets what a workstation or build host at the company would have: the sandbox's resolver,
the corporate root certificate in its trust store, an ordinary host name, and credentials in
production form as environment variables. It gets no capabilities, the same masked paths as
every agent-position container, and nothing from the mirror itself: no files, labels or
variables that name the mirror (decision 0010).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass

from mirrordimensions.engine.docker_api import ContainerSpec, Docker
from mirrordimensions.errors import MirrorError
from mirrordimensions.network.egress_check import MASKED_PATHS
from mirrordimensions.network.sandbox import LAN, Plan
from mirrordimensions.twins.base import Identity

# Bundles that common base images read; the first one present is extended.
CA_BUNDLES = (
    "/etc/ssl/certs/ca-certificates.crt",  # Debian, Ubuntu, Alpine
    "/etc/pki/tls/certs/ca-bundle.crt",  # Fedora, RHEL
    "/etc/ssl/cert.pem",  # Alpine's LibreSSL path, macOS-like images
)
CA_FILE = "/usr/local/share/ca-certificates/corp-root.crt"
REFERENCE = re.compile(r"\$\{([a-z0-9-]+)\.(url|token|username|password)\}")


@dataclass(frozen=True)
class Placement:
    name: str  # container name and host name: an ordinary workstation name
    ip: str


# How a company's IT names its machines: one convention per world, chosen by its seed, so
# workstations are not named the same way in every world (decision 0029). `{n}` is a number.
WORKSTATION_NAMES = (
    "ws-{n:04d}",
    "lt-{n:05d}",
    "pc{n:05d}",
    "wks-{n:04d}",
    "nb-{n:04d}",
    "dt{n:04d}",
    "lap-{n:04d}",
    "w{n:06d}",
)
DESKTOP_NAMES = ("vdi-{n:04d}", "vd-{n:04d}", "rds{n:04d}", "desk-{n:04d}", "vdesk{n:03d}")


def convention(seed: int, names: tuple[str, ...]) -> str:
    return names[int(hashlib.sha256(f"{seed}:hostnames".encode()).hexdigest(), 16) % len(names)]


def placement(plan: Plan, agent_name: str) -> Placement:
    """A stable workstation name and address on the office network for this agent."""
    digest = int(hashlib.sha256(agent_name.encode()).hexdigest(), 16)
    number = 100 + digest % 40  # 10.40.0.100-139; the probe uses .142
    prefix = plan.addr.lan_subnet.split("/")[0].rsplit(".", 1)[0]
    name = convention(plan.seed, WORKSTATION_NAMES).format(n=1000 + digest % 9000)
    return Placement(name=name, ip=f"{prefix}.{number}")


def environment(declared: dict[str, str], identities: dict[str, Identity]) -> dict[str, str]:
    """The agent's variables: its own, with `${app.token}`-style references filled from the
    credentials issued to it. With none declared, each system's production-form variables."""
    if not declared:
        merged: dict[str, str] = {}
        for identity in identities.values():
            merged.update(identity.env)
        return merged

    def fill(match: re.Match[str]) -> str:
        app, part = match.group(1), match.group(2)
        identity = identities.get(app)
        if identity is None:
            raise MirrorError(
                f"The agent's variables refer to {app!r}, which issues it no credentials.",
                f"Systems with credentials: {', '.join(sorted(identities)) or 'none'}.",
                "Fix the reference in the agent file, or grant it access to that system.",
            )
        if part == "url":
            return next((v for k, v in identity.env.items() if k.endswith("_URL")), "")
        return {
            "token": identity.token,
            "username": identity.username,
            "password": identity.password,
        }[part]

    return {key: REFERENCE.sub(fill, value) for key, value in declared.items()}


KEY_FORMS = {
    # Each provider's key shape, so the placeholder reads as an ordinary deployed key.
    "anthropic": ("sk-ant-api03-", 93, "AA"),  # 108 characters, as issued
    "openai": ("sk-proj-", 156, ""),
}
_KEY_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def placeholder_key(provider: str, seed: int, route: str) -> str:
    """A key in the provider's own form that unlocks nothing: the gateway swaps in the real
    one. Deterministic for a world and route."""
    prefix, length, suffix = KEY_FORMS.get(provider, ("sk-", 48, ""))
    stream = b""
    counter = 0
    while len(stream) < length:
        stream += hashlib.sha256(f"{seed}:{route}:{counter}".encode()).digest()
        counter += 1
    body = "".join(_KEY_ALPHABET[b % len(_KEY_ALPHABET)] for b in stream[:length])
    return prefix + body + suffix


def model_placeholders(plan: Plan) -> dict[str, str]:
    """The model credential variables the agent is deployed with, holding placeholders."""
    return {
        m.credential_env: placeholder_key(m.provider, plan.seed, m.name)
        for m in plan.models
        if m.credential_env
    }


def spec(
    plan: Plan, where: Placement, image: str, env: dict[str, str], platform: str | None
) -> ContainerSpec:
    return ContainerSpec(
        name=where.name,
        image=image,
        networks={LAN: where.ip},
        dns=[plan.addr.dns_ip],
        masked_paths=MASKED_PATHS,
        env=env,
        hostname=where.name,
        platform=platform,
    )


def trust_root(docker: Docker, name: str, ca_pem: bytes) -> str:
    """Add the corporate root to the image's own trust store, as the company's image build
    would; return the bundle extended. Done before start: nothing runs in the container."""
    for bundle in CA_BUNDLES:
        current = docker.read_file(name, bundle)
        if current is not None:
            joined = current if current.endswith(b"\n") else current + b"\n"
            docker.put_files(name, {bundle: (joined + ca_pem, 0o644), CA_FILE: (ca_pem, 0o644)})
            return bundle
    raise MirrorError(
        "The agent's image has no system certificate bundle to add the company's root to.",
        f"Looked for {', '.join(CA_BUNDLES)}.",
        "Use a base image with ca-certificates installed.",
    )


def start(
    docker: Docker,
    container: ContainerSpec,
    ca_pem: bytes,
    before_start: Callable[[str], None] | None = None,
) -> str:
    docker.create(container)
    bundle = trust_root(docker, container.name, ca_pem)
    if before_start is not None:
        before_start(container.name)  # e.g. tell the tracer which container to watch
    docker.start(container.name)
    return bundle
