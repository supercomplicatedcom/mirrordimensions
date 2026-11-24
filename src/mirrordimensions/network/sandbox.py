# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The sealed network for one world, built in the engine through the Docker API.

Three networks (decision 0002, build spec "Complete coverage"):

| Network     | Members                                   | Purpose                               |
| ----------- | ----------------------------------------- | ------------------------------------- |
| corp-lan    | agent, browser, resolver, gateway         | the only network the agent is on      |
| corp-apps   | gateway, twins and their databases        | where the apps live                   |
| corp-uplink | gateway only                              | the route to allowed model endpoints  |

The engine's edge firewall is the sinkhole: every packet a container sends to anything but
another container on its own network is dropped and logged in the engine kernel, and the
log relay turns those lines into `egress.blocked` events (decision 0011).

Names are ordinary infrastructure names. Container names, hostnames and network names are
visible to the agent (reverse DNS answers name.network), so none may contain a tell.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib.resources import files

from mirrordimensions.config.manifest import Manifest
from mirrordimensions.engine.docker_api import ContainerSpec, Docker
from mirrordimensions.network.certs import Leaf
from mirrordimensions.network.dns import ROOT_ZONE, render_corefile, render_hosts

IMAGES = {
    "dns": "coredns/coredns:1.15.0@sha256:0a9d8c8ddf34347eb59aad9a8784f0710de88d6d112726d11d271f9bc6daca26",
    "gateway": "mitmproxy/mitmproxy:12.3.1@sha256:2711066c855659b5af8b1dbb84494ed3eff69b42ece439c60b4fe09a2db829d4",
    "stub": "nginx:1.29-alpine@sha256:5616878291a2eed594aee8db4dade5878cf7edcb475e59193904b198d9b830de",
    "relay": "alpine:3.22@sha256:49340b346798875b5592e5d420241f2f9cfba5f47e62ebb1446a1b34734e898f",
    "probe": "nicolaka/netshoot:v0.14@sha256:7f08c4aff13ff61a35d30e30c5c1ea8396eac6ab4ce19fd02d5a4b3b5d0d09a2",
}

LAN, APPS, UPLINK = "corp-lan", "corp-apps", "corp-uplink"
LABEL = "com.mirrordimensions.world"  # labels are not visible inside containers


@dataclass
class Address:
    lan_subnet: str = "10.40.0.0/24"
    lan_gw: str = "10.40.0.1"
    lan_v6: str = "fd4a:4000:0:1::/64"
    apps_subnet: str = "10.41.0.0/24"
    apps_gw: str = "10.41.0.1"
    uplink_subnet: str = "10.42.0.0/24"
    uplink_gw: str = "10.42.0.1"
    dns_ip: str = "10.40.0.53"
    gw_lan: str = "10.40.0.10"
    gw_apps: str = "10.41.0.10"
    gw_uplink: str = "10.42.0.10"

    def app_ip(self, index: int) -> str:
        return f"10.41.0.{21 + index}"


@dataclass
class App:
    id: str
    hostname: str
    visibility: str
    container: str
    ip: str


@dataclass
class Plan:
    world: str
    seed: int
    company: str
    apps: list[App]
    model_hosts: list[str]
    addr: Address = field(default_factory=Address)

    @property
    def resolvable(self) -> list[str]:
        # `absent` apps are not in DNS at all.
        return [a.hostname for a in self.apps if a.visibility != "absent"] + self.model_hosts

    @property
    def tls_names(self) -> list[str]:
        return [a.hostname for a in self.apps if a.visibility != "absent"]


DNS_NAME, GATEWAY_NAME, RELAY_NAME = "ns1", "edge-proxy-02", "klog"


def plan_from(manifest: Manifest) -> Plan:
    addr = Address()
    apps = [
        App(
            id=a.id,
            hostname=a.hostname,
            visibility=a.visibility,
            container=f"app-{i + 1:02d}",
            ip=addr.app_ip(i),
        )
        for i, a in enumerate(manifest.apps)
    ]
    return Plan(
        world=manifest.name,
        seed=manifest.company.seed,
        company=manifest.company.name,
        apps=apps,
        model_hosts=[m.host for m in manifest.models],
        addr=addr,
    )


def routes_json(plan: Plan, secrets: list[str]) -> bytes:
    routes: dict[str, dict[str, str]] = {}
    for app in plan.apps:
        if app.visibility == "absent":
            continue
        routes[app.hostname] = {"upstream": f"http://{app.ip}:80", "visibility": app.visibility}
    return json.dumps({"routes": routes, "secrets": secrets}, indent=2).encode()


def stub_page(plan: Plan, app: App) -> bytes:
    """A plain sign-in page standing in for a product until its twin exists (M2)."""
    return (
        '<!doctype html>\n<html lang="en">\n<head><meta charset="utf-8">'
        f"<title>Sign in · {plan.company}</title></head>\n"
        f"<body><main><h1>{plan.company}</h1><p>Sign in to continue.</p>"
        '<form method="post" action="/login"><input name="username" autocomplete="username">'
        '<input name="password" type="password"><button>Sign in</button></form></main></body>\n'
        "</html>\n"
    ).encode()


def _gateway_command(plan: Plan) -> list[str]:
    # The default upstream is a closed local port. Known hostnames are routed per request by
    # the add-on; anything else that is passed through ends in an ordinary refusal.
    default = "http://127.0.0.1:9"
    command = [
        "mitmdump",
        "--mode",
        f"reverse:{default}@443",
        "--mode",
        f"reverse:{default}@80",
        "--set",
        "connection_strategy=lazy",
        "--set",
        "keep_host_header=true",
        "--set",
        "upstream_cert=false",
        "--set",
        "onboarding=false",
        "--set",
        "flow_detail=0",
        "--set",
        "termlog_verbosity=error",
        "-s",
        "/etc/edge/edge.py",
    ]
    for host in plan.tls_names:
        command += ["--certs", f"{host}=/etc/edge/certs/{host}.pem"]
    return command


def specs(plan: Plan, leaves: list[Leaf], secrets: list[str]) -> list[ContainerSpec]:
    a = plan.addr
    edge_py = files("mirrordimensions.network.payloads").joinpath("edge.py").read_bytes()
    label = {LABEL: plan.world}
    out = [
        ContainerSpec(
            name=RELAY_NAME,
            image=IMAGES["relay"],
            command=["sh", "-c", "exec cat /dev/kmsg"],
            cap_add=["SYSLOG"],
            devices=["/dev/kmsg:/dev/kmsg:r"],
            network_mode="none",
            networks={},
            labels=label,
        ),
        ContainerSpec(
            name=DNS_NAME,
            image=IMAGES["dns"],
            command=["-conf", "/etc/coredns/Corefile"],
            networks={LAN: a.dns_ip},
            cap_add=["NET_BIND_SERVICE"],
            files={
                "/etc/coredns/Corefile": (render_corefile().encode(), 0o644),
                "/etc/coredns/hosts": (render_hosts(plan.resolvable, a.gw_lan).encode(), 0o644),
                "/etc/coredns/root.zone": (ROOT_ZONE.encode(), 0o644),
            },
            labels=label,
        ),
        ContainerSpec(
            name=GATEWAY_NAME,
            image=IMAGES["gateway"],
            command=_gateway_command(plan),
            networks={LAN: a.gw_lan, APPS: a.gw_apps, UPLINK: a.gw_uplink},
            sysctls={"net.ipv4.ip_unprivileged_port_start": "0"},
            cap_add=["SETUID", "SETGID", "CHOWN", "DAC_OVERRIDE", "FOWNER"],
            files={
                "/etc/edge/edge.py": (edge_py, 0o644),
                "/etc/edge/routes.json": (routes_json(plan, secrets), 0o644),
                **{f"/etc/edge/certs/{leaf.hostname}.pem": (leaf.pem, 0o644) for leaf in leaves},
            },
            labels=label,
        ),
    ]
    for app in plan.apps:
        if app.visibility == "absent":
            continue
        out.append(
            ContainerSpec(
                name=app.container,
                image=IMAGES["stub"],
                networks={APPS: app.ip},
                cap_add=["NET_BIND_SERVICE", "SETUID", "SETGID", "CHOWN"],
                files={"/usr/share/nginx/html/index.html": (stub_page(plan, app), 0o644)},
                labels=label,
            )
        )
    return out


def up(docker: Docker, plan: Plan, leaves: list[Leaf], secrets: list[str]) -> list[str]:
    """Create the networks and containers and start them. Returns the container names."""
    a = plan.addr
    label = {LABEL: plan.world}
    docker.ensure_network(LAN, a.lan_subnet, a.lan_gw, ipv6_subnet=a.lan_v6, labels=label)
    docker.ensure_network(APPS, a.apps_subnet, a.apps_gw, labels=label)
    docker.ensure_network(UPLINK, a.uplink_subnet, a.uplink_gw, labels=label)
    names: list[str] = []
    for spec in specs(plan, leaves, secrets):
        docker.pull(spec.image)
        docker.create(spec)
        docker.start(spec.name)
        names.append(spec.name)
    return names


def down(docker: Docker, plan: Plan) -> None:
    for spec in specs(plan, [], []):
        docker.remove(spec.name)
    for net in (LAN, APPS, UPLINK):
        docker.remove_network(net)
