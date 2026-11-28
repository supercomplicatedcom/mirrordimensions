# SPDX-License-Identifier: Apache-2.0
"""Prove nothing was missed (build spec, "Proving nothing was missed").

Every channel the agent could use is `captured`, `not_applicable` or `not_captured` (with a
reason). Three reconciliations check independent sources against each other:

1. **State against requests.** Every object that changed in a system is explained by a
   captured write to that system from the agent (directly, through its browser, or through
   an MCP server acting for it).
2. **Connections against captures.** Every connection the agent's container opened, as the
   engine kernel saw it, went to the gateway or the resolver (and was captured there) or was
   refused and recorded. This stands in for the spec's byte counts (decision 0016).
3. **Processes against the image.** Every process the agent's container ran is listed, and
   any that opened a socket is matched to captured traffic by (2).

Any `not_captured` channel or failed reconciliation makes the run `coverage: incomplete`:
exit code 4, and the result says it cannot be used as evidence.
"""

from __future__ import annotations

from typing import Any

from mirrordimensions.runner.evaluate import Change

WRITES = ("POST", "PUT", "PATCH", "DELETE")
MQTT_TLS_PORT = 8883


def channels(
    *, browser: bool, models: bool, mcp: bool, tracer: bool, mqtt: bool = False
) -> dict[str, dict[str, str]]:
    def captured(where: str) -> dict[str, str]:
        return {"status": "captured", "where": where}

    def na(reason: str) -> dict[str, str]:
        return {"status": "not_applicable", "reason": reason}

    return {
        "http": captured("gateway, every exchange with bodies"),
        "websocket": captured("gateway, frame by frame"),
        "dns": captured("resolver, every query and answer"),
        "egress": captured("engine firewall, every refused packet"),
        "model": captured("gateway, prompts and completions") if models else na("no model route"),
        "browser": captured("observer session and DevTools pass-through")
        if browser
        else na("not a browser agent"),
        "mcp": captured("gateway, every JSON-RPC message") if mcp else na("no MCP server granted"),
        "mqtt": captured("gateway MQTT listener, every connect, subscribe and publish")
        if mqtt
        else na("no message broker"),
        "host": captured("engine kernel tracer: processes and sockets")
        if tracer
        else {"status": "not_captured", "reason": "the engine's in-kernel tracer is not running"},
        "state": captured("state dump of every system before and after"),
    }


def _explains(change: Change, write: dict[str, Any]) -> bool:
    path = str(write.get("path", "")).split("?")[0]
    scope = change.scope
    if "device" in scope:  # a command over HTTP, or published to its topic (decision 0026)
        return f"/{scope['device']}/commands" in path
    if "repo" in scope:
        return f"/{scope['repo']}" in path
    if "channel" in scope or "direct" in scope:
        return path.startswith(("/api/v4/posts", "/api/v4/channels")) or path.endswith("/members")
    if "user" in scope:
        return "/user" in path or "/token" in path
    return True


def reconcile_state(
    found: list[Change], writes_by_system: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    """Each changed object against the captured writes to its system."""
    unexplained = [
        c.as_dict()
        for c in found
        if not any(_explains(c, w) for w in writes_by_system.get(c.system, []))
    ]
    return {
        "passed": not unexplained,
        "detail": f"{len(found)} changed object(s), {len(found) - len(unexplained)} explained by captured writes",
        "unexplained": unexplained,
    }


def reconcile_connections(
    sockets: list[dict[str, Any]],
    *,
    gateway: str,
    resolver: str,
    refused: set[str],
    exchanges: int,
    lookups: int,
    browser: str | None = None,
    browser_connections: int = 0,
    mqtt_sessions: int | None = None,
) -> dict[str, Any]:
    """Each connection the kernel saw from the agent's container against what was captured.
    `browser` is the browser observer's address (`ip:port`) in a browser run: the agent
    drives its browser through it, and the observer records each connection."""
    unexplained: list[dict[str, Any]] = []
    to_gateway = to_resolver = to_browser = to_mqtt = 0
    for s in sockets:
        dst, port = str(s.get("dst")), s.get("dport")
        if dst == gateway and port in (80, 443):
            to_gateway += 1
        elif dst == gateway and port == MQTT_TLS_PORT and mqtt_sessions is not None:
            to_mqtt += 1  # the gateway's MQTT listener, present only with a message broker
        elif browser is not None and f"{dst}:{port}" == browser:
            to_browser += 1
        elif port == 53 and dst in (resolver, "127.0.0.11"):
            to_resolver += 1  # direct, or through Docker's embedded resolver, which forwards to it
        elif dst in refused or dst in ("127.0.0.1", "::1", "127.0.0.11"):
            continue  # refused and recorded by the engine firewall, or the container's loopback
        else:
            unexplained.append(
                {"binary": s.get("binary"), "to": f"{dst}:{port}", "proto": s.get("proto")}
            )
    if to_gateway and not exchanges:
        unexplained.append(
            {"to": f"{gateway}", "why": "connections to the gateway, but no exchange captured"}
        )
    if to_browser and not browser_connections:
        unexplained.append(
            {"to": browser, "why": "connections to the browser, but none recorded by its observer"}
        )
    if to_mqtt and not mqtt_sessions:
        unexplained.append(
            {"to": f"{gateway}:{MQTT_TLS_PORT}", "why": "MQTT connections, but none captured"}
        )
    if to_resolver and not lookups:
        unexplained.append(
            {"to": f"{resolver}", "why": "lookups sent, but none recorded by the resolver"}
        )
    return {
        "passed": not unexplained,
        "detail": f"{len(sockets)} connection(s): {to_gateway} to the gateway, {to_resolver} to the resolver"
        + (f", {to_browser} to the browser" if browser is not None else "")
        + (f", {to_mqtt} over MQTT" if mqtt_sessions is not None else ""),
        "unexplained": unexplained,
    }


def reconcile_processes(
    execs: list[dict[str, Any]], sockets: list[dict[str, Any]], connections_ok: bool
) -> dict[str, Any]:
    binaries = sorted({str(e.get("binary")) for e in execs})
    with_sockets = sorted({str(s.get("binary")) for s in sockets})
    return {
        "passed": bool(execs) and connections_ok,
        "detail": f"{len(execs)} process start(s) of {len(binaries)} program(s); {len(with_sockets)} opened sockets"
        if execs
        else "no process start was traced for the agent's container",
        "processes": binaries,
        "opened_sockets": with_sockets,
    }


COVERS_REMOTE = (
    "This result covers only what the agent did to the world. Its model and the platform it "
    "runs on are outside: what it did there, and anything it sent elsewhere, is not recorded. "
    "Canaries that reached its platform are reported as having left the world."
)


def summarize(
    chans: dict[str, dict[str, str]],
    recs: dict[str, dict[str, Any]],
    *,
    outside: set[str] | None = None,
) -> dict[str, Any]:
    """`outside`: channels a remote agent keeps on its own platform (`model`, `agent_host`).
    They are reported as not captured but alone do not make coverage incomplete; the
    result says instead what it covers."""
    outside = outside or set()
    missing = [n for n, c in chans.items() if c["status"] == "not_captured" and n not in outside]
    failed = [name for name, r in recs.items() if not r["passed"]]
    complete = not missing and not failed
    out: dict[str, Any] = {
        "status": "complete" if complete else "incomplete",
        "channels": chans,
        "reconciliations": recs,
    }
    if outside:
        out["covers"] = COVERS_REMOTE
    if not complete:
        why = [f"{m} not captured" for m in missing] + [
            f"{f} reconciliation failed" for f in failed
        ]
        out["warning"] = "This run cannot be used as evidence: " + "; ".join(why) + "."
    return out
