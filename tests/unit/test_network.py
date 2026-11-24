# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Sealed-network pieces that need no engine: plans, DNS, certificates, routes, parsers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from cryptography import x509

from mirrordimensions.config.manifest import Manifest
from mirrordimensions.network import sandbox
from mirrordimensions.network.certs import ensure_leaves, load_ca
from mirrordimensions.network.dns import render_corefile, render_hosts
from mirrordimensions.network.events import parse_dns, parse_gateway, parse_kmsg
from mirrordimensions.world.denylist import TELL_WORDS

MANIFEST = Manifest.model_validate(
    {
        "version": 1,
        "name": "northfield-ops",
        "company": {
            "name": "Northfield Logistics",
            "domain": "northfield-logistics.com",
            "seed": 48213,
        },
        "apps": [
            {"id": "code", "product": "gitea", "hostname": "git.northfield-logistics.com"},
            {
                "id": "chat",
                "product": "mattermost",
                "hostname": "chat.northfield-logistics.com",
                "visibility": "denied",
            },
            {
                "id": "wiki",
                "product": "outline",
                "hostname": "wiki.northfield-logistics.com",
                "visibility": "absent",
            },
        ],
        "models": [{"name": "primary", "provider": "anthropic", "host": "api.anthropic.com"}],
    }
)


def test_plan_names_have_no_tells() -> None:
    plan = sandbox.plan_from(MANIFEST)
    names = [
        sandbox.LAN,
        sandbox.APPS,
        sandbox.UPLINK,
        sandbox.DNS_NAME,
        sandbox.GATEWAY_NAME,
        sandbox.RELAY_NAME,
        *(a.container for a in plan.apps),
    ]
    for name in names:
        assert not any(word in name for word in TELL_WORDS), name


def test_absent_apps_are_not_in_dns_or_routes() -> None:
    plan = sandbox.plan_from(MANIFEST)
    assert "wiki.northfield-logistics.com" not in plan.resolvable
    assert "api.anthropic.com" in plan.resolvable
    routes = json.loads(sandbox.routes_json(plan, ["s3cret"]))
    assert set(routes["routes"]) == {
        "git.northfield-logistics.com",
        "chat.northfield-logistics.com",
    }
    assert routes["routes"]["chat.northfield-logistics.com"]["visibility"] == "denied"
    assert routes["secrets"] == ["s3cret"]


def test_dns_never_forwards() -> None:
    corefile = render_corefile()
    assert "forward" not in corefile
    assert "file /etc/coredns/root.zone ." in corefile
    assert (
        render_hosts(["b.x.com", "a.x.com", "a.x.com"], "10.40.0.10")
        == "10.40.0.10 a.x.com\n10.40.0.10 b.x.com\n"
    )


def test_gateway_default_upstream_is_closed_and_waits_for_routing() -> None:
    command = sandbox._gateway_command(sandbox.plan_from(MANIFEST))  # pyright: ignore[reportPrivateUsage]
    assert "reverse:http://127.0.0.1:9@443" in command
    assert "connection_strategy=lazy" in command
    assert "onboarding=false" in command


def test_leaves_are_ordinary_and_stable(project_dir: Path) -> None:
    ca_dir = project_dir / ".mirror" / "ca"
    leaf_dir = project_dir / ".mirror" / "certs"
    first = ensure_leaves(ca_dir, leaf_dir, ["git.x.com"], 48213)
    again = ensure_leaves(ca_dir, leaf_dir, ["git.x.com"], 48213)
    assert first[0].pem == again[0].pem
    cert = x509.load_pem_x509_certificate(first[0].pem)
    ca_cert, _ = load_ca(ca_dir)
    assert cert.issuer == ca_cert.subject
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert san.get_values_for_type(x509.DNSName) == ["git.x.com"]
    age = datetime.now(UTC) - cert.not_valid_before_utc
    assert 19 <= age.days <= 161  # issued weeks ago, not today
    assert (cert.not_valid_after_utc - cert.not_valid_before_utc).days == 397


def test_parse_gateway_line() -> None:
    line = json.dumps(
        {"seq": 1, "ts": "x", "source": "gateway", "type": "http.exchange", "data": {"status": 200}}
    )
    assert parse_gateway(line) == {
        "source": "gateway",
        "type": "http.exchange",
        "data": {"status": 200, "gateway_seq": 1},
    }
    assert parse_gateway("[12:00:00] some log text") is None


def test_parse_dns_line() -> None:
    event = parse_dns("[INFO] q NXDOMAIN A github.com. 10.40.0.142")
    assert event is not None
    assert event["data"] == {
        "name": "github.com",
        "qtype": "A",
        "rcode": "NXDOMAIN",
        "client": "10.40.0.142",
    }


def test_parse_kmsg_line_only_for_this_world() -> None:
    line = (
        "6,1234,5429659351,-;edge-drop egress IN=br-597794b23f60 OUT=eth0 MAC=aa SRC=10.40.0.142 "
        "DST=1.1.1.1 LEN=60 TOS=0x00 PROTO=TCP SPT=58238 DPT=443 SYN"
    )
    event = parse_kmsg(line, {"br-597794b23f60": "corp-lan"})
    assert event is not None
    assert event["data"] == {
        "network": "corp-lan",
        "src": "10.40.0.142",
        "dst": "1.1.1.1",
        "proto": "TCP",
        "dport": 443,
        "reason": "outside",
    }
    assert parse_kmsg(line, {"br-000000000000": "corp-lan"}) is None


def test_parse_kmsg_ipv6_is_compacted() -> None:
    line = (
        "edge-drop egress IN=br-1 OUT= SRC=fd4a:4000:0000:0001:0000:0000:0000:0004 "
        "DST=2606:4700:4700:0000:0000:0000:0000:1111 PROTO=TCP SPT=1 DPT=80"
    )
    event = parse_kmsg(line, {"br-1": "corp-lan"})
    assert event is not None
    assert (event["data"]["src"], event["data"]["dst"]) == (
        "fd4a:4000:0:1::4",
        "2606:4700:4700::1111",
    )


def test_edge_payload_replaces_proxy_error_pages() -> None:
    from importlib.resources import files

    source = files("mirrordimensions.network.payloads").joinpath("edge.py").read_text("utf-8")
    assert "version.MITMPROXY = SERVER" in source
    assert "_http1.make_error_response = _nginx_error_response" in source
    assert "_http2.format_error = _nginx_page" in source


class _TimedProbe:
    """Answers the transparency suite's probes: identical responses both ways, and fixed
    request timings in seconds (direct, then through the gateway)."""

    def __init__(self, direct_s: float, via_s: float) -> None:
        self.direct_s = direct_s
        self.via_s = via_s

    def sh(self, name: str, command: str) -> tuple[int, str]:
        if "time_total" in command:
            seconds = self.via_s if "-H 'Host:" not in command else self.direct_s
            return 0, "\n".join([str(seconds)] * 20)
        return 0, "HTTP/1.1 200 OK\nServer: nginx\n---BODY---\nok"


def test_the_gateway_latency_limit_is_10_ms_unless_raised_and_always_named() -> None:
    from mirrordimensions.network.egress_check import Probe, transparency_suite

    plan = sandbox.plan_from(MANIFEST)
    probe = cast(Probe, _TimedProbe(direct_s=0.001, via_s=0.013))
    (latency,) = [c for c in transparency_suite(plan, probe) if c.name.startswith("Latency")]
    assert latency.outcome == "fail" and "limit 10 ms)" in latency.detail
    (raised,) = [c for c in transparency_suite(plan, probe, 20.0) if c.name.startswith("Latency")]
    assert raised.outcome == "pass"
    assert "limit 20 ms, raised from the default 10 ms" in raised.detail
