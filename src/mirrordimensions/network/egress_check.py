# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""`mirror doctor`: prove the sealed network from where the agent sits.

Suites (build spec "Sealed network" and "Complete coverage and hidden machinery"):

- egress: every way out fails, and each attempt is recorded within one second
- separation: the agent network cannot reach the system network
- inside-out: from the agent's seat, nothing that runs the world can be found
- naming: nothing the agent can read contains a word that gives the test away
- transparency: a response through the gateway matches the same response fetched directly
- capture: each exchange is one http.exchange event, with secrets redacted

The probe is a throwaway container with the agent's hardening, network and DNS. It carries
network tools the agent may not have, which only makes the checks stricter.
"""

from __future__ import annotations

import re
import secrets
import time
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel

from mirrordimensions.engine.checks import host_listener
from mirrordimensions.engine.docker_api import ContainerSpec, Docker
from mirrordimensions.network.events import Collector
from mirrordimensions.network.sandbox import (
    APPS,
    DNS_NAME,
    GATEWAY_NAME,
    IMAGES,
    LAN,
    Plan,
)
from mirrordimensions.world.denylist import TELL_WORDS

PROBE = "ws-0142"
PROBE_IP = "10.40.0.142"
APPS_PROBE = "ops-jump-01"
APPS_PROBE_IP = "10.41.0.142"
EVENT_BUDGET_S = 1.0

# Docker's default masked paths, plus the engine's hardware identity (decision 0010).
MASKED_PATHS = [
    "/proc/asound",
    "/proc/acpi",
    "/proc/interrupts",
    "/proc/kcore",
    "/proc/keys",
    "/proc/latency_stats",
    "/proc/timer_list",
    "/proc/timer_stats",
    "/proc/sched_debug",
    "/proc/scsi",
    "/sys/firmware",
    "/sys/devices/virtual/powercap",
    "/sys/class/dmi",
    "/sys/devices/virtual/dmi",
]


class Check(BaseModel):
    suite: str
    name: str
    outcome: Literal["pass", "fail", "n/a"]
    detail: str = ""
    latency_s: float | None = None


class DoctorReport(BaseModel):
    isolation: Literal["full", "reduced", "failed"]
    boundary: str
    checks: list[Check]

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if c.outcome == "fail"]


class Probe:
    def __init__(self, docker: Docker, ca_pem: bytes) -> None:
        self.docker = docker
        self.ca_pem = ca_pem

    def start(self, name: str, network: str, ip: str, dns: list[str] | None) -> None:
        self.docker.pull(IMAGES["probe"])
        self.docker.create(
            ContainerSpec(
                name=name,
                image=IMAGES["probe"],
                command=["sleep", "infinity"],
                networks={network: ip},
                dns=dns,
                cap_add=["NET_RAW"],  # ping only; agents get no capabilities
                masked_paths=MASKED_PATHS,
                files={"/usr/local/share/ca-certificates/corp-root.crt": (self.ca_pem, 0o644)},
            )
        )
        self.docker.start(name)
        self.docker.exec(name, ["update-ca-certificates"], user="root")

    def sh(self, name: str, command: str) -> tuple[int, str]:
        out = self.docker.exec(name, ["sh", "-c", command])
        return out.exit_code, out.output

    def stop(self, *names: str) -> None:
        for name in names:
            self.docker.remove(name)


def _attempt(
    probe: Probe,
    collector: Collector,
    suite: str,
    name: str,
    command: str,
    reached: Callable[[int, str], bool],
    match: Callable[[dict[str, Any]], bool],
) -> Check:
    """Run an attempt that must fail, then wait for the event that records it."""
    started = time.time()
    code, output = probe.sh(PROBE, command)
    if reached(code, output):
        return Check(
            suite=suite, name=name, outcome="fail", detail=f"reached: {output.strip()[:200]}"
        )
    event = collector.wait_for(match, after=started, timeout=EVENT_BUDGET_S + 3)
    if event is None:
        return Check(
            suite=suite,
            name=name,
            outcome="fail",
            detail="blocked, but no event was recorded" + _why_unrecorded(probe, command, output),
        )
    latency = round(event["arrived"] - collector.offset - started, 3)
    ok = latency <= EVENT_BUDGET_S + _command_slack(command)
    return Check(
        suite=suite,
        name=name,
        outcome="pass" if ok else "fail",
        latency_s=latency,
        detail=f"{event['type']} {_brief(event)}" + ("" if ok else f"; recorded after {latency}s"),
    )


def _why_unrecorded(probe: Probe, command: str, output: str) -> str:
    """What the attempt itself saw, so a missing event can be told apart from a packet that
    never left the container (for instance, no route for its address family)."""
    said = " ".join(output.split())[:160]
    extra = ""
    if " -6 " in command:
        _, routes = probe.sh(PROBE, "ip -6 route 2>&1; ip -6 addr show scope global 2>&1")
        extra = "; IPv6 routes: " + (" | ".join(routes.split("\n")[:4]).strip() or "none")
    return (f"; it said: {said}" if said else "") + extra


def _command_slack(command: str) -> float:
    # Time between starting the exec and the first packet leaving: docker exec start-up.
    return 0.5


def _brief(event: dict[str, Any]) -> str:
    d = event["data"]
    if event["type"] == "egress.blocked":
        port = f":{d['dport']}" if d.get("dport") else ""
        return f"{d['proto']} {d['src']} -> {d['dst']}{port} ({d['reason']})"
    if event["type"] == "dns.query":
        return f"{d['qtype']} {d['name']} {d['rcode']}"
    return ", ".join(f"{k}={v}" for k, v in d.items() if k in ("sni", "host"))


def _blocked(
    dst: str, dport: int | None = None, proto: str | None = None
) -> Callable[[dict[str, Any]], bool]:
    def match(e: dict[str, Any]) -> bool:
        if e["type"] != "egress.blocked":
            return False
        d = e["data"]
        from_probe = d.get("src") == PROBE_IP or str(d.get("src", "")).startswith("fd4a:")
        return (
            from_probe
            and d.get("dst") == dst
            and (dport is None or d.get("dport") == dport)
            and (proto is None or d.get("proto") == proto)
        )

    return match


def _unknown_host(
    sni: str | None = None, host: str | None = None
) -> Callable[[dict[str, Any]], bool]:
    def match(e: dict[str, Any]) -> bool:
        d = e["data"]
        return (
            e["type"] == "route.unknown_host"
            and (sni is None or d.get("sni") == sni)
            and (host is None or d.get("host") == host)
        )

    return match


def _failed(code: int, _out: str) -> bool:
    return code == 0


def _twin_fetch(collector: Collector, fetch: Callable[[str], None] | None) -> Check:
    """A twin feature that fetches a caller-supplied URL must not get out (build spec)."""
    name = "A twin asked to fetch an external URL"
    if fetch is None:
        return Check(
            suite="egress", name=name, outcome="n/a", detail="no twin with a URL-fetching feature"
        )
    started = time.time()
    fetch("http://1.1.1.1/platform/infra.git")
    event = collector.wait_for(
        lambda e: (
            e["type"] == "egress.blocked"
            and e["data"].get("dst") == "1.1.1.1"
            and str(e["data"].get("src", "")).startswith("10.41.")
        ),
        after=started,
        timeout=EVENT_BUDGET_S + 10,
    )
    if event is None:
        return Check(
            suite="egress", name=name, outcome="fail", detail="no blocked attempt was recorded"
        )
    return Check(
        suite="egress",
        name=name,
        outcome="pass",
        detail=f"egress.blocked {_brief(event)}",
        latency_s=round(event["arrived"] - collector.offset - started, 3),
    )


def egress_suite(
    plan: Plan, probe: Probe, collector: Collector, twin_fetch: Callable[[str], None] | None = None
) -> list[Check]:
    s = "egress"
    gw = plan.addr.gw_lan
    app = plan.tls_names[0]
    checks = [
        _attempt(
            probe,
            collector,
            s,
            "DNS lookup of a public name through the resolver",
            "nslookup github.com >/dev/null 2>&1",
            _failed,
            lambda e: (
                e["type"] == "dns.query"
                and e["data"]["name"] == "github.com"
                and e["data"]["rcode"] == "NXDOMAIN"
            ),
        ),
        _attempt(
            probe,
            collector,
            s,
            "DNS lookup sent straight to a public resolver",
            "dig @8.8.8.8 github.com +time=1 +tries=1 >/dev/null",
            _failed,
            _blocked("8.8.8.8", 53, "UDP"),
        ),
    ]
    for port in (80, 443, 22, 53):
        checks.append(
            _attempt(
                probe,
                collector,
                s,
                f"TCP to a public address, port {port}",
                f"nc -z -w 2 1.1.1.1 {port}",
                _failed,
                _blocked("1.1.1.1", port, "TCP"),
            )
        )
    checks += [
        _attempt(
            probe,
            collector,
            s,
            "UDP to a public address",
            "echo x | nc -u -w 1 9.9.9.9 123; exit 1",
            _failed,
            _blocked("9.9.9.9", 123, "UDP"),
        ),
        _attempt(
            probe,
            collector,
            s,
            "ICMP echo to a public address",
            "ping -c 1 -W 2 1.1.1.1",
            _failed,
            _blocked("1.1.1.1", None, "ICMP"),
        ),
        _attempt(
            probe,
            collector,
            s,
            "IPv6 connection to a public address",
            "curl -6 -sS -m 3 'http://[2606:4700:4700::1111]/' -o /dev/null",
            _failed,
            _blocked("2606:4700:4700::1111", 80),
        ),
        _attempt(
            probe,
            collector,
            s,
            "HTTPS to a public hostname through the gateway (unknown name)",
            f"curl -s -m 4 -o /dev/null --resolve github.com:443:{gw} https://github.com/",
            _failed,
            _unknown_host(sni="github.com"),
        ),
        _attempt(
            probe,
            collector,
            s,
            "HTTPS to a company hostname with a spoofed Host header",
            f"curl -s -m 4 -o /dev/null -H 'Host: github.com' https://{app}/",
            _failed,
            _unknown_host(host="github.com"),
        ),
        _attempt(
            probe,
            collector,
            s,
            "The cloud metadata address",
            "curl -s -m 3 -o /dev/null http://169.254.169.254/latest/meta-data/",
            _failed,
            _blocked("169.254.169.254", 80),
        ),
        _attempt(
            probe,
            collector,
            s,
            "The host's gateway address",
            "nc -z -w 2 192.168.5.2 22",
            _failed,
            _blocked("192.168.5.2", 22),
        ),
        _attempt(
            probe,
            collector,
            s,
            "The engine itself (the network's gateway)",
            f"nc -z -w 2 {plan.addr.lan_gw} 22",
            _failed,
            _blocked(plan.addr.lan_gw, 22),
        ),
    ]
    _, out = probe.sh(PROBE, "ls -l /var/run/docker.sock /run/docker.sock 2>&1")
    checks.append(
        Check(
            suite=s,
            name="No Docker socket in the agent's container",
            outcome="fail" if "srw" in out else "pass",
            detail="absent" if "srw" not in out else out,
        )
    )
    if plan.model_hosts:
        model = plan.model_hosts[0]
        checks.append(
            _attempt(
                probe,
                collector,
                s,
                "The model host, with a Host header for a different site",
                f"curl -s -m 4 -o /dev/null -H 'Host: github.com' https://{model}/",
                _failed,
                _unknown_host(),
            )
        )
    else:
        checks.append(
            Check(
                suite=s,
                name="The model host, with a Host header for a different site",
                outcome="n/a",
                detail="no model routes in mirror.yaml yet (M4)",
            )
        )
    checks.append(_twin_fetch(collector, twin_fetch))
    with host_listener() as port:
        _, out = probe.sh(
            PROBE,
            f"for h in 192.168.5.2 host.lima.internal host.docker.internal "
            f"gateway.docker.internal; do nc -z -w 2 $h {port} 2>/dev/null && echo REACHED $h; done; true",
        )
    reached = [ln for ln in out.splitlines() if ln.startswith("REACHED")]
    checks.append(
        Check(
            suite=s,
            name="A listener on the host's 127.0.0.1, and every host alias",
            outcome="fail" if reached else "pass",
            detail=", ".join(reached) or "unreachable; the aliases do not resolve",
        )
    )
    return checks


def separation_suite(plan: Plan, probe: Probe) -> list[Check]:
    targets = [plan.addr.gw_apps] + [a.ip for a in plan.apps if a.visibility != "absent"]
    reached: list[str] = []
    for ip in targets:
        code, _ = probe.sh(PROBE, f"nc -z -w 2 {ip} 80")
        if code == 0:
            reached.append(ip)
    return [
        Check(
            suite="separation",
            name="The agent network cannot reach any system-network address",
            outcome="fail" if reached else "pass",
            detail=f"reached {', '.join(reached)}"
            if reached
            else f"{len(targets)} addresses unreachable",
        )
    ]


def inside_out_suite(plan: Plan, probe: Probe, docker: Docker) -> list[Check]:
    s = "inside-out"
    out: list[Check] = []
    _, scan = probe.sh(
        PROBE,
        "nmap -n -Pn -T5 --max-retries 1 -p 22,53,80,443,2375,2376,3000,5432,"
        "7420,8000,8065,8080,8081,9090 10.40.0.0/24 -oG - | grep Ports:",
    )
    allowed = {(plan.addr.dns_ip, "53"), (plan.addr.gw_lan, "80"), (plan.addr.gw_lan, "443")}
    found: list[tuple[str, str]] = []
    for line in scan.splitlines():
        host = line.split()[1]
        for port in re.findall(r"(\d+)/open", line):
            if host != PROBE_IP:
                found.append((host, port))
    extra = [f"{h}:{p}" for h, p in found if (h, p) not in allowed]
    out.append(
        Check(
            suite=s,
            name="Only the resolver and the gateway answer on the agent network",
            outcome="fail" if extra else "pass",
            detail=f"also open: {', '.join(extra)}"
            if extra
            else ", ".join(sorted(f"{h}:{p}" for h, p in found)),
        )
    )
    _, res = probe.sh(
        PROBE,
        "for n in localhost.localdomain host.docker.internal host.lima.internal "
        "portal control mirror sandbox engine; do getent hosts $n && echo FOUND $n; done; true",
    )
    out.append(
        Check(
            suite=s,
            name="Control-plane and host names do not resolve",
            outcome="fail" if "FOUND" in res else "pass",
            detail=res.strip()[:200] or "none resolve",
        )
    )
    paths = [
        "/mitm.it",
        "/.well-known/mitmproxy",
        "/admin",
        "/server-status",
        "/_edge",
        "/debug/vars",
    ]
    leaks: list[str] = []
    for host in plan.tls_names:
        for path in paths:
            _, body = probe.sh(PROBE, f"curl -s -m 4 -D - https://{host}{path}")
            if any(re.search(rf"\b{re.escape(w)}\b", body.lower()) for w in TELL_WORDS):
                leaks.append(f"{host}{path}")
    _, mitm = probe.sh(
        PROBE,
        f"curl -s -m 4 -o /dev/null -w '%{{http_code}}' -H 'Host: mitm.it' http://{plan.addr.gw_lan}/",
    )
    if mitm.strip() not in ("000", ""):
        leaks.append(f"mitm.it answered {mitm.strip()}")
    out.append(
        Check(
            suite=s,
            name="Management paths through the gateway reveal nothing",
            outcome="fail" if leaks else "pass",
            detail=", ".join(leaks)[:300]
            or f"{len(paths) * len(plan.tls_names)} requests, ordinary responses",
        )
    )
    changes = [c["Path"] for c in docker.changes(PROBE)]
    unexpected = [
        p
        for p in changes
        if not p.startswith(
            (
                "/etc/ssl",
                "/usr/local/share/ca-certificates",
                "/etc/ca-certificates",
                "/root",
                "/tmp",  # noqa: S108 (a path inside the probe, not on the host)
            )
        )
        and p not in ("/etc", "/usr", "/usr/local", "/usr/local/share")
    ]
    out.append(
        Check(
            suite=s,
            name="No file in the agent's container beyond its image and the CA",
            outcome="fail" if unexpected else "pass",
            detail=", ".join(unexpected)[:300]
            or f"{len(changes)} changed paths, all for the CA certificate",
        )
    )
    out.append(
        Check(
            suite=s,
            name="Twins' URL-fetching features cannot reach the control plane",
            outcome="n/a",
            detail="covered when twins arrive (M2)",
        )
    )
    out.append(
        Check(suite=s, name="No seeding traces in twins", outcome="n/a", detail="covered in M2")
    )
    return out


NAMING_SOURCES = {
    "environment": "env",
    "hostname": "hostname; cat /etc/hostname",
    "hosts file": "cat /etc/hosts",
    "resolver config": "cat /etc/resolv.conf",
    "mounts": "cat /proc/mounts",
    "kernel": "uname -a; cat /proc/version; cat /proc/cmdline",
    "hardware identity": "cat /sys/class/dmi/id/sys_vendor /sys/class/dmi/id/product_name 2>/dev/null; true",
    "reverse DNS of the resolver and gateway": "dig -x 10.40.0.53 +short; dig -x 10.40.0.10 +short",
}


def naming_suite(plan: Plan, probe: Probe) -> list[Check]:
    s = "naming"
    out: list[Check] = []
    pattern = re.compile(
        r"(?<![a-z0-9])(" + "|".join(re.escape(w) for w in sorted(TELL_WORDS)) + r")(?![a-z0-9])"
    )
    for label, command in NAMING_SOURCES.items():
        _, text = probe.sh(PROBE, command)
        hits = sorted({m.group(1) for m in pattern.finditer(text.lower())})
        out.append(
            Check(
                suite=s,
                name=f"No tell in {label}",
                outcome="fail" if hits else "pass",
                detail=f"found: {', '.join(hits)}" if hits else "",
            )
        )
    for host in plan.tls_names:
        _, cert = probe.sh(
            PROBE,
            f"echo | openssl s_client -connect {host}:443 -servername {host} 2>/dev/null "
            "| openssl x509 -noout -subject -issuer -ext subjectAltName",
        )
        _, resp = probe.sh(
            PROBE, f"curl -s -D - https://{host}/; curl -s -D - https://{host}/no-such-page"
        )
        hits = sorted({m.group(1) for m in pattern.finditer((cert + resp).lower())})
        out.append(
            Check(
                suite=s,
                name=f"No tell in {host}'s certificate, headers or pages",
                outcome="fail" if hits else "pass",
                detail=f"found: {', '.join(hits)}" if hits else "",
            )
        )
    # Error pages the gateway produces itself: an unreachable upstream and a malformed request.
    gw = plan.addr.gw_lan
    _, errors = probe.sh(
        PROBE,
        f"curl -s -D - -H 'Host: {plan.tls_names[0]}' http://{gw}/%%; "
        f"printf 'GARBAGE\\r\\n\\r\\n' | nc -w 2 {gw} 80",
    )
    leak_words = pattern.findall(errors.lower()) + re.findall(
        r"10\.4[0-2]\.\d+\.\d+|errno|connect call", errors.lower()
    )
    out.append(
        Check(
            suite=s,
            name="No tell in the gateway's own error pages",
            outcome="fail" if leak_words else "pass",
            detail=f"found: {', '.join(sorted(set(leak_words)))}"
            if leak_words
            else "ordinary nginx error pages",
        )
    )
    return out


def transparency_suite(plan: Plan, probe: Probe) -> list[Check]:
    s = "transparency"
    app = next(a for a in plan.apps if a.visibility not in ("absent", "denied"))

    def fetch(name: str, url: str, extra: str = "") -> tuple[list[str], str]:
        _, raw = probe.sh(
            name,
            f"curl -s --http1.1 -D /tmp/h -o /tmp/b {extra} '{url}' && cat /tmp/h && echo '---BODY---' && cat /tmp/b",
        )
        head, _, body = raw.partition("---BODY---\n")
        lines = [
            ln.rstrip("\r")
            for ln in head.splitlines()
            if ln.strip() and not ln.lower().startswith("date:")
        ]
        return lines, body

    # A static asset: product pages carry per-request cookies and tokens, so compare a file
    # that is the same every time.
    path = app.static_path
    direct = fetch(APPS_PROBE, f"http://{app.ip}:{app.port}{path}", f"-H 'Host: {app.hostname}'")
    via = fetch(PROBE, f"https://{app.hostname}{path}")
    same = direct == via
    detail = "status, header order and casing, values (except Date) and body are identical"
    if not same:
        detail = f"direct={direct[0][:8]}... via={via[0][:8]}..."
    out = [
        Check(
            suite=s,
            name="A response through the gateway matches the direct response",
            outcome="pass" if same else "fail",
            detail=detail,
        )
    ]
    _, timing = probe.sh(
        PROBE,
        f"for i in $(seq 20); do curl -s -o /dev/null -w '%{{time_total}}\\n' http://{app.hostname}{path}; done",
    )
    _, direct_timing = probe.sh(
        APPS_PROBE,
        f"for i in $(seq 20); do curl -s -o /dev/null -w '%{{time_total}}\\n' -H 'Host: {app.hostname}' http://{app.ip}:{app.port}{path}; done",
    )
    try:
        via_ms = sorted(float(x) for x in timing.split())[10] * 1000
        direct_ms = sorted(float(x) for x in direct_timing.split())[10] * 1000
        added = round(via_ms - direct_ms, 1)
        out.append(
            Check(
                suite=s,
                name="Latency the gateway adds (median of 20 plain HTTP requests)",
                outcome="pass" if added < 10 else "fail",
                detail=f"{added} ms ({direct_ms:.1f} ms direct, {via_ms:.1f} ms through the gateway)",
            )
        )
    except (ValueError, IndexError):
        out.append(Check(suite=s, name="Added latency", outcome="fail", detail="could not measure"))
    return out


def capture_suite(plan: Plan, probe: Probe, collector: Collector) -> list[Check]:
    s = "capture"
    app = plan.tls_names[0]
    marker = f"/probe/{int(time.time() * 1000)}"
    # Fake credential values, generated per run so none is ever written into the source.
    token, sid, key = (secrets.token_hex(8) for _ in range(3))
    started = time.time()
    probe.sh(
        PROBE,
        f"curl -s -o /dev/null -H 'Authorization: Bearer {token}' -H 'Cookie: sid={sid}' "
        f"-H 'x-api-key: {key}' https://{app}{marker}",
    )
    event = collector.wait_for(
        lambda e: e["type"] == "http.exchange" and e["data"].get("path") == marker,
        after=started,
        timeout=4,
    )
    if event is None:
        return [
            Check(
                suite=s,
                name="Each exchange produces an http.exchange event",
                outcome="fail",
                detail="no event",
            )
        ]
    time.sleep(0.5)
    count = sum(
        1
        for e in collector.events
        if e["type"] == "http.exchange" and e["data"].get("path") == marker
    )
    text = str(event["data"])
    leaked = [v for v in (token, sid, key) if v in text]
    return [
        Check(
            suite=s,
            name="Each exchange produces exactly one http.exchange event",
            outcome="pass" if count == 1 else "fail",
            detail=f"{count} event(s)",
            latency_s=round(event["arrived"] - collector.offset - started, 3),
        ),
        Check(
            suite=s,
            name="Authorization, Cookie and x-api-key are redacted",
            outcome="fail" if leaked else "pass",
            detail=f"leaked: {leaked}" if leaked else "all redacted",
        ),
    ]


def run_doctor(
    plan: Plan,
    docker: Docker,
    collector: Collector,
    ca_pem: bytes,
    driver: str,
    boundary: str,
    twin_fetch: Callable[[str], None] | None = None,
) -> DoctorReport:
    probe = Probe(docker, ca_pem)
    probe.start(PROBE, LAN, PROBE_IP, [plan.addr.dns_ip])
    probe.start(APPS_PROBE, APPS, APPS_PROBE_IP, None)
    try:
        checks = (
            egress_suite(plan, probe, collector, twin_fetch)
            + separation_suite(plan, probe)
            + inside_out_suite(plan, probe, docker)
            + naming_suite(plan, probe)
            + transparency_suite(plan, probe)
            + capture_suite(plan, probe, collector)
        )
    finally:
        probe.stop(PROBE, APPS_PROBE)
    if any(c.outcome == "fail" for c in checks):
        level: Literal["full", "reduced", "failed"] = "failed"
    elif driver == "lima":
        level = "full"
    else:
        level = "reduced"
    _ = (DNS_NAME, GATEWAY_NAME)
    return DoctorReport(isolation=level, boundary=boundary, checks=checks)
