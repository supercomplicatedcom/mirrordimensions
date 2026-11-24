# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Turn the sandbox's three logs into events, and collect them on the host.

| Source container | What it writes                    | Event                                   |
| ---------------- | --------------------------------- | --------------------------------------- |
| edge-proxy-02    | JSON lines from the add-on        | http.exchange, route.unknown_host       |
| ns1              | one CoreDNS log line per query    | dns.query                               |
| klog             | the engine kernel's log           | egress.blocked (edge firewall drops)    |
| browser observer | JSON lines (decision 0014)        | browser.action, browser.navigate,       |
|                  |                                   | browser.screenshot, browser.connect     |

Lines arrive through the Docker API (decision 0003). Timestamps are taken on the host when
a line arrives, corrected by the engine's clock offset, so "within one second" is measured
the way an operator would see it.
"""

from __future__ import annotations

import base64
import json
import re
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from mirrordimensions.engine.docker_api import Docker
from mirrordimensions.hostos.files import make_dir

_KMSG = re.compile(r"edge-drop (?P<kind>egress|host|engine) (?P<fields>.*)$")
_FIELD = re.compile(r"(?P<key>[A-Z]+)=(?P<value>\S*)")
_DNS = re.compile(r"\] q (?P<rcode>\S+) (?P<qtype>\S+) (?P<name>\S+) (?P<client>\S+)")


def parse_gateway(line: str) -> dict[str, Any] | None:
    try:
        raw = json.loads(line)
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    item = cast(dict[str, Any], raw)
    if item.get("source") != "gateway":
        return None
    return {"source": "gateway", "type": item["type"], "data": item.get("data", {})}


BROWSER_TYPES = frozenset(
    {
        "browser.action",
        "browser.navigate",
        "browser.screenshot",
        "browser.connect",
        "browser.disconnect",
        "browser.target",
        "browser.observer_ready",
        "browser.observer_error",
    }
)


def browser_parser(shots: Path) -> Callable[[str], dict[str, Any] | None]:
    """Events from a browser observer. Screenshots are written to `shots` and the event
    keeps the file name, so the timeline stays small."""
    counter = [0]

    def parse(line: str) -> dict[str, Any] | None:
        try:
            raw = json.loads(line)
        except ValueError:
            return None
        if not isinstance(raw, dict):
            return None
        item = cast(dict[str, Any], raw)
        kind = item.get("type")
        if item.get("source") != "browser" or kind not in BROWSER_TYPES:
            return None
        data = cast(dict[str, Any], item.get("data") or {})
        if kind == "browser.screenshot":
            image = str(data.pop("jpeg", ""))
            counter[0] += 1
            name = f"shot-{counter[0]:04d}.jpg"
            make_dir(shots, owner_only=True)
            try:
                (shots / name).write_bytes(base64.b64decode(image, validate=True))
            except (ValueError, OSError):
                return None
            data["file"] = name
        return {"source": "browser", "type": kind, "data": data}

    return parse


def parse_dns(line: str) -> dict[str, Any] | None:
    match = _DNS.search(line)
    if not match:
        return None
    client = (
        match["client"].rsplit(":", 1)[0] if match["client"].count(":") == 1 else match["client"]
    )
    return {
        "source": "dns",
        "type": "dns.query",
        "data": {
            "name": match["name"].rstrip("."),
            "qtype": match["qtype"],
            "rcode": match["rcode"],
            "client": client,
        },
    }


def parse_kmsg(line: str, bridges: dict[str, str]) -> dict[str, Any] | None:
    """An edge-firewall drop on one of this world's bridges, or None."""
    match = _KMSG.search(line)
    if not match:
        return None
    fields = {m["key"]: m["value"] for m in _FIELD.finditer(match["fields"])}
    network = bridges.get(fields.get("IN", ""))
    if network is None:
        return None
    data: dict[str, Any] = {
        "network": network,
        "src": _ipv6_compact(fields.get("SRC", "")),
        "dst": _ipv6_compact(fields.get("DST", "")),
        "proto": fields.get("PROTO", ""),
        "dport": int(fields["DPT"]) if fields.get("DPT", "").isdigit() else None,
        "reason": {"egress": "outside", "host": "host", "engine": "engine"}[match["kind"]],
    }
    if data["proto"] == "ICMP" and "TYPE" in fields:
        data["icmp_type"] = int(fields["TYPE"])
    return {"source": "egress", "type": "egress.blocked", "data": data}


def _ipv6_compact(addr: str) -> str:
    if ":" not in addr:
        return addr
    import ipaddress

    try:
        return str(ipaddress.ip_address(addr))
    except ValueError:
        return addr


class Collector:
    """Follows the sandbox's logs and keeps the events in order, in memory and on disk."""

    def __init__(
        self,
        docker: Docker,
        out: Path,
        bridges: dict[str, str],
        clock_offset_s: float = 0.0,
        names: tuple[str, ...] = ("edge-proxy-02", "ns1", "klog", "ns2"),
    ) -> None:
        self.docker = docker
        self.out = out
        self.bridges = bridges
        self.offset = clock_offset_s
        self.names = names
        self.events: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        make_dir(self.out.parent, owner_only=True)
        since = int(time.time() + self.offset)
        gateway, dns, relay, *more = self.names
        parsers: list[tuple[str, Callable[[str], dict[str, Any] | None]]] = [
            (gateway, parse_gateway),
            (dns, parse_dns),
            (relay, lambda line: parse_kmsg(line, self.bridges)),
            *((name, parse_dns) for name in more),
        ]
        for name, parser in parsers:
            thread = threading.Thread(target=self._follow, args=(name, parser, since), daemon=True)
            thread.start()
            self._threads.append(thread)

    def add_source(self, name: str, parser: Callable[[str], dict[str, Any] | None]) -> None:
        """Follow one more container, such as a browser observer started for a run."""
        since = int(time.time() + self.offset) - 1
        thread = threading.Thread(target=self._follow, args=(name, parser, since), daemon=True)
        thread.start()
        self._threads.append(thread)

    def _follow(
        self, name: str, parser: Callable[[str], dict[str, Any] | None], since: int
    ) -> None:
        for line in self.docker.follow(name, since=since):
            event = parser(line)
            if event is None:
                continue
            arrived = time.time() + self.offset
            with self._cond:
                event["seq"] = len(self.events) + 1
                event["ts"] = (
                    datetime.fromtimestamp(arrived, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
                )
                event["arrived"] = arrived
                self.events.append(event)
                with self.out.open("a", encoding="utf-8", newline="\n") as handle:
                    record = {k: v for k, v in event.items() if k != "arrived"}
                    handle.write(json.dumps(record) + "\n")
                self._cond.notify_all()

    def wait_for(
        self, match: Callable[[dict[str, Any]], bool], after: float, timeout: float
    ) -> dict[str, Any] | None:
        """The first event arriving after `after` (host time) that matches, or None."""
        deadline = time.time() + timeout
        with self._cond:
            while True:
                for event in self.events:
                    if event["arrived"] - self.offset >= after and match(event):
                        return event
                remaining = deadline - time.time()
                if remaining <= 0:
                    return None
                self._cond.wait(remaining)
