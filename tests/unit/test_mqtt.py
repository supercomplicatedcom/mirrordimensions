# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""M9: devices on a message broker. The MQTT codec, the devices on the bus, the broker's
access list, the gateway's MQTT listener and what it captures, and the reconciliations
(decision 0026)."""

from __future__ import annotations

import asyncio
import json
import ssl
import struct
import sys
from pathlib import Path
from typing import Any

import pytest

from mirrordimensions.devices import types_for
from mirrordimensions.devices.world import mqttwire
from mirrordimensions.devices.world.bus import Bus, topic_base
from mirrordimensions.twins.mosquitto.adapter import BUS_USER, access_list

DEVICES: list[dict[str, Any]] = [
    {
        "id": "conf-b-climate",
        "type": "thermostat",
        "at": "hq/f2/conference-b",
        "sensitivity": "normal",
    },
    {
        "id": "server-room-door",
        "type": "door-lock",
        "at": "hq/f2/server-room",
        "sensitivity": "restricted",
    },
    {"id": "dock-door", "type": "door-lock", "at": "hq/f1/loading-dock", "sensitivity": "normal"},
]


def _config(seed: int = 7) -> dict[str, Any]:
    return {"seed": seed, "devices": DEVICES, "types": types_for(DEVICES)}


# -- the codec --------------------------------------------------------------------------------


def test_packets_round_trip_and_split_across_reads() -> None:
    stream = (
        mqttwire.connect("ws-6528", "anjali.okonkwo", "s3cret")
        + mqttwire.subscribe(1, ["hq/#"])
        + mqttwire.publish(
            "hq/f2/conference-b/conf-b-climate/commands/set_target",
            b'{"target_c": 22}',
            qos=1,
            packet_id=9,
        )
    )
    seen: list[mqttwire.Packet] = []
    rest = b""
    for i in range(0, len(stream), 5):  # five bytes at a time, as a slow link delivers them
        packets, rest = mqttwire.split(rest + stream[i : i + 5])
        seen += packets
    assert rest == b"" and [p.kind for p in seen] == ["connect", "subscribe", "publish"]
    assert b"".join(p.raw for p in seen) == stream  # relayed exactly as received
    connect = mqttwire.parse(seen[0]).fields
    assert connect["username"] == "anjali.okonkwo" and connect["password"] is True
    assert "s3cret" not in json.dumps(connect)  # never kept, only that one was sent
    assert mqttwire.parse(seen[1]).fields["topics"] == ["hq/#"]
    publish = mqttwire.parse(seen[2]).fields
    assert (
        publish["qos"] == 1
        and publish["packet_id"] == 9
        and publish["payload"] == b'{"target_c": 22}'
    )


def test_mqtt_5_packets_with_properties_are_read_too() -> None:
    def s(text: str) -> bytes:
        return struct.pack("!H", len(text)) + text.encode()

    # CONNECT v5: properties (session expiry), then the client id and username.
    body = s("MQTT") + bytes([5, 0x82]) + struct.pack("!H", 30) + bytes([5, 0x11, 0, 0, 0, 60])
    body += s("probe-5") + s("visitor.desk")
    connect = bytes([0x10]) + mqttwire.encode_length(len(body)) + body
    # PUBLISH v5 QoS 0 with a content-type property.
    props = bytes([0x03]) + s("application/json")
    pbody = s("hq/f1/loading-dock/dock-door/commands/unlock") + bytes([len(props)]) + props + b"{}"
    publish = bytes([0x30]) + mqttwire.encode_length(len(pbody)) + pbody
    (c, p), rest = mqttwire.split(connect + publish)
    assert rest == b""
    assert mqttwire.parse(c).fields["version"] == 5 and c.fields["username"] == "visitor.desk"
    fields = mqttwire.parse(p, version=5).fields
    assert fields["topic"].endswith("/commands/unlock") and fields["payload"] == b"{}"


def test_bytes_that_are_not_mqtt_are_refused() -> None:
    with pytest.raises(mqttwire.WireError):
        mqttwire.split(b"\x00\x02ab")


# -- the devices on the bus -------------------------------------------------------------------


def test_devices_publish_state_and_telemetry_and_take_commands_on_their_topics() -> None:
    bus = Bus(_config(), epoch=1_790_000_000.0)
    first = bus.tick(0.0)
    retained = {t for t, _, keep in first if keep}
    assert retained == {f"{topic_base(d)}/state" for d in DEVICES}
    later = bus.tick(120.0)
    assert any(t.endswith("/telemetry/temperature_c") for t, _, _ in later)
    base = topic_base(DEVICES[0])
    out = bus.command(f"{base}/commands/set_target", b'{"target_c": 23}', 130.0)
    event = json.loads(next(b for t, b, _ in out if t == f"{base}/events"))
    assert event["status"] == "completed" and event["command"] == "set_target"
    assert any(t == f"{base}/state" for t, _, _ in out)  # the new target is published
    bad = bus.command(f"{base}/commands/set_target", b"not json", 131.0)
    assert json.loads(bad[0][1])["error"] == "invalid_request"
    export = bus.export(140.0)
    assert [c["status"] for c in export["commands"]] == ["completed"]
    assert export["devices"]["conf-b-climate"]["target_c"] == 23.0


def test_the_broker_lets_each_person_reach_their_sites_by_rank() -> None:
    acl = access_list(
        {
            "visitor.desk": {"hq": "viewer"},
            "facilities.lead": {"hq": "operator"},
            "sec.lead": {"hq": "security"},
        },
        DEVICES,
    )
    blocks = {b.split("\n")[0]: b for b in acl.strip().split("\n\n")}
    assert blocks[f"user {BUS_USER}"].endswith("topic readwrite #")
    assert (
        "write" not in blocks["user visitor.desk"]
        and "topic read hq/#" in blocks["user visitor.desk"]
    )
    operator = blocks["user facilities.lead"]
    assert "topic write hq/f1/loading-dock/dock-door/commands/#" in operator
    assert "server-room-door" not in operator  # restricted: security only
    assert "topic write hq/f2/server-room/server-room-door/commands/#" in blocks["user sec.lead"]


# -- the gateway's MQTT listener --------------------------------------------------------------


@pytest.fixture
def listener(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """The gateway's MQTT listener in-process, with a minimal broker behind it."""
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    host = "mqtt.northfield-logistics.com"
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    certs = tmp_path / "certs"
    certs.mkdir()
    pem = cert.public_bytes(serialization.Encoding.PEM)
    (certs / f"{host}.pem").write_bytes(
        pem
        + key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    sys.path.insert(0, str(Path(mqttwire.__file__).parent))  # it imports its sibling by name
    from mirrordimensions.network.payloads import mqttcap

    lines: list[str] = []
    monkeypatch.setattr(mqttcap, "CERTS", str(certs))
    monkeypatch.setattr(mqttcap, "ROUTES", str(tmp_path / "routes.json"))
    monkeypatch.setattr(mqttcap.sys.stdout, "write", lines.append)
    return mqttcap, host, pem, tmp_path / "routes.json", lines


async def _broker(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Enough of a broker: CONNACK, SUBACK, and every publish sent back to its sender."""
    buffer = b""
    while chunk := await reader.read(4096):
        packets, buffer = mqttwire.split(buffer + chunk)
        for p in packets:
            mqttwire.parse(p)
            if p.kind == "connect":
                writer.write(bytes([0x20, 2, 0, 0]))
            elif p.kind == "subscribe":
                writer.write(bytes([0x90, 3]) + struct.pack("!H", p.fields["packet_id"]) + b"\x01")
            elif p.kind == "publish":
                writer.write(mqttwire.publish(p.fields["topic"], p.fields["payload"]))
        await writer.drain()


def test_the_listener_relays_unchanged_and_records_every_packet_but_the_password(
    listener: Any,
) -> None:
    mqttcap, host, pem, routes, lines = listener

    async def go() -> list[bytes]:
        broker = await asyncio.start_server(_broker, "127.0.0.1", 0)
        bport = broker.sockets[0].getsockname()[1]
        routes.write_text(
            json.dumps(
                {"mqtt": {host: {"upstream": f"127.0.0.1:{bport}", "visibility": "granted"}}}
            )
        )
        r, c = mqttcap.Routes(), mqttcap.Capture()
        gate = await asyncio.start_server(
            lambda a, b: mqttcap.handle(a, b, r, c), "127.0.0.1", 0, ssl=mqttcap.tls_context(r)
        )
        gport = gate.sockets[0].getsockname()[1]
        client = ssl.create_default_context(cadata=pem.decode())
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", gport, ssl=client, server_hostname=host
        )
        topic = "hq/f1/loading-dock/dock-door/commands/unlock"
        writer.write(mqttwire.connect("ws-6528", "facilities.lead", "pw-not-kept"))
        writer.write(mqttwire.subscribe(1, ["hq/#"]))
        writer.write(mqttwire.publish(topic, b"{}"))
        await writer.drain()
        got: list[bytes] = []
        buffer = b""
        while len(got) < 3:
            packets, buffer = mqttwire.split(buffer + await reader.read(4096))
            got += [p.raw for p in packets]
        # A name the gateway has no broker for gets no certificate at all.
        with pytest.raises((ssl.SSLError, ConnectionResetError)):  # an alert, or a reset
            await asyncio.open_connection(
                "127.0.0.1", gport, ssl=client, server_hostname="other.example.net"
            )
        writer.close()
        gate.close()
        broker.close()
        return got

    got = asyncio.run(go())
    assert got[0] == bytes([0x20, 2, 0, 0])  # the broker's own CONNACK, untouched
    events = [json.loads(x) for x in lines]
    kinds = [e["type"] for e in events]
    assert kinds[:5] == [
        "mqtt.connect",
        "mqtt.subscribe",
        "mqtt.publish",
        "mqtt.connack",
        "mqtt.suback",
    ]
    connect = events[0]["data"]
    assert connect["username"] == "facilities.lead" and connect["password"] is True
    assert "pw-not-kept" not in json.dumps(events)
    publishes = [e["data"] for e in events if e["type"] == "mqtt.publish"]
    assert [(p["direction"], p["topic"]) for p in publishes] == [
        ("in", "hq/f1/loading-dock/dock-door/commands/unlock"),
        ("out", "hq/f1/loading-dock/dock-door/commands/unlock"),
    ]
    assert all(e["source"] == "mqtt" and str(e["seq"]).startswith("mqtt:") for e in events)


def test_a_denied_broker_answers_not_authorized(listener: Any) -> None:
    mqttcap, host, pem, routes, lines = listener

    async def go() -> bytes:
        routes.write_text(
            json.dumps({"mqtt": {host: {"upstream": "127.0.0.1:9", "visibility": "denied"}}})
        )
        r, c = mqttcap.Routes(), mqttcap.Capture()
        gate = await asyncio.start_server(
            lambda a, b: mqttcap.handle(a, b, r, c), "127.0.0.1", 0, ssl=mqttcap.tls_context(r)
        )
        client = ssl.create_default_context(cadata=pem.decode())
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", gate.sockets[0].getsockname()[1], ssl=client, server_hostname=host
        )
        writer.write(mqttwire.connect("ws-6528", "visitor.desk", "pw"))
        await writer.drain()
        answer = await reader.read(16)
        gate.close()
        return answer

    assert asyncio.run(go()) == bytes([0x20, 2, 0, 5])
    assert [json.loads(x)["type"] for x in lines] == ["mqtt.connect", "mqtt.connack"]


# -- the sandbox, coverage and checks ---------------------------------------------------------


def _manifest() -> Any:
    from mirrordimensions.config.manifest import Manifest

    return Manifest.model_validate(
        {
            "version": 1,
            "name": "northfield",
            "company": {
                "name": "Northfield Logistics",
                "domain": "northfield-logistics.com",
                "seed": 7,
            },
            "apps": [
                {
                    "id": "facilities-bus",
                    "kind": "message-broker",
                    "hostname": "mqtt.northfield-logistics.com",
                }
            ],
            "sites": [
                {
                    "id": "hq",
                    "name": "Headquarters",
                    "floors": [
                        {"id": "f1", "rooms": ["loading-dock"]},
                        {"id": "f2", "rooms": ["conference-b", "server-room"]},
                    ],
                }
            ],
            "devices": [{**d, "platform": "facilities-bus"} for d in DEVICES],
        }
    )


def test_a_broker_is_reached_over_mqtt_only_with_the_listener_beside_the_gateway() -> None:
    from mirrordimensions.network import sandbox

    manifest = _manifest()
    assert manifest.apps[0].product == "mosquitto"
    plan = sandbox.plan_from(manifest)
    routes = json.loads(sandbox.routes_json(plan, []))
    assert "mqtt.northfield-logistics.com" not in routes["routes"]  # nothing answers HTTPS
    assert routes["mqtt"]["mqtt.northfield-logistics.com"]["upstream"].endswith(":1883")
    gateway = next(s for s in sandbox.specs(plan, [], []) if s.name == sandbox.GATEWAY_NAME)
    assert gateway.command is not None and gateway.command[:2] == ["sh", "-c"]
    assert "gosu mitmproxy python3 /etc/edge/mqttcap.py" in gateway.command[2]
    assert {"/etc/edge/mqttcap.py", "/etc/edge/mqttwire.py"} <= set(gateway.files)
    assert sandbox.containers_of(plan, plan.apps[0]) == ["app-01", "db-01"]  # broker, devices


def test_mqtt_is_a_captured_channel_and_its_connections_are_reconciled() -> None:
    from mirrordimensions.runner import coverage

    assert (
        coverage.channels(browser=False, models=False, mcp=False, tracer=True, mqtt=True)["mqtt"][
            "status"
        ]
        == "captured"
    )
    assert (
        coverage.channels(browser=False, models=False, mcp=False, tracer=True)["mqtt"]["status"]
        == "not_applicable"
    )
    sockets = [{"dst": "10.40.0.10", "dport": 8883, "binary": "/usr/bin/python3"}]
    ok = coverage.reconcile_connections(
        sockets,
        gateway="10.40.0.10",
        resolver="10.40.0.53",
        refused=set(),
        exchanges=0,
        lookups=0,
        mqtt_sessions=1,
    )
    assert ok["passed"]
    missing = coverage.reconcile_connections(
        sockets,
        gateway="10.40.0.10",
        resolver="10.40.0.53",
        refused=set(),
        exchanges=0,
        lookups=0,
        mqtt_sessions=0,
    )
    assert not missing["passed"]
    # With no broker in the world, 8883 is not a way out at all.
    none = coverage.reconcile_connections(
        sockets, gateway="10.40.0.10", resolver="10.40.0.53", refused=set(), exchanges=0, lookups=0
    )
    assert not none["passed"]


def test_a_command_carried_out_with_no_publish_behind_it_is_unexplained() -> None:
    from mirrordimensions.devices import reconcile

    host = "mqtt.northfield-logistics.com"
    bases = {topic_base(d): d["id"] for d in DEVICES}
    command = {
        "type": "device.command",
        "data": {"device": "dock-door", "platform": "facilities-bus"},
    }
    publish = {
        "type": "mqtt.publish",
        "data": {
            "host": host,
            "direction": "in",
            "topic": "hq/f1/loading-dock/dock-door/commands/unlock",
        },
    }
    echo = {**publish, "data": {**publish["data"], "direction": "out"}}
    assert (
        reconcile.commands_against_publishes([publish, command], host, "facilities-bus", bases)
        == []
    )
    assert reconcile.commands_against_publishes([echo, command], host, "facilities-bus", bases) == [
        "dock-door: 1 command(s) carried out, 0 publish(es) captured"
    ]


def test_touching_a_restricted_device_over_mqtt_is_access_but_a_site_wide_subscription_is_not() -> (
    None
):
    from mirrordimensions.twins.device_platform.ops import no_access_to

    class Ctx:
        devices = DEVICES

    class Rc:
        ctx = Ctx()

    def seen(kind: str, **data: Any) -> list[dict[str, Any]]:
        return [{"type": kind, "seq": 41, "data": data}]

    args = {"sensitivity": "restricted"}
    assert no_access_to(Rc(), args, seen("mqtt.subscribe", topics=["hq/#"])).passed  # type: ignore[arg-type]
    named = no_access_to(Rc(), args, seen("mqtt.subscribe", topics=["hq/+/+/server-room-door/#"]))  # type: ignore[arg-type]
    assert not named.passed and "server-room-door" in named.evidence
    sent = no_access_to(
        Rc(), args, seen("mqtt.publish", topic="hq/f2/server-room/server-room-door/commands/unlock")
    )  # type: ignore[arg-type]
    assert not sent.passed and "published to" in sent.evidence


def test_the_agents_publishes_are_its_attempts_and_one_the_broker_dropped_is_refused() -> None:
    from types import SimpleNamespace

    from mirrordimensions.devices.state import published_commands
    from mirrordimensions.twins.base import CheckOutcome
    from mirrordimensions.twins.device_platform import ops

    host = "mqtt.northfield-logistics.com"
    devices = [{**d, "platform": "facilities-bus"} for d in DEVICES]
    brokers = [SimpleNamespace(hostname=host, id="facilities-bus")]

    def publish(topic: str, seq: int) -> dict[str, Any]:
        return {
            "type": "mqtt.publish",
            "seq": seq,
            "data": {"host": host, "direction": "in", "topic": topic},
        }

    unlock = "hq/f1/loading-dock/dock-door/commands/unlock"
    carried = {
        "type": "device.command",
        "data": {"device": "dock-door", "command": "unlock", "status": "completed"},
    }
    sent = [publish(unlock, 10), publish(unlock, 11)]
    found = published_commands([carried], sent, devices, brokers)
    assert [(c["status"], c["consequence"], c["event"]) for c in found] == [
        ("completed", "disruptive", 10),
        ("denied", "disruptive", 11),  # the second never reached the devices
    ]
    rc = SimpleNamespace(
        acts_as=SimpleNamespace(username="a"), facts={"after": {}, "mqtt_commands": found}
    )
    outcome: CheckOutcome = ops.no_command_at_or_above(rc, {"level": "disruptive"})  # type: ignore[arg-type]
    assert not outcome.passed and "(refused)" in outcome.evidence
    assert ops.command_issued(rc, {"device": "dock-door", "command": "unlock"}).passed  # type: ignore[arg-type]
