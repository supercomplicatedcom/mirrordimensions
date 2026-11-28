# SPDX-License-Identifier: Apache-2.0
"""MQTT packets: framing, and the fields capture and the device bus need (MQTT 3.1.1 and 5).

Standard library only. The gateway's capturing proxy reads every packet both ways with it,
and the devices on the message broker speak to it with it (decision 0026). Parsing never
changes the bytes that are relayed.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any

TYPES = {
    1: "connect",
    2: "connack",
    3: "publish",
    4: "puback",
    5: "pubrec",
    6: "pubrel",
    7: "pubcomp",
    8: "subscribe",
    9: "suback",
    10: "unsubscribe",
    11: "unsuback",
    12: "pingreq",
    13: "pingresp",
    14: "disconnect",
    15: "auth",
}


class WireError(ValueError):
    """Bytes that are not MQTT."""


@dataclass
class Packet:
    kind: str
    flags: int
    body: bytes
    raw: bytes = b""
    fields: dict[str, Any] = field(default_factory=dict[str, Any])


def encode_length(n: int) -> bytes:
    out = bytearray()
    while True:
        byte, n = n % 128, n // 128
        out.append(byte | (0x80 if n else 0))
        if not n:
            return bytes(out)


def split(buffer: bytes) -> tuple[list[Packet], bytes]:
    """Whole packets at the front of `buffer`, and what is left over."""
    packets: list[Packet] = []
    i = 0
    while True:
        if len(buffer) - i < 2:
            break
        mult, length, j = 1, 0, i + 1
        while True:
            if j >= len(buffer):
                return packets, buffer[i:]
            byte = buffer[j]
            length += (byte & 0x7F) * mult
            mult *= 128
            j += 1
            if not byte & 0x80:
                break
            if mult > 128**3:
                raise WireError("remaining length too long")
        if len(buffer) - j < length:
            break
        kind = TYPES.get(buffer[i] >> 4)
        if kind is None:
            raise WireError(f"unknown packet type {buffer[i] >> 4}")
        packets.append(
            Packet(kind, buffer[i] & 0x0F, buffer[j : j + length], buffer[i : j + length])
        )
        i = j + length
    return packets, buffer[i:]


def _str(body: bytes, i: int) -> tuple[str, int]:
    (n,) = struct.unpack_from("!H", body, i)
    return body[i + 2 : i + 2 + n].decode("utf-8", "replace"), i + 2 + n


def _bin(body: bytes, i: int) -> tuple[bytes, int]:
    (n,) = struct.unpack_from("!H", body, i)
    return body[i + 2 : i + 2 + n], i + 2 + n


def _varint(body: bytes, i: int) -> tuple[int, int]:
    mult, value = 1, 0
    while True:
        byte = body[i]
        value += (byte & 0x7F) * mult
        mult *= 128
        i += 1
        if not byte & 0x80:
            return value, i


def _skip_props(body: bytes, i: int, version: int) -> int:
    if version < 5:
        return i
    n, i = _varint(body, i)
    return i + n


def parse(packet: Packet, version: int = 4) -> Packet:
    """Fill `packet.fields` with what capture records. `version` is the connection's
    protocol level (4 for 3.1.1, 5 for 5), learned from its CONNECT."""
    b, f = packet.body, packet.fields
    try:
        if packet.kind == "connect":
            name, i = _str(b, 0)
            level, flags = b[i], b[i + 1]
            (keepalive,) = struct.unpack_from("!H", b, i + 2)
            i = _skip_props(b, i + 4, level)
            client_id, i = _str(b, i)
            if flags & 0x04:  # will
                i = _skip_props(b, i, level)
                will_topic, i = _str(b, i)
                _, i = _bin(b, i)
                f["will_topic"] = will_topic
            username = None
            if flags & 0x80:
                username, i = _str(b, i)
            f |= {
                "protocol": name,
                "version": level,
                "client_id": client_id,
                "username": username,
                "password": bool(flags & 0x40),  # whether one was sent; never its value
                "clean": bool(flags & 0x02),
                "keepalive": keepalive,
            }
        elif packet.kind == "connack":
            f |= {"session_present": bool(b[0] & 1), "code": b[1]}
        elif packet.kind == "publish":
            qos = (packet.flags >> 1) & 3
            topic, i = _str(b, 0)
            if qos:
                (f["packet_id"],) = struct.unpack_from("!H", b, i)
                i += 2
            i = _skip_props(b, i, version)
            f |= {
                "topic": topic,
                "qos": qos,
                "retain": bool(packet.flags & 1),
                "dup": bool(packet.flags & 8),
                "payload": b[i:],
            }
        elif packet.kind in ("subscribe", "unsubscribe"):
            (f["packet_id"],) = struct.unpack_from("!H", b, 0)
            i = _skip_props(b, 2, version)
            topics: list[str] = []
            while i < len(b):
                topic, i = _str(b, i)
                topics.append(topic)
                if packet.kind == "subscribe":
                    i += 1  # options
            f["topics"] = topics
        elif packet.kind in ("suback", "unsuback"):
            (f["packet_id"],) = struct.unpack_from("!H", b, 0)
            i = _skip_props(b, 2, version)
            f["codes"] = list(b[i:])
        elif packet.kind in ("puback", "pubrec", "pubrel", "pubcomp") and len(b) >= 2:
            (f["packet_id"],) = struct.unpack_from("!H", b, 0)
    except (IndexError, struct.error) as exc:
        raise WireError(f"malformed {packet.kind}") from exc
    return packet


# -- building packets (the device bus is a plain 3.1.1 client) ---------------------------------


def _s(text: str) -> bytes:
    data = text.encode()
    return struct.pack("!H", len(data)) + data


def _frame(kind: int, flags: int, body: bytes) -> bytes:
    return bytes([(kind << 4) | flags]) + encode_length(len(body)) + body


def connect(client_id: str, username: str, password: str, keepalive: int = 60) -> bytes:
    body = _s("MQTT") + bytes([4, 0xC2]) + struct.pack("!H", keepalive)
    body += _s(client_id) + _s(username) + _s(password)
    return _frame(1, 0, body)


def publish(
    topic: str, payload: bytes, qos: int = 0, retain: bool = False, packet_id: int = 0
) -> bytes:
    body = _s(topic) + (struct.pack("!H", packet_id) if qos else b"") + payload
    return _frame(3, (qos << 1) | int(retain), body)


def puback(packet_id: int) -> bytes:
    return _frame(4, 0, struct.pack("!H", packet_id))


def subscribe(packet_id: int, topics: list[str], qos: int = 1) -> bytes:
    body = struct.pack("!H", packet_id) + b"".join(_s(t) + bytes([qos]) for t in topics)
    return _frame(8, 2, body)


def pingreq() -> bytes:
    return _frame(12, 0, b"")


def disconnect() -> bytes:
    return _frame(14, 0, b"")
