# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The device platform: a building-access service that fronts a company's doors, climate
units, sensors and cameras with a REST API (decision 0026).

Standard library only, beside `sim.py`; it runs inside the world on the system network and
is reached through the gateway like every system. Each command is written to stdout as one
JSON line, which the control plane collects and replays.
"""

# JSON from the platform and its configuration is untyped.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sys
import threading
import time
import urllib.parse
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

try:  # on the host (tests): the package; in the world: the file beside this one
    from mirrordimensions.devices.world.sim import Simulator
except ImportError:  # pragma: no cover
    sys.path.insert(0, "/opt/platform")
    from sim import Simulator  # pyright: ignore[reportMissingImports]

PORT = 8080
CONFIG = "/etc/platform/config.json"
RANKS = {"viewer": 1, "operator": 2, "security": 3}
HISTORY_S = 7 * 86400.0  # how far back the access log reaches


class Platform:
    """The platform's state: configuration, people with access, and the simulator."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.sites: list[dict[str, Any]] = config["sites"]
        self.devices: dict[str, dict[str, Any]] = {d["id"]: d for d in config["devices"]}
        self.epoch = time.time()
        self.clock = {"epoch": self.epoch, "offsets": dict(config.get("offsets") or {})}
        self.people: list[dict[str, Any]] = list(config.get("people") or [])
        self.sim = Simulator(
            config["devices"], config["types"], int(config["seed"]), self.people, self.clock
        )
        self.lock = threading.Lock()
        self.users: dict[str, dict[str, Any]] = {}  # token digest -> user
        self.audit: list[dict[str, Any]] = []
        self.denied: list[dict[str, Any]] = []  # attempts refused for lack of access
        self.attempts = 0  # every command attempt is numbered in the order it arrived
        self.seq = 0
        self.emit("device.started", {"epoch": self.epoch, "devices": sorted(self.devices)})

    def now(self) -> float:
        return round(time.time() - self.epoch, 3)

    def iso(self, t: float) -> str:
        return (
            datetime.fromtimestamp(self.epoch + t, UTC)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )

    def emit(self, kind: str, data: dict[str, Any]) -> None:
        self.seq += 1
        line = {"seq": self.seq, "ts": time.time(), "source": "device", "type": kind, "data": data}
        sys.stdout.write(json.dumps(line, separators=(",", ":")) + "\n")
        sys.stdout.flush()

    def access_log(self, t: float) -> list[dict[str, Any]]:
        """Badges and camera motion over the past week, and every command people sent, in
        time order: what a building's access log holds."""
        found: list[tuple[float, dict[str, Any]]] = []
        for e in self.sim.access_log(-HISTORY_S, t):
            entry: dict[str, Any] = {
                "time": self.iso(e["t"]),
                "type": e["type"],
                "device": e["device"],
            }
            if e["type"] == "motion.detected":
                entry["badge_match"] = e["badge_match"]
            else:
                entry |= {"actor": e["name"], "badge": e["badge"], "method": "badge"}
                if "reason" in e:
                    entry["reason"] = e["reason"]
            found.append((e["t"], entry))
        found += [(_t(self, e["time"]), e) for e in self.audit]
        return [e for _, e in sorted(found, key=lambda x: x[0])]

    def badges(self, t: float) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for person in sorted(self.people, key=lambda x: x["badge"]):
            left = None if person.get("left_ago") is None else -60.0 * float(person["left_ago"])
            disabled = left is not None and left <= t
            out.append(
                {
                    "number": person["badge"],
                    "holder": person["name"],
                    "username": person["username"],
                    "site": person["site"],
                    "access": "restricted" if person.get("restricted") else "general",
                    "status": "disabled" if disabled else "active",
                    **({"disabled_at": self.iso(left)} if disabled and left is not None else {}),
                }
            )
        return out

    def user(self, header: str | None) -> dict[str, Any] | None:
        if not header or not header.lower().startswith("bearer "):
            return None
        digest = hashlib.sha256(header[7:].strip().encode()).hexdigest()
        return self.users.get(digest)

    def admin(self, header: str | None) -> bool:
        token = str(self.config["admin_token"])
        given = (header or "")[7:].strip() if (header or "").lower().startswith("bearer ") else ""
        return bool(given) and hmac.compare_digest(given, token)

    def rank(self, user: dict[str, Any], site: str) -> int:
        return RANKS.get(str(user["sites"].get(site, "")), 0)

    def visible(self, user: dict[str, Any], device: dict[str, Any]) -> bool:
        return self.rank(user, device["at"].split("/")[0]) > 0

    def describe(self, device: dict[str, Any], t: float, full: bool) -> dict[str, Any]:
        spec = self.config["types"][device["type"]]
        site, floor, room = ([*device["at"].split("/"), "", ""])[:3]
        out: dict[str, Any] = {
            "id": device["id"],
            "name": device["id"].replace("-", " ").capitalize(),
            "type": device["type"],
            "model": spec.get("label", device["type"]),
            "site": site,
            "floor": floor or None,
            "room": room or None,
            "zone": "restricted" if device.get("sensitivity") == "restricted" else "general",
            "online": self.sim.online(device["id"], t),
        }
        if full:
            out["state"] = self.sim.read(device["id"], t)
            out["commands"] = sorted(spec.get("commands", {}))
            out["last_seen"] = self.iso(
                t if out["online"] else _last_online(self.sim, device["id"], t)
            )
        return out


def _t(p: Platform, iso: str) -> float:
    """An access-log time back as t, for ordering."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() - p.epoch


def _last_online(sim: Simulator, device: str, t: float) -> float:
    while t > 0 and not sim.online(device, t):
        t -= 1
    return max(t, 0.0)


def _uuid(seed: int, *parts: object) -> str:
    h = hashlib.sha256(":".join([str(seed), *map(str, parts)]).encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-4{h[13:16]}-a{h[17:20]}-{h[20:32]}"


class Handler(BaseHTTPRequestHandler):
    server_version = "nginx"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    platform: Platform

    def version_string(self) -> str:
        return self.server_version

    def log_message(self, format: str, *args: Any) -> None:
        return  # the gateway captures every exchange

    def _send(self, status: int, body: Any) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Request-Id", secrets.token_hex(8))
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _error(self, status: int, code: str, message: str) -> None:
        self._send(status, {"error": code, "message": message})

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            data = json.loads(self.rfile.read(length))
        except ValueError:
            return {"__invalid__": True}
        return data if isinstance(data, dict) else {"__invalid__": True}

    def do_GET(self) -> None:
        self._route("GET")

    def do_POST(self) -> None:
        self._route("POST")

    def _route(self, method: str) -> None:
        p = self.platform
        url = urllib.parse.urlsplit(self.path)
        parts = [x for x in url.path.split("/") if x]
        query = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        if parts == ["healthz"]:
            self._send(200, {"status": "ok"})
            return
        if parts[:3] == ["api", "v1", "admin"]:
            self._admin(method, parts[3:])
            return
        if parts[:2] != ["api", "v1"]:
            self._error(404, "not_found", "No such resource.")
            return
        user = p.user(self.headers.get("Authorization"))
        if user is None:
            self._error(401, "unauthorized", "A valid access token is required.")
            return
        rest = parts[2:]
        with p.lock:
            t = p.now()
            if method == "GET" and rest == ["me"]:
                self._send(200, {k: user[k] for k in ("id", "username", "name", "email", "sites")})
            elif method == "GET" and rest == ["sites"]:
                self._send(200, [s for s in p.sites if p.rank(user, s["id"])])
            elif method == "GET" and len(rest) == 2 and rest[0] == "sites":
                site = next(
                    (s for s in p.sites if s["id"] == rest[1] and p.rank(user, s["id"])), None
                )
                if site is None:
                    self._error(404, "not_found", "No such site.")
                else:
                    self._send(200, site)
            elif method == "GET" and rest == ["devices"]:
                found = [
                    p.describe(d, t, full=False)
                    for d in p.devices.values()
                    if p.visible(user, d)
                    and all(
                        str(p.describe(d, t, full=False).get(k)) == v
                        for k, v in query.items()
                        if k in ("site", "floor", "room", "type", "zone")
                    )
                ]
                self._send(200, found)
            elif method == "GET" and rest == ["events"]:
                device = query.get("device")
                self._send(
                    200,
                    [
                        e
                        for e in p.access_log(t)
                        if (device is None or e["device"] == device)
                        and p.visible(user, p.devices[e["device"]])
                    ][-200:],
                )
            elif method == "GET" and rest == ["badges"]:
                self._send(200, [b for b in p.badges(t) if p.rank(user, b["site"])])
            elif len(rest) >= 2 and rest[0] == "devices":
                self._device(method, user, rest[1], rest[2:], query, t)
            else:
                self._error(404, "not_found", "No such resource.")

    def _device(
        self,
        method: str,
        user: dict[str, Any],
        device_id: str,
        rest: list[str],
        query: dict[str, str],
        t: float,
    ) -> None:
        p = self.platform
        device = p.devices.get(device_id)
        if device is None or not p.visible(user, device):
            self._error(404, "not_found", "No such device.")
            return
        if method == "GET" and not rest:
            self._send(200, p.describe(device, t, full=True))
        elif method == "GET" and rest == ["state"]:
            online = p.sim.online(device_id, t)
            self._send(
                200,
                {
                    "device": device_id,
                    "online": online,
                    "reported_at": p.iso(t if online else _last_online(p.sim, device_id, t)),
                    "properties": p.sim.read(device_id, t),
                },
            )
        elif method == "GET" and rest == ["telemetry"]:
            since, until = max(t - 3600, 0.0), t
            readings = p.sim.telemetry(device_id, since, until)
            self._send(
                200,
                [
                    {"time": p.iso(r["t"]), "property": r["property"], "value": r["value"]}
                    for r in readings
                ],
            )
        elif method == "GET" and rest == ["commands"]:
            self._send(200, [_shown(p, c) for c in p.sim.commands if c["device"] == device_id])
        elif method == "POST" and rest == ["commands"]:
            self._command(user, device, t)
        else:
            self._error(404, "not_found", "No such resource.")

    def _command(self, user: dict[str, Any], device: dict[str, Any], t: float) -> None:
        p = self.platform
        body = self._body()
        name = body.get("command")
        params = body.get("params") or {}
        if body.get("__invalid__") or not isinstance(name, str) or not isinstance(params, dict):
            self._error(400, "invalid_request", 'Send {"command": "<name>", "params": {...}}.')
            return
        needed = "security" if device.get("sensitivity") == "restricted" else "operator"
        if p.rank(user, device["at"].split("/")[0]) < RANKS[needed]:
            self._error(403, "forbidden", "You do not have permission to operate this device.")
            record = {
                "device": device["id"],
                "command": name,
                "params": params,
                "t": t,
                "who": user["username"],
                "status": "denied",
                "error": "forbidden",
                "consequence": p.config["types"][device["type"]]
                .get("commands", {})
                .get(name, {})
                .get("consequence", "observe"),
            }
            p.attempts += 1
            record["attempt"] = p.attempts
            p.denied.append(record)
            p.emit("device.command", record)
            return
        record = p.sim.command(device["id"], name, params, t, user["username"])
        p.attempts += 1
        record["attempt"] = p.attempts
        p.emit("device.command", record)
        if record["status"] == "completed":
            for event in p.config["types"][device["type"]].get("events", []):
                if event["on"] == name:
                    p.audit.append(
                        {
                            "time": p.iso(t),
                            "type": event["emit"],
                            "device": device["id"],
                            "actor": user["name"],
                            "username": user["username"],
                            "method": "remote",
                        }
                    )
            self._send(202, _shown(p, record))
        else:
            status = {"offline": 504, "jammed": 409}.get(record["error"], 400)
            self._send(
                status,
                {
                    "error": record["error"],
                    "message": record["message"],
                    "command": _shown(p, record),
                },
            )

    def _admin(self, method: str, rest: list[str]) -> None:
        p = self.platform
        if not p.admin(self.headers.get("Authorization")):
            self._error(401, "unauthorized", "A valid access token is required.")
            return
        with p.lock:
            if method == "POST" and rest == ["users"]:
                body = self._body()
                token = secrets.token_urlsafe(32)
                user = {
                    "id": _uuid(p.config["seed"], "user", body.get("username")),
                    "username": str(body.get("username", "")),
                    "name": str(body.get("name", "")),
                    "email": str(body.get("email", "")),
                    "sites": {
                        str(k): str(v) for k, v in (body.get("sites") or {}).items() if v in RANKS
                    },
                }
                for digest, existing in list(p.users.items()):
                    if existing["username"] == user["username"]:
                        del p.users[digest]  # a new token replaces the old one
                p.users[hashlib.sha256(token.encode()).hexdigest()] = user
                self._send(201, {**user, "token": token})
            elif method == "GET" and rest == ["export"]:
                t = p.now()
                attempts = sorted(p.sim.commands + p.denied, key=lambda c: c["attempt"])
                self._send(
                    200,
                    {
                        "t": t,
                        "clock": p.clock,
                        "devices": p.sim.snapshot(t),
                        "commands": attempts,
                    },
                )
            else:
                self._error(404, "not_found", "No such resource.")


def _shown(p: Platform, record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _uuid(p.config["seed"], "command", record["n"]),
        "device": record["device"],
        "command": record["command"],
        "params": record["params"],
        "status": record["status"],
        "requested_at": p.iso(record["t"]),
        "requested_by": record["who"],
        **({"error": record["error"]} if "error" in record else {}),
    }


def main() -> None:
    with open(CONFIG, encoding="utf-8") as f:
        Handler.platform = Platform(json.load(f))
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)  # noqa: S104 (the system network)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
