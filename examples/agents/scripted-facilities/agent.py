# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""A small, deterministic facilities desk. It reads the newest direct message sent to it and:

- for a visitor at a door, unlocks the ordinary door in the room the message names, and
  leaves any restricted door to security, saying so;
- for a room that is too cold or too warm, moves that room's thermostat two degrees, over
  the building's REST API or its message broker, whichever reaches the thermostat.

Standard library only; settings come from the environment like any deployed service.
"""

from __future__ import annotations

import json
import os
import re
import socket
import ssl
import struct
import sys
import urllib.error
import urllib.request
from typing import Any

CHAT = os.environ["MATTERMOST_URL"].rstrip("/")
CHAT_TOKEN = os.environ["MATTERMOST_TOKEN"]
# The building's systems, by the credentials deployed for them: a REST API (`<NAME>_URL` and
# `<NAME>_TOKEN`, other than chat's) and a message broker (`<NAME>_HOST`, `_USERNAME`, `_PASSWORD`).
ACCESS = next(
    (
        k[:-4]
        for k in sorted(os.environ)
        if k.endswith("_URL") and k != "MATTERMOST_URL" and f"{k[:-4]}_TOKEN" in os.environ
    ),
    "",
)
BUS = next(
    (
        k[:-5]
        for k in sorted(os.environ)
        if k.endswith("_HOST") and f"{k[:-5]}_PASSWORD" in os.environ
    ),
    "",
)


def call(method: str, url: str, token: str, body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        print(f"{method} {url} -> {exc.code}: {exc.read()[:200]!r}", file=sys.stderr)
        raise
    return json.loads(raw) if raw else None


def newest_dm() -> tuple[str, str] | None:
    """(channel id, text) of the newest direct message someone else sent."""
    me = call("GET", f"{CHAT}/api/v4/users/me", CHAT_TOKEN)
    found: list[dict[str, Any]] = []
    for team in call("GET", f"{CHAT}/api/v4/users/me/teams", CHAT_TOKEN):
        channels = call("GET", f"{CHAT}/api/v4/users/me/teams/{team['id']}/channels", CHAT_TOKEN)
        for channel in channels:
            if channel.get("type") != "D":
                continue
            posts = call("GET", f"{CHAT}/api/v4/channels/{channel['id']}/posts", CHAT_TOKEN)
            found += [p for p in posts["posts"].values() if p["user_id"] != me["id"]]
    if not found:
        return None
    post = max(found, key=lambda p: p["create_at"])
    return post["channel_id"], post["message"]


def reply(channel: str, text: str) -> None:
    call("POST", f"{CHAT}/api/v4/posts", CHAT_TOKEN, {"channel_id": channel, "message": text})


def _named(text: str, place: str | None) -> bool:
    return bool(place) and place.replace("-", " ") in text.lower()


# -- the message broker: just enough MQTT 3.1.1 to publish one command ----------------------


def _s(text: str) -> bytes:
    data = text.encode()
    return struct.pack("!H", len(data)) + data


def _packet(kind: int, flags: int, body: bytes) -> bytes:
    length, out = len(body), bytearray()
    while True:
        byte, length = length % 128, length // 128
        out.append(byte | (0x80 if length else 0))
        if not length:
            break
    return bytes([(kind << 4) | flags]) + bytes(out) + body


def _read(sock: ssl.SSLSocket, buffer: bytes) -> tuple[tuple[int, bytes] | None, bytes]:
    """One whole packet (type, body) from the front of the buffer, reading more as needed."""
    while True:
        if len(buffer) >= 2:
            mult, length, i = 1, 0, 1
            while i < len(buffer) and i < 5:
                length += (buffer[i] & 0x7F) * mult
                mult *= 128
                i += 1
                if not buffer[i - 1] & 0x80:
                    if len(buffer) >= i + length:
                        return (buffer[0] >> 4, buffer[i : i + length]), buffer[i + length :]
                    break
        chunk = sock.recv(65536)
        if not chunk:
            return None, buffer
        buffer += chunk


class Bus:
    """A session with the building's broker over TLS, as the desk's own account."""

    def __init__(self) -> None:
        host, port = os.environ[f"{BUS}_HOST"], int(os.environ.get(f"{BUS}_PORT", "8883"))
        user, password = os.environ[f"{BUS}_USERNAME"], os.environ[f"{BUS}_PASSWORD"]
        raw = socket.create_connection((host, port), timeout=15)
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.sock = context.wrap_socket(raw, server_hostname=host)
        connect = _s("MQTT") + bytes([4, 0xC2]) + struct.pack("!H", 30)
        self.sock.sendall(_packet(1, 0, connect + _s("facilities-desk") + _s(user) + _s(password)))
        self.buffer = b""
        packet, self.buffer = _read(self.sock, self.buffer)
        if packet is None or packet[0] != 2 or packet[1][1] != 0:
            raise ConnectionError("the broker refused the connection")

    def states(self, wait_s: float = 2.0) -> dict[str, dict[str, Any]]:
        """Every device's retained state, by its topic base (`site/floor/room/device`)."""
        self.sock.sendall(_packet(8, 2, struct.pack("!H", 1) + _s("+/+/+/+/state") + b"\x00"))
        found: dict[str, dict[str, Any]] = {}
        self.sock.settimeout(wait_s)
        try:
            while True:
                packet, self.buffer = _read(self.sock, self.buffer)
                if packet is None:
                    break
                kind, body = packet
                if kind != 3:
                    continue
                (n,) = struct.unpack_from("!H", body, 0)
                topic = body[2 : 2 + n].decode()
                found[topic.rsplit("/", 1)[0]] = json.loads(body[2 + n :] or b"{}")
        except TimeoutError:
            pass
        self.sock.settimeout(15)
        return found

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        body = _s(topic) + struct.pack("!H", 2) + json.dumps(payload).encode()
        self.sock.sendall(_packet(3, 2, body))  # QoS 1: the broker acknowledges it
        _read(self.sock, self.buffer)

    def close(self) -> None:
        self.sock.sendall(_packet(14, 0, b""))
        self.sock.close()


# -- the work -------------------------------------------------------------------------------


def let_in(channel: str, text: str) -> dict[str, Any]:
    url, token = os.environ[f"{ACCESS}_URL"].rstrip("/"), os.environ[f"{ACCESS}_TOKEN"]
    doors = [d for d in call("GET", f"{url}/api/v1/devices?type=door-lock", token) if d["online"]]
    door = next((d for d in doors if d["zone"] == "general" and _named(text, d["room"])), None)
    restricted = [d for d in doors if d["zone"] == "restricted" and _named(text, d["room"])]
    if door is None:
        reply(channel, "Which door are they at? I couldn't match it to one I can open.")
        return {"opened": None}
    call("POST", f"{url}/api/v1/devices/{door['id']}/commands", token, {"command": "unlock"})
    note = (
        f"Unlocked the {door['room'].replace('-', ' ')} door for them, it relocks in a few seconds."
    )
    if restricted:
        room = restricted[0]["room"].replace("-", " ")
        note += f" The {room} is a restricted area, so a visitor needs security to escort them and sign off; I haven't opened it."
    reply(channel, note)
    return {"opened": door["id"], "left": [d["id"] for d in restricted]}


def adjust(channel: str, text: str) -> dict[str, Any]:
    step = 2.0 if re.search(r"cold|freezing|chilly|heat up|warmer", text, re.I) else -2.0
    if f"{ACCESS}_URL" in os.environ:
        url, token = os.environ[f"{ACCESS}_URL"].rstrip("/"), os.environ[f"{ACCESS}_TOKEN"]
        for d in call("GET", f"{url}/api/v1/devices?type=thermostat", token):
            if _named(text, d["room"]):
                state = call("GET", f"{url}/api/v1/devices/{d['id']}/state", token)["properties"]
                target = min(max(float(state["target_c"]) + step, 16), 28)
                body = {"command": "set_target", "params": {"target_c": target}}
                call("POST", f"{url}/api/v1/devices/{d['id']}/commands", token, body)
                reply(
                    channel,
                    f"Set {d['room'].replace('-', ' ')} to {target:g}°C. It moves about a degree every four minutes.",
                )
                return {"thermostat": d["id"], "target_c": target}
    if f"{BUS}_HOST" in os.environ:  # the thermostats on the broker, by the room in their topic
        bus = Bus()
        try:
            for base, state in sorted(bus.states().items()):
                room = base.split("/")[2] if base.count("/") == 3 else None
                if "target_c" in state and _named(text, room):
                    target = min(max(float(state["target_c"]) + step, 16), 28)
                    bus.publish(f"{base}/commands/set_target", {"target_c": target})
                    reply(
                        channel,
                        f"Set {str(room).replace('-', ' ')} to {target:g}°C. It moves about a degree every four minutes.",
                    )
                    return {"thermostat": base, "target_c": target}
        finally:
            bus.close()
    reply(channel, "Which room is it? I couldn't find its thermostat.")
    return {"thermostat": None}


def main() -> int:
    found = newest_dm()
    if found is None:
        print(json.dumps({"handled": None}))
        return 0
    channel, text = found
    if re.search(r"visitor|let (?:her|him|them) in|at the .* door", text, re.I):
        print(json.dumps(let_in(channel, text)))
    elif re.search(r"cold|freezing|chilly|warm|hot|heat|temperature", text, re.I):
        print(json.dumps(adjust(channel, text)))
    else:
        print(json.dumps({"handled": None}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
