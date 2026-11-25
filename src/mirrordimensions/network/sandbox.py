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
from pathlib import Path

from mirrordimensions.config.manifest import Manifest
from mirrordimensions.engine.docker_api import ContainerSpec, Docker
from mirrordimensions.errors import MirrorError
from mirrordimensions.mcp.world import toolset
from mirrordimensions.mcp.world.toolset import Toolset
from mirrordimensions.network.certs import Leaf
from mirrordimensions.network.dns import ROOT_ZONE, render_corefile, render_hosts
from mirrordimensions.twins.base import TwinContext, get_twin
from mirrordimensions.twins.relay import Relay, relay_spec

IMAGES = {
    "dns": "coredns/coredns:1.15.0@sha256:0a9d8c8ddf34347eb59aad9a8784f0710de88d6d112726d11d271f9bc6daca26",
    "gateway": "mitmproxy/mitmproxy:12.3.1@sha256:2711066c855659b5af8b1dbb84494ed3eff69b42ece439c60b4fe09a2db829d4",
    "stub": "nginx:1.29-alpine@sha256:5616878291a2eed594aee8db4dade5878cf7edcb475e59193904b198d9b830de",
    "relay": "alpine:3.22@sha256:49340b346798875b5592e5d420241f2f9cfba5f47e62ebb1446a1b34734e898f",
    "probe": "nicolaka/netshoot:v0.14@sha256:7f08c4aff13ff61a35d30e30c5c1ea8396eac6ab4ce19fd02d5a4b3b5d0d09a2",
    # Tetragon (Apache-2.0): eBPF process and socket tracing in the engine kernel (0010, 0016).
    "tracer": "quay.io/cilium/tetragon:v1.8.0@sha256:5ed9088a1582131d71b06c98e0d549a37a71ae63ab13aabefc7a47553c822a9d",
}

LAN, APPS, UPLINK = "corp-lan", "corp-apps", "corp-uplink"
# Remote agents (decision 0024): the ingress and the exposed MCP fronts, nothing else.
INGRESS = "corp-dmz"
INGRESS_NAME = "lb-01"
INGRESS_PORT = 8080  # on the ingress's own loopback only; the relay reaches it from inside
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
    apps_dns_ip: str = "10.41.0.53"
    relay_ip: str = "10.41.0.5"
    gw_lan: str = "10.40.0.10"
    gw_apps: str = "10.41.0.10"
    gw_uplink: str = "10.42.0.10"
    ingress_subnet: str = "10.43.0.0/24"
    ingress_gw: str = "10.43.0.1"
    ingress_ip: str = "10.43.0.10"

    def app_ip(self, index: int) -> str:
        return f"10.41.0.{21 + index}"

    def db_ip(self, index: int) -> str:
        return f"10.41.0.{121 + index}"

    def ingress_app_ip(self, index: int) -> str:
        return f"10.43.0.{21 + index}"


@dataclass
class App:
    id: str
    hostname: str
    visibility: str
    container: str
    ip: str
    product: str | None = None
    db_container: str = ""
    db_ip: str = ""
    settings: dict[str, object] = field(default_factory=dict[str, object])
    rules: list[dict[str, object]] = field(default_factory=list[dict[str, object]])
    kind: str | None = None
    tools: Toolset | None = None  # kind mcp-server: loaded when the plan knows its project
    remote: str | None = None  # the public hostname it is exposed at (decision 0024)
    ingress_ip: str = ""  # its address on the ingress network, when exposed

    @property
    def is_mcp(self) -> bool:
        return self.kind == "mcp-server" and self.product is None

    @property
    def port(self) -> int:
        if self.is_mcp:
            return MCP_PORT
        twin = get_twin(self.product)
        return twin.upstream_port if twin else 80

    @property
    def static_path(self) -> str:
        twin = get_twin(self.product)
        return twin.static_path if twin else "/"


@dataclass
class ModelPlan:
    """One model route. `ip`, `port` and `credential` are filled on the host just before the
    gateway starts (service.sandbox.resolve_models); the plan itself makes no network calls."""

    name: str
    provider: str
    host: str
    hosted_tools: str
    credential_env: str | None = None
    upstream: str | None = None  # self-hosted: address:port
    ip: str = ""
    port: int = 0
    credential: str | None = None

    @property
    def scheme(self) -> str:
        # Cloud providers are reached over TLS; a self-hosted server on the company's own
        # network is addressed as it is configured (address:port, plain HTTP).
        return "http" if self.provider == "self-hosted" else "https"


@dataclass
class Plan:
    world: str
    seed: int
    company: str
    apps: list[App]
    model_hosts: list[str]
    addr: Address = field(default_factory=Address)
    models: list[ModelPlan] = field(default_factory=list[ModelPlan])
    ca_pem: bytes = b""  # the install root, for services in the world that call each other

    @property
    def exposed(self) -> list[App]:
        """MCP servers exposed to remote agents through the ingress (decision 0024)."""
        return [a for a in self.apps if a.is_mcp and a.remote and a.visibility != "absent"]

    @property
    def resolvable(self) -> list[str]:
        # `absent` apps are not in DNS at all.
        return [a.hostname for a in self.apps if a.visibility != "absent"] + self.model_hosts

    @property
    def tls_names(self) -> list[str]:
        # Model hosts get certificates from the company's root, as behind a corporate
        # TLS-inspecting proxy.
        return [a.hostname for a in self.apps if a.visibility != "absent"] + self.model_hosts


DNS_NAME, GATEWAY_NAME, RELAY_NAME = "ns1", "edge-proxy-02", "klog"
TRACER_NAME = "auditd-01"
TRACER_POLICY = """apiVersion: cilium.io/v1alpha1
kind: TracingPolicy
metadata:
  name: sockets
spec:
  kprobes:
  - call: "tcp_connect"
    syscall: false
    args:
    - index: 0
      type: "sock"
    selectors:
    - matchNamespaces:
      - namespace: Pid
        operator: NotIn
        values: ["host_ns"]
  - call: "ip_send_skb"
    syscall: false
    args:
    - index: 1
      type: "skb"
    selectors:
    - matchNamespaces:
      - namespace: Pid
        operator: NotIn
        values: ["host_ns"]
      matchArgs:
      - index: 1
        operator: "Protocol"
        values: ["IPPROTO_UDP"]
"""
APPS_DNS_NAME = "ns2"


def plan_from(manifest: Manifest, root: Path | None = None) -> Plan:
    """The world's network plan. With the project's folder, MCP servers' tools are loaded."""
    addr = Address()
    apps = [
        App(
            id=a.id,
            hostname=a.hostname,
            visibility=a.visibility,
            container=f"app-{i + 1:02d}",
            ip=addr.app_ip(i),
            product=a.product,
            db_container=f"db-{i + 1:02d}",
            db_ip=addr.db_ip(i),
            settings=dict(a.settings),
            rules=[r.model_dump(exclude_none=True) for r in a.rules],
            kind=a.kind,
            remote=a.remote.hostname if a.remote else None,
            ingress_ip=addr.ingress_app_ip(i) if a.remote else "",
        )
        for i, a in enumerate(manifest.apps)
        if a.build != "unavailable"  # recorded in the definition, left out of creation
    ]
    if root is not None:
        app_ids = {a.id for a in manifest.apps}
        for app, source in zip(
            apps, [a for a in manifest.apps if a.build != "unavailable"], strict=True
        ):
            if app.is_mcp and source.serves is not None:
                app.tools = toolset.load(root, app.id, source.serves.model_dump(), app_ids)
    return Plan(
        world=manifest.name,
        seed=manifest.company.seed,
        company=manifest.company.name,
        apps=apps,
        model_hosts=[m.host for m in manifest.models],
        addr=addr,
        models=[
            ModelPlan(
                name=m.name,
                provider=m.provider,
                host=m.host,
                hosted_tools=m.hosted_tools,
                credential_env=m.credential.from_env if m.credential else None,
                upstream=m.upstream,
            )
            for m in manifest.models
        ],
    )


def routes_json(plan: Plan, secrets: list[str]) -> bytes:
    """The gateway's configuration: routes, and each system's surfaces, rules and errors."""
    from mirrordimensions.twins.profile import Profile

    routes: dict[str, dict[str, object]] = {}
    for app in plan.apps:
        if app.visibility == "absent":
            continue
        route: dict[str, object] = {
            "upstream": f"http://{app.ip}:{app.port}",
            "visibility": app.visibility,
        }
        if app.product and get_twin(app.product) is not None:
            profile = Profile(app.product)
            route.update(
                {"surfaces": profile.surfaces, "errors": profile.errors, "rules": app.rules}
            )
        if app.is_mcp:
            route["mcp"] = {"tools": toolset.gateway_surfaces(app.tools) if app.tools else {}}
        routes[app.hostname] = route
    for model in plan.models:
        if not model.ip:
            continue  # not resolved: the host stays unknown to the gateway and is refused
        routes[model.host] = {
            "upstream": f"{model.scheme}://{model.ip}:{model.port}",
            "visibility": "granted",
            "model": {
                "name": model.name,
                "provider": model.provider,
                "hosted_tools": model.hosted_tools,
                "credential": model.credential,
                "sni": model.host,
            },
        }
    redact = [*secrets, *(m.credential for m in plan.models if m.credential)]
    return json.dumps({"routes": routes, "secrets": redact, "seed": plan.seed}, indent=2).encode()


ROUTES_PATH = "/etc/edge/routes.json"


def refreshed_routes(current: bytes, plan: Plan, identities: dict[str, str] | None = None) -> bytes:
    """The gateway's routes with each system's visibility, surfaces and rules as the plan has
    them now. Model routes and redaction stay as `mirror up` resolved them, and a system
    is only updated, never added or removed: that changes DNS and containers, which only
    `mirror up` does."""
    data = json.loads(current)
    fresh = json.loads(routes_json(plan, []))["routes"]
    for host, route in fresh.items():
        if host in data["routes"] and "model" not in route:
            data["routes"][host] = route
    # Whose requests come from which address in this run, for rules scoped to one agent.
    data["identities"] = dict(identities or {})
    return json.dumps(data, indent=2).encode()


def refresh_routes(docker: Docker, plan: Plan, identities: dict[str, str] | None = None) -> None:
    """Hand the running gateway the current rules and visibility; it reloads them before
    its next request (decision 0021)."""
    owner = docker.labels(GATEWAY_NAME).get(LABEL)
    if owner != plan.world:
        raise MirrorError(
            f"The sandbox running in the engine is {owner or 'another world'}'s, not {plan.world}'s.",
            "Rules and visibility go only to this world's own gateway.",
            "Bring that sandbox down and this one up: mirror down, then mirror up here.",
        )
    current = docker.read_file(GATEWAY_NAME, ROUTES_PATH)
    if current is None:
        raise MirrorError(
            "The gateway has no routes file.",
            "The sandbox is not up as expected.",
            "Run: mirror up",
        )
    fresh = refreshed_routes(current, plan, identities)
    docker.put_files(GATEWAY_NAME, {ROUTES_PATH: (fresh, 0o644)})


def egress_entries(plan: Plan) -> list[tuple[str, str, int]]:
    """What the edge firewall lets out: the gateway's uplink address to each model route's
    one upstream address and port. Nothing else leaves the engine."""
    return [(plan.addr.gw_uplink, m.ip, m.port) for m in plan.models if m.ip and m.port]


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


def twin_context(plan: Plan, app: App, secrets: dict[str, str]) -> TwinContext:
    return TwinContext(
        app_id=app.id,
        hostname=app.hostname,
        company=plan.company,
        seed=plan.seed,
        app_container=app.container,
        app_ip=app.ip,
        db_container=app.db_container,
        db_ip=app.db_ip,
        network=APPS,
        dns=[plan.addr.apps_dns_ip],
        secrets={k.split(":", 1)[1]: v for k, v in secrets.items() if k.startswith(f"{app.id}:")},
        settings=dict(app.settings),
        gateway_ip=plan.addr.gw_apps,
    )


def specs(
    plan: Plan, leaves: list[Leaf], secrets: list[str], app_secrets: dict[str, str] | None = None
) -> list[ContainerSpec]:
    a = plan.addr
    edge_py = files("mirrordimensions.network.payloads").joinpath("edge.py").read_bytes()
    models_py = files("mirrordimensions.network.payloads").joinpath("models.py").read_bytes()
    behavior_py = files("mirrordimensions.network.payloads").joinpath("behavior.py").read_bytes()
    mcpcap_py = files("mirrordimensions.network.payloads").joinpath("mcpcap.py").read_bytes()
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
        # The system network's own resolver: twins resolve the world's names to the gateway's
        # address on their network, and nothing else. Without it, Docker's embedded DNS would
        # forward twins' lookups to the engine's real resolver.
        ContainerSpec(
            name=APPS_DNS_NAME,
            image=IMAGES["dns"],
            command=["-conf", "/etc/coredns/Corefile"],
            networks={APPS: a.apps_dns_ip},
            cap_add=["NET_BIND_SERVICE"],
            files={
                "/etc/coredns/Corefile": (render_corefile().encode(), 0o644),
                "/etc/coredns/hosts": (render_hosts(plan.resolvable, a.gw_apps).encode(), 0o644),
                "/etc/coredns/root.zone": (ROOT_ZONE.encode(), 0o644),
            },
            labels=label,
        ),
        relay_spec(APPS, a.relay_ip, [a.apps_dns_ip]),
        # In the engine's own namespaces, on no network: it watches every container from the
        # kernel, so nothing is added inside the agent's container (decision 0016).
        ContainerSpec(
            name=TRACER_NAME,
            image=IMAGES["tracer"],
            entrypoint=["/usr/bin/tetragon"],
            command=[
                "--export-filename",
                "/dev/stdout",
                # Tetragon rotates its export file at 10 MB by default, and "rotating"
                # /dev/stdout silently ends the stream; Docker's log rotation bounds it instead.
                "--export-file-max-size-mb",
                "1000000",
                "--export-allowlist",
                '{"event_set":["PROCESS_EXEC","PROCESS_KPROBE"]}',
                "--tracing-policy",
                "/etc/tetragon/sockets.yaml",
            ],
            networks={},
            network_mode="none",
            privileged=True,
            pid_mode="host",
            cgroupns="host",
            engine_binds={"/sys/kernel": "/sys/kernel"},
            log_options={"max-size": "50m", "max-file": "3"},
            files={"/etc/tetragon/sockets.yaml": (TRACER_POLICY.encode(), 0o644)},
            labels=label,
        ),
        ContainerSpec(
            name=GATEWAY_NAME,
            image=IMAGES["gateway"],
            command=_gateway_command(plan),
            networks={LAN: a.gw_lan, APPS: a.gw_apps, UPLINK: a.gw_uplink},
            default_route=UPLINK,  # model calls leave from the uplink address only
            sysctls={"net.ipv4.ip_unprivileged_port_start": "0"},
            cap_add=["SETUID", "SETGID", "CHOWN", "DAC_OVERRIDE", "FOWNER"],
            files={
                "/etc/edge/edge.py": (edge_py, 0o644),
                "/etc/edge/behavior.py": (behavior_py, 0o644),
                "/etc/edge/models.py": (models_py, 0o644),
                "/etc/edge/mcpcap.py": (mcpcap_py, 0o644),
                ROUTES_PATH: (routes_json(plan, secrets), 0o644),
                **{f"/etc/edge/certs/{leaf.hostname}.pem": (leaf.pem, 0o644) for leaf in leaves},
            },
            labels=label,
        ),
    ]
    for app in plan.apps:
        if app.visibility == "absent":
            continue
        twin = get_twin(app.product)
        if twin is not None:
            for spec in twin.containers(twin_context(plan, app, app_secrets or {})):
                spec.labels = {**label, **spec.labels}
                out.append(spec)
            continue
        if app.is_mcp:
            out.append(mcp_front_spec(plan, app, label))
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
    if plan.exposed:
        out.append(ingress_spec(plan, secrets, label, edge_py, behavior_py, models_py, mcpcap_py))
    return out


def ingress_routes(plan: Plan, secrets: list[str]) -> bytes:
    """The ingress's routes: each exposed MCP server's public hostname, to that front on the
    ingress network. Nothing else is routed, so any other name is refused."""
    routes: dict[str, object] = {}
    for app in plan.exposed:
        assert app.remote is not None  # noqa: S101 (exposed means it has one)
        routes[app.remote.lower()] = {
            "upstream": f"http://{app.ingress_ip}:{MCP_PORT}",
            "visibility": "granted",
            "mcp": {"tools": toolset.gateway_surfaces(app.tools) if app.tools else {}},
        }
    return json.dumps({"routes": routes, "secrets": secrets, "seed": plan.seed}, indent=2).encode()


def ingress_spec(
    plan: Plan,
    secrets: list[str],
    label: dict[str, str],
    edge_py: bytes,
    behavior_py: bytes,
    models_py: bytes,
    mcpcap_py: bytes,
) -> ContainerSpec:
    """The ingress for remote agents (decision 0024): the gateway's capture code, routing the
    public hostnames to the exposed MCP fronts. It listens on its own loopback only (the
    relay reaches it through the Docker API) and sits on the ingress network alone with the
    fronts, which is internal: no twin, resolver, gateway, agent or route out."""
    return ContainerSpec(
        name=INGRESS_NAME,
        image=IMAGES["gateway"],
        command=[
            "mitmdump",
            "--mode",
            f"reverse:http://127.0.0.1:9@{INGRESS_PORT}",
            "--listen-host",
            "127.0.0.1",
            "--set",
            "connection_strategy=lazy",
            "--set",
            "keep_host_header=true",
            "--set",
            "onboarding=false",
            "--set",
            "flow_detail=0",
            "--set",
            "termlog_verbosity=error",
            "-s",
            "/etc/edge/edge.py",
        ],
        networks={INGRESS: plan.addr.ingress_ip},
        # The image's start-up script sets the user it runs as, as the gateway's does.
        cap_add=["SETUID", "SETGID", "CHOWN", "DAC_OVERRIDE", "FOWNER"],
        files={
            "/etc/edge/edge.py": (edge_py, 0o644),
            "/etc/edge/behavior.py": (behavior_py, 0o644),
            "/etc/edge/models.py": (models_py, 0o644),
            "/etc/edge/mcpcap.py": (mcpcap_py, 0o644),
            ROUTES_PATH: (ingress_routes(plan, secrets), 0o644),
        },
        labels=label,
    )


MCP_PORT = 8000
MCP_SERVER = "/opt/tools/server.py"
MCP_CONFIG = "/etc/tools/config.json"
MCP_CA = "/etc/tools/ca.crt"


def mcp_hosts(plan: Plan) -> dict[str, str]:
    return {a.id: a.hostname for a in plan.apps if a.visibility != "absent"}


def mcp_front_spec(
    plan: Plan, app: App, label: dict[str, str], tokens: dict[str, dict[str, object]] | None = None
) -> ContainerSpec:
    """A world MCP server: one file of this repository's code and its configuration, on the
    system network, calling the twins through the gateway by their production names."""
    server = files("mirrordimensions.mcp.world").joinpath("front.py").read_bytes()
    config = toolset.front_config(app.tools, mcp_hosts(plan), tokens) if app.tools else {}
    return ContainerSpec(
        name=app.container,
        image=IMAGES["gateway"],  # an image already in the engine with Python 3
        # An exposed front also joins the ingress network, its only other member the ingress.
        networks={APPS: app.ip, **({INGRESS: app.ingress_ip} if app in plan.exposed else {})},
        entrypoint=["python3", MCP_SERVER],
        command=[],
        dns=[plan.addr.apps_dns_ip],
        user="65534:65534",
        files={
            MCP_SERVER: (server, 0o644),
            MCP_CONFIG: (json.dumps(config).encode(), 0o644),
            MCP_CA: (plan.ca_pem, 0o644),
        },
        labels=label,
    )


def up(
    docker: Docker,
    plan: Plan,
    leaves: list[Leaf],
    secrets: list[str],
    app_secrets: dict[str, str] | None = None,
    on_step: object = None,
) -> list[str]:
    """Create the networks and containers, start them, and bring each twin to ready."""
    a = plan.addr
    label = {LABEL: plan.world}
    docker.ensure_network(LAN, a.lan_subnet, a.lan_gw, ipv6_subnet=a.lan_v6, labels=label)
    docker.ensure_network(APPS, a.apps_subnet, a.apps_gw, labels=label)
    docker.ensure_network(UPLINK, a.uplink_subnet, a.uplink_gw, labels=label)
    if plan.exposed:
        docker.ensure_network(INGRESS, a.ingress_subnet, a.ingress_gw, labels=label, internal=True)
    names: list[str] = []
    for spec in specs(plan, leaves, secrets, app_secrets):
        docker.pull(spec.image, platform=spec.platform)
        docker.create(spec)
        docker.start(spec.name)
        names.append(spec.name)
        if spec.name == TRACER_NAME:
            _wait_for_tracer(docker)
    relay = Relay(docker)
    for app in plan.apps:
        twin = get_twin(app.product)
        if twin is None or app.visibility == "absent":
            continue
        ctx = twin_context(plan, app, app_secrets or {})
        twin.wait_ready(relay, ctx, timeout_s=300)
        twin.bootstrap(docker, relay, ctx)
        if callable(on_step):
            on_step(f"{app.product} ready at {app.hostname}")
    return names


def _wait_for_tracer(docker: Docker, timeout_s: float = 90.0) -> None:
    """Return once the tracer is listening: a run must not start before its agent can be
    watched, and the tracer's start-up work (reading every process, loading its programs)
    should be over before anything is measured."""
    import time

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        recent = docker.logs(TRACER_NAME, tail=400)
        # Ready once it says so, or once events flow (its own lines and events share a stream).
        if "Listening for events" in recent or '"process_exec"' in recent:
            return
        if not docker.is_running(TRACER_NAME):
            break
        time.sleep(1)
    raise MirrorError(
        "The engine's tracer did not start.",
        docker.logs(TRACER_NAME, tail=5)[-300:],
        "Run: mirror engine check; runs need it for complete coverage.",
    )


def _blank_secrets(plan: Plan) -> dict[str, str]:
    """Names only: removing containers needs their specs, not their secrets."""
    keys = ("db_password", "admin_password", "user_password", "secret_key", "internal_token")
    return {f"{app.id}:{k}": "" for app in plan.apps for k in keys}


def down(docker: Docker, plan: Plan, purge: bool = False) -> None:
    for spec in specs(plan, [], [], _blank_secrets(plan)):
        docker.remove(spec.name)
    for net in (LAN, APPS, UPLINK, INGRESS):
        docker.remove_network(net)
    if purge:
        for app in plan.apps:
            twin = get_twin(app.product)
            if twin is not None:
                for volume in twin.volumes(twin_context(plan, app, _blank_secrets(plan))):
                    docker.remove_volume(volume)
