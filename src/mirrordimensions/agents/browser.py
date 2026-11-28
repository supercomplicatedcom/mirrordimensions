# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The managed browser for browser-mode agents (build spec, "Agent modes"; decision 0014).

Three containers on the office network, all hardened as agent-position containers:

- the browser, `vdi-NNNN`: headless Chromium with DevTools on loopback only, the company
  root in its NSS store, the sandbox resolver;
- the observer, sharing the browser's network namespace: passes the agent's DevTools
  connection through unchanged, records it, and holds a read-only session for navigations
  and screenshots;
- the agent's own program, `ws-NNNN`, as a hosted agent runs, given `BROWSER_CDP_URL`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib.resources import files

from mirrordimensions.agents import hosted
from mirrordimensions.engine.docker_api import ContainerSpec, Docker
from mirrordimensions.network.egress_check import MASKED_PATHS
from mirrordimensions.network.sandbox import IMAGES, LAN, Plan
from mirrordimensions.twins.base import Identity

# The Playwright image ships Chromium builds for arm64 and amd64 (multi-arch index).
BROWSER_BASE = (
    "mcr.microsoft.com/playwright/python:v1.65.2-noble"
    "@sha256:38dd67fc654b56b3cba611e4c8eb71cd33750e1cd29eea2a5dc00b484817a75f"
)
BROWSER_USER = "pwuser"
NSS_DB = f"/home/{BROWSER_USER}/.pki/nssdb"
PROFILE = f"/home/{BROWSER_USER}/.config/chromium"
DEVTOOLS_PORT = 9222
CDP_ENV = "BROWSER_CDP_URL"
OBSERVER_CONFIG = "/etc/observer/config.json"
OBSERVER_SCRIPT = "/opt/observer/observer.py"
CA_PATH = hosted.CA_FILE
OBSERVER_SUFFIX = "-console"  # container name only; never visible inside any container

# Chromium's headless shell, found at build time under the version Playwright pinned.
_FIND_SHELL = (
    "find /ms-playwright -type f -name chrome-headless-shell -perm -u+x | head -n 1 | "
    "xargs -I{} ln -s {} /usr/local/bin/chromium"
)


def dockerfile(ca_pem: bytes) -> dict[str, bytes]:
    """The browser image for this install: the base image with the company's root in the
    browser's own store. Built at setup time; the build needs no network beyond the apt
    mirror for NSS tools, reached from the engine's own namespace."""
    nickname = "Corporate Root CA"
    text = f"""FROM {BROWSER_BASE}
RUN apt-get update && apt-get install -y --no-install-recommends libnss3-tools \\
 && rm -rf /var/lib/apt/lists/* && {_FIND_SHELL}
COPY corp-root.crt {CA_PATH}
RUN update-ca-certificates \\
 && install -d -o {BROWSER_USER} -g {BROWSER_USER} -m 700 /home/{BROWSER_USER}/.pki {NSS_DB} \\
 && su {BROWSER_USER} -s /bin/sh -c 'certutil -d sql:{NSS_DB} -N --empty-password \\
 && certutil -d sql:{NSS_DB} -A -t "C,," -n "{nickname}" -i {CA_PATH}'
USER {BROWSER_USER}
WORKDIR /home/{BROWSER_USER}
"""
    return {"Dockerfile": text.encode(), "corp-root.crt": ca_pem}


def image_tag(ca_pem: bytes) -> str:
    """One browser image per install root; the tag never appears inside a container."""
    digest = hashlib.sha256(BROWSER_BASE.encode() + ca_pem).hexdigest()[:12]
    return f"workstation-browser:{digest}"


def ensure_image(docker: Docker, ca_pem: bytes, platform: str | None = None) -> str:
    tag = image_tag(ca_pem)
    if docker.image_arch(tag) is None:
        docker.build(dockerfile(ca_pem), tag, platform)
    return tag


@dataclass(frozen=True)
class BrowserPlacement:
    name: str
    ip: str

    @property
    def cdp_url(self) -> str:
        return f"http://{self.ip}:{DEVTOOLS_PORT}"

    @property
    def observer(self) -> str:
        return self.name + OBSERVER_SUFFIX


def placement(plan: Plan, agent_name: str) -> BrowserPlacement:
    """The browser's virtual-desktop name and address, distinct from the agent's own."""
    digest = int(hashlib.sha256(f"{agent_name}/desktop".encode()).hexdigest(), 16)
    agent = hosted.placement(plan, agent_name)
    prefix = agent.ip.rsplit(".", 1)[0]
    number = 140 + digest % 40  # 10.40.0.140-179, clear of workstations (.100-.139)
    if number == 142:  # the address doctor's probe uses
        number = 143
    name = hosted.convention(plan.seed, hosted.DESKTOP_NAMES).format(n=1000 + digest % 9000)
    return BrowserPlacement(name=name, ip=f"{prefix}.{number}")


CHROMIUM_FLAGS = (
    "--no-sandbox",  # Chromium's own sandbox needs capabilities the container does not have
    "--no-first-run",
    "--no-default-browser-check",
    f"--user-data-dir={PROFILE}",
    f"--remote-debugging-port={DEVTOOLS_PORT}",  # loopback only: Chromium's default address
    "--window-size=1280,800",
    "about:blank",
)


def browser_spec(plan: Plan, where: BrowserPlacement, image: str) -> ContainerSpec:
    return ContainerSpec(
        name=where.name,
        image=image,
        networks={LAN: where.ip},
        command=["chromium", *CHROMIUM_FLAGS],
        dns=[plan.addr.dns_ip],
        masked_paths=MASKED_PATHS,
        hostname=where.name,
        user=BROWSER_USER,
    )


def observer_spec(where: BrowserPlacement, secrets: list[str]) -> ContainerSpec:
    script = files("mirrordimensions.network.payloads").joinpath("observer.py").read_bytes()
    config = {
        "listen": f"{where.ip}:{DEVTOOLS_PORT}",
        "upstream": f"127.0.0.1:{DEVTOOLS_PORT}",
        "secrets": sorted({s for s in secrets if s}),
        "screenshot_every_s": 1.0,
    }
    return ContainerSpec(
        name=where.observer,
        image=IMAGES["gateway"],  # an image already in the engine with Python 3
        networks={},
        network_mode=f"container:{where.name}",
        entrypoint=["python3", OBSERVER_SCRIPT],
        command=[],
        files={
            OBSERVER_SCRIPT: (script, 0o644),
            OBSERVER_CONFIG: (json.dumps(config).encode(), 0o600),
        },
        masked_paths=MASKED_PATHS,
        user="root",  # reads its own config; holds no capabilities (all dropped)
    )


def start(
    docker: Docker, plan: Plan, where: BrowserPlacement, image: str, secrets: list[str]
) -> None:
    """Start the browser, then its observer. The agent starts after both are up."""
    docker.create(browser_spec(plan, where, image))
    docker.start(where.name)
    observer = observer_spec(where, secrets)
    docker.create(observer)
    docker.start(observer.name)


def stop(docker: Docker, where: BrowserPlacement) -> None:
    docker.remove(where.observer)
    docker.remove(where.name)


def environment(
    declared: dict[str, str], identities: dict[str, Identity], where: BrowserPlacement
) -> dict[str, str]:
    """The agent program's variables. A browser agent signs in as a person does, so by
    default it gets each system's address, username and password, not an API token; and
    always the browser's DevTools address."""
    if declared:
        env = hosted.environment(declared, identities)
    else:
        env = {}
        for identity in identities.values():
            url_key = next((k for k in identity.env if k.endswith("_URL")), None)
            if url_key is None:
                continue
            prefix = url_key.removesuffix("_URL")
            env[url_key] = identity.env[url_key]
            env[f"{prefix}_USERNAME"] = identity.username
            env[f"{prefix}_PASSWORD"] = identity.password
    env.setdefault(CDP_ENV, where.cdp_url)
    return env
