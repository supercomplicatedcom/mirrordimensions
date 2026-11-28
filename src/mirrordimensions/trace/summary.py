# SPDX-License-Identifier: Apache-2.0
"""One short line per event, for `mirror trace` and the report's timeline."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, cast

from mirrordimensions.trace.timeline import parse_ts

WIDTH = 96


def clip(text: str, width: int = WIDTH) -> str:
    text = re.sub(r"\s*[\r\n\t]+\s*", " ", text)
    return text if len(text) <= width else text[: width - 1] + "…"


def elapsed(event: dict[str, Any], start: datetime | None) -> str:
    """Minutes and seconds since the run started, to a tenth: `01:04.2`."""
    at = parse_ts(event)
    if at is None or start is None:
        return "--:--.-"
    seconds = max(0.0, (at - start).total_seconds())
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes):02d}:{rest:04.1f}"


def _short_host(host: Any) -> str:
    """`git.northfield.com` as `git…`, as in the timeline's design: the app's name is enough
    on one line, and the report shows the full host."""
    text = str(host or "").split(":")[0]
    first, _, rest = text.partition(".")
    return f"{first}…" if rest else text


def _str(value: Any) -> str:
    return "" if value is None else str(value)


def summarize(event: dict[str, Any], *, full_hosts: bool = False) -> str:
    """What happened, in one line without the time or the source."""
    d: dict[str, Any] = event.get("data") or {}
    kind = str(event.get("type", ""))

    def host(h: Any) -> str:
        return _str(h).split(":")[0] if full_hosts else _short_host(h)

    def http(method: Any, h: Any, path: Any, status: Any) -> str:
        return f"{_str(method):<6} {host(h)}{_str(path)}  {_str(status)}".rstrip()

    match kind:
        case "run.start":
            line = f"run started: {d.get('scenario')} by {d.get('agent')} as {d.get('acts_as')}"
        case "snapshot.restored":
            line = f"snapshot {d.get('snapshot')} restored in {d.get('seconds')} s"
        case "overlay.applied":
            line = f"scenario overlay applied: {d.get('operation')}"
        case "work.delivered":
            line = f"work delivered: {d.get('channel')} from {d.get('from')} to {d.get('to')}"
            if d.get("url"):
                line += f" ({d['url']})"
        case "agent.woken":
            command = d.get("command")
            shown = (
                " ".join(str(c) for c in cast(list[Any], command))
                if isinstance(command, list)
                else _str(command)
            )
            line = f"agent woken: {shown}"
        case "run.end":
            line = f"run ended: {d.get('status')}"
        case "http.exchange":
            line = http(d.get("method"), d.get("host"), d.get("path"), d.get("status"))
        case "ws.frame":
            arrow = "→" if d.get("direction") == "client" else "←"
            line = (
                f"WS {arrow}  {host(d.get('host'))}{_str(d.get('path'))}  {d.get('length')} bytes"
            )
        case "tls.handshake":
            line = f"TLS {d.get('sni') or d.get('host')}"
        case "route.unknown_host":
            line = f"unknown host {d.get('host')} (SNI {d.get('sni')}) from {d.get('client')}"
        case "rule.applied":
            line = f"rule {d.get('rule')} on {host(d.get('host'))}{_str(d.get('path'))}"
        case "model.exchange":
            tokens = ""
            if "input_tokens" in d or "output_tokens" in d:
                tokens = f", {d.get('input_tokens', '?')} in / {d.get('output_tokens', '?')} out"
            stream = ", streamed" if d.get("streamed") else ""
            line = (
                f"{d.get('model') or 'model'} via {d.get('route')}: {d.get('status')}"
                f"{tokens}{stream}, {d.get('duration_ms')} ms"
            )
        case "model.refused":
            line = f"model call refused: {d.get('path')} ({d.get('reason')})"
        case "model.hosted_tools":
            line = f"hosted tools {d.get('action')}: {', '.join(map(str, d.get('tools') or []))}"
        case "mcp.call":
            error = " error" if d.get("is_error") else ""
            line = f"tool {d.get('tool')} ({d.get('access')}){error}: {_str(d.get('arguments'))}"
        case "mcp.message":
            line = (
                f"{d.get('direction')} {d.get('kind')} {_str(d.get('method'))} "
                f"(exchange {d.get('exchange')})"
            )
        case "dns.query":
            line = f"{d.get('qtype')} {d.get('name')}  {d.get('rcode')}  from {d.get('client')}"
        case "egress.blocked":
            port = f":{d['dport']}" if d.get("dport") is not None else ""
            line = (
                f"blocked {d.get('proto')} {d.get('src')} → {d.get('dst')}{port} "
                f"({d.get('reason')}, {d.get('network')})"
            )
        case "browser.navigate":
            line = f"navigate {d.get('url')}"
        case "browser.action":
            line = f"{d.get('kind', 'action')} {_str(d.get('method'))} {_params(d.get('params'))}"
        case "browser.screenshot":
            line = f"screenshot {d.get('file')} of {d.get('url')}"
        case "browser.connect":
            line = f"browser connection {d.get('conn')} from {d.get('client')}: {d.get('path')}"
        case "process.exec":
            line = f"exec {d.get('binary')} {_str(d.get('arguments'))}"
        case "socket.connect":
            line = (
                f"{d.get('proto')} to {d.get('dst')}:{d.get('dport')} by {d.get('binary')} "
                f"(pid {d.get('pid')})"
            )
        case "state.diff":
            line = f"{d.get('system')}: {d.get('changed')} object(s) changed"
        case "check.result":
            verdict = "passed" if d.get("passed") else "FAILED"
            line = f"{d.get('kind')} check {d.get('check')} {verdict}"
            if d.get("evidence"):
                line += f": {d['evidence']}"
        case "side_effect.unexpected":
            line = f"unexpected change: {d.get('system')} {d.get('object')} {d.get('change')}"
        case "suspicion.flag":
            line = f'suspicion: "{d.get("phrase")}" (event {d.get("event")})'
        case _:
            shown = {k: v for k, v in d.items() if k != "gateway_seq"}
            line = f"{kind} {json.dumps(shown, sort_keys=True)}"
    return clip(line)


def _params(params: Any) -> str:
    if not params:
        return ""
    return json.dumps(params, sort_keys=True) if not isinstance(params, str) else params
