# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The control relay: how the host reaches twins (decision 0003).

A small container on the system network runs curl on the host's behalf, driven through
Docker exec. No twin port is published to the engine or the host, and the relay is not on
the agent network. Bodies travel base64-encoded in the exec environment and output.
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from mirrordimensions.engine.docker_api import ContainerSpec, Docker
from mirrordimensions.errors import MirrorError

RELAY_NAME = "ops-01"
RELAY_IMAGE = (
    "alpine/curl:8.17.0@sha256:2a36f3dfe424231c1b03753929e43dda451c29a6193873916924f0b6073bbc5f"
)


@dataclass
class Response:
    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict[str, str])  # when asked for

    def json(self) -> Any:
        return json.loads(self.body or b"null")


def relay_spec(network: str, ip: str, dns: list[str]) -> ContainerSpec:
    return ContainerSpec(
        name=RELAY_NAME,
        image=RELAY_IMAGE,
        command=["sleep", "infinity"],
        networks={network: ip},
        dns=dns,
    )


class Relay:
    def __init__(self, docker: Docker, name: str = RELAY_NAME) -> None:
        self.docker = docker
        self.name = name

    def request(
        self,
        method: str,
        url: str,
        *,
        body: bytes | str | dict[str, Any] | list[Any] | None = None,
        headers: dict[str, str] | None = None,
        basic: tuple[str, str] | None = None,
        timeout: int = 60,
        with_headers: bool = False,
    ) -> Response:
        # Unique file names: requests run concurrently in the same relay container.
        tag = secrets.token_hex(6)
        hdrs = dict(headers or {})
        payload = b""
        if isinstance(body, (dict, list)):
            payload = json.dumps(body).encode()
            hdrs.setdefault("Content-Type", "application/json")
        elif isinstance(body, str):
            payload = body.encode()
        elif isinstance(body, bytes):
            payload = body
        args = [
            "curl",
            "-sS",
            "-X",
            method,
            "--max-time",
            str(timeout),
            "-o",
            f"/tmp/out-{tag}",  # noqa: S108 (a path inside the relay container)
            "-w",
            "%{http_code}",
        ]
        for key, value in hdrs.items():
            args += ["-H", f"{key}: {value}"]
        if basic:
            args += ["-u", f"{basic[0]}:{basic[1]}"]
        if with_headers:
            args += ["-D", f"/tmp/hdr-{tag}"]  # noqa: S108 (inside the relay container)
        if payload:
            args += ["--data-binary", f"@/tmp/in-{tag}"]
        script = (
            f'printf %s "$BODY" | base64 -d > /tmp/in-{tag}; '
            + " ".join(_quote(a) for a in args)
            + f" {_quote(url)} 2>/dev/null; echo; base64 -w0 /tmp/out-{tag} 2>/dev/null; echo;"
            f" base64 -w0 /tmp/hdr-{tag} 2>/dev/null; rm -f /tmp/in-{tag} /tmp/out-{tag} /tmp/hdr-{tag}"
        )
        out = self.docker.exec(
            self.name, ["sh", "-c", script], env={"BODY": base64.b64encode(payload).decode()}
        )
        first, _, rest = out.output.partition("\n")
        try:
            status = int(first.strip()[-3:])
        except ValueError as exc:
            raise MirrorError(
                "The control relay could not reach a system.",
                f"{method} {url}: {out.output.strip()[:200]}",
                "Check that the sandbox is up: mirror status",
            ) from exc
        if status == 0:  # no connection (the system is starting, or gone)
            raise MirrorError(
                "The control relay could not reach a system.",
                f"{method} {url}: no connection",
                "Check that the sandbox is up: mirror status",
            )
        body_b64, _, headers_b64 = rest.partition("\n")
        got: dict[str, str] = {}
        for line in base64.b64decode(headers_b64.strip() or b"").decode("latin-1").splitlines():
            name, sep, value = line.partition(":")
            if sep and not name.startswith("HTTP/"):
                got[name.strip().lower()] = value.strip()
        return Response(status=status, body=base64.b64decode(body_b64.strip() or b""), headers=got)

    def wait_for(self, url: str, timeout_s: float, ok: tuple[int, ...] = (200,)) -> None:
        deadline = time.time() + timeout_s
        last = ""
        while time.time() < deadline:
            try:
                resp = self.request("GET", url, timeout=5)
                if resp.status in ok:
                    return
                last = f"HTTP {resp.status}"
            except MirrorError as exc:
                last = exc.why
            time.sleep(2)
        raise MirrorError(
            f"{url} did not become ready in {int(timeout_s)}s.",
            f"Last answer: {last}.",
            "See: mirror logs <app-id>",
        )


def _quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"
