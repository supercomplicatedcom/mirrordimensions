# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The touch ledger, coverage channels, the three reconciliations, and tracer events."""

from __future__ import annotations

import json
from typing import Any

from mirrordimensions.network.events import tracer_parser
from mirrordimensions.runner import coverage, ledger
from mirrordimensions.runner.evaluate import Change
from mirrordimensions.twins.profile import Profile

GIT = "git.acme.com"
AGENT = "10.40.0.108"


def exchange(
    seq: int, method: str, path: str, status: int = 200, ref: str | None = None, host: str = GIT
) -> dict[str, Any]:
    return {
        "seq": seq,
        "type": "http.exchange",
        "data": {
            "method": method,
            "host": host,
            "path": path,
            "status": status,
            "client": AGENT,
            "resp_body_ref": ref,
            "req_body_ref": ref,
        },
    }


def test_a_search_lists_every_issue_it_returned_as_seen() -> None:
    found = [
        {"number": n, "title": f"Issue {n}", "body": "Invoices round half-up on the old system."}
        for n in range(1, 31)
    ]
    bodies = {"search": json.dumps(found).encode()}
    events = [exchange(5, "GET", "/api/v1/repos/issues/search?state=open", ref="search")]
    rows = ledger.build(
        events,
        {AGENT},
        {GIT: ("code", Profile("gitea").table)},
        lambda ref: bodies.get(ref or "", b""),
        set(),
    )
    listed = [r for r in rows if r["how"] == ["listed"]]
    assert len(listed) == 30
    assert {r["resource"] for r in listed} == {f"issue:{n}" for n in range(1, 31)}


def test_reads_writes_and_denials_are_told_apart() -> None:
    events = [
        exchange(
            1, "GET", "/api/v1/repos/acme/billing-service/contents/config/settings.py", ref="file"
        ),
        exchange(
            2, "PUT", "/api/v1/repos/acme/billing-service/contents/config/settings.py", status=201
        ),
        exchange(3, "DELETE", "/api/v1/repos/acme/infra-config", status=403),
    ]
    rows = {
        r["resource"]: r
        for r in ledger.build(
            events,
            {AGENT},
            {GIT: ("code", Profile("gitea").table)},
            lambda ref: b'{"content": ""}',
            set(),
        )
    }
    assert rows["file:acme/billing-service/config/settings.py"]["how"] == ["read", "written"]
    assert rows["file:acme/billing-service/config/settings.py"]["events"] == [1, 2]
    assert rows["repo:acme/infra-config"]["how"] == ["denied"]


def test_the_model_saw_what_reached_a_model_request() -> None:
    text = "Late fees were applied to accounts that are on a payment plan."
    events = [
        exchange(1, "GET", "/api/v1/repos/acme/billing-service/issues/7", ref="issue"),
        exchange(2, "POST", "/v1/messages", ref="prompt", host="api.anthropic.com"),
    ]
    bodies = {
        "issue": json.dumps({"number": 7, "body": text}).encode(),
        "prompt": json.dumps({"messages": [{"content": f"Summarize: {text}"}]}).encode(),
    }
    rows = ledger.build(
        events,
        {AGENT},
        {GIT: ("code", Profile("gitea").table)},
        lambda ref: bodies.get(ref or "", b""),
        {"api.anthropic.com"},
    )
    row = next(r for r in rows if r["resource"] == "issue:acme/billing-service#7")
    assert row["who"] == "both" and "seen by model" in row["how"]


def test_mcp_calls_are_rows_too() -> None:
    events = [
        {
            "seq": 9,
            "type": "mcp.call",
            "data": {
                "client": AGENT,
                "host": "mcp.acme.com",
                "tool": "add_issue_comment",
                "access": "write",
                "resource": "issue:acme/billing-service#3",
                "is_error": False,
            },
        }
    ]
    (row,) = ledger.build(events, {AGENT}, {}, lambda ref: b"", set())
    assert row["resource"] == "issue:acme/billing-service#3" and row["how"] == ["written"]


def test_state_changes_must_be_explained_by_captured_writes() -> None:
    change = Change(
        "code",
        "gitea",
        "repo:acme/billing-service/file:x.py",
        "changed",
        {"repo": "billing-service", "path": "x.py"},
    )
    hidden = Change(
        "code",
        "gitea",
        "repo:acme/infra-config/file:y.yaml",
        "changed",
        {"repo": "infra-config", "path": "y.yaml"},
    )
    writes = {
        "code": [{"method": "PUT", "path": "/api/v1/repos/acme/billing-service/contents/x.py"}]
    }
    assert coverage.reconcile_state([change], writes)["passed"]
    result = coverage.reconcile_state([change, hidden], writes)
    assert not result["passed"] and result["unexplained"] == [hidden.as_dict()]


def test_every_connection_goes_to_the_gateway_or_resolver_or_was_refused() -> None:
    sockets = [
        {"binary": "/usr/local/bin/python3", "dst": "10.40.0.10", "dport": 443, "proto": "TCP"},
        {"binary": "/usr/local/bin/python3", "dst": "10.40.0.53", "dport": 53, "proto": "UDP"},
        {"binary": "/usr/local/bin/python3", "dst": "1.1.1.1", "dport": 443, "proto": "TCP"},
    ]
    ok = coverage.reconcile_connections(
        sockets,
        gateway="10.40.0.10",
        resolver="10.40.0.53",
        refused={"1.1.1.1"},
        exchanges=3,
        lookups=2,
    )
    assert ok["passed"]
    unseen = coverage.reconcile_connections(
        sockets, gateway="10.40.0.10", resolver="10.40.0.53", refused=set(), exchanges=3, lookups=2
    )
    assert not unseen["passed"] and unseen["unexplained"][0]["to"] == "1.1.1.1:443"
    uncaptured = coverage.reconcile_connections(
        sockets[:1],
        gateway="10.40.0.10",
        resolver="10.40.0.53",
        refused=set(),
        exchanges=0,
        lookups=0,
    )
    assert not uncaptured["passed"]


def test_a_channel_not_captured_makes_the_run_incomplete() -> None:
    full = coverage.channels(browser=False, models=True, mcp=False, tracer=True)
    assert full["browser"]["status"] == "not_applicable" and full["host"]["status"] == "captured"
    good = {"r": {"passed": True}}
    assert coverage.summarize(full, good)["status"] == "complete"
    blind = coverage.channels(browser=False, models=True, mcp=False, tracer=False)
    summary = coverage.summarize(blind, good)
    assert summary["status"] == "incomplete" and "host not captured" in summary["warning"]
    assert coverage.summarize(full, {"r": {"passed": False}})["status"] == "incomplete"


def test_tracer_events_for_watched_containers_only() -> None:
    watch = {"e9d0ba4d0ad9453ab159f7a83c70100abcdef"}
    parse = tracer_parser(watch)
    mine = {
        "process_exec": {
            "process": {
                "docker": "e9d0ba4d0ad9453ab159f7a83c70100",
                "binary": "/usr/bin/python3",
                "arguments": "/opt/triage/agent.py",
                "pid": 7,
            }
        }
    }
    connect = {
        "process_kprobe": {
            "function_name": "tcp_connect",
            "process": {
                "docker": "e9d0ba4d0ad9453ab159f7a83c70100",
                "binary": "/usr/bin/python3",
                "pid": 7,
            },
            "args": [{"sock_arg": {"daddr": "10.40.0.10", "dport": 443}}],
        }
    }
    other = {
        "process_exec": {
            "process": {"docker": "c2304d9f019ce667ac7f4938f9f51cf", "binary": "/bin/sh"}
        }
    }
    assert parse(json.dumps(mine)) == {
        "source": "host",
        "type": "process.exec",
        "data": {
            "container": "e9d0ba4d0ad9453ab159f7a83c70100",
            "binary": "/usr/bin/python3",
            "pid": 7,
            "arguments": "/opt/triage/agent.py",
        },
    }
    event = parse(json.dumps(connect))
    assert (
        event is not None
        and event["type"] == "socket.connect"
        and event["data"]["dst"] == "10.40.0.10"
    )
    assert parse(json.dumps(other)) is None
    assert parse('level=info msg="Listening for events..."') is None


def test_kernel_tcp_replies_are_not_credited_to_the_running_process() -> None:
    """Seen live: the kernel's TCP acknowledgements for the gateway's upstream connection
    leave through ip_send_skb in interrupt context and carry whichever process was running.
    Only the packet's own protocol tells them apart from the container's UDP."""
    watch = {"2389872190b14671bee7c64295556caabcdef"}
    parse = tracer_parser(watch)
    process = {"docker": "2389872190b14671bee7c64295556ca", "binary": "/usr/local/bin/python"}

    def send(proto: int, daddr: str, dport: int) -> str:
        skb = {"saddr": "10.42.0.10", "daddr": daddr, "dport": dport, "proto": proto}
        return json.dumps(
            {
                "process_kprobe": {
                    "function_name": "ip_send_skb",
                    "process": process,
                    "args": [{"skb_arg": skb}],
                }
            }
        )

    assert parse(send(6, "160.79.104.10", 443)) is None
    udp = parse(send(17, "10.40.0.53", 53))
    assert udp is not None and udp["data"]["proto"] == "UDP" and udp["data"]["dport"] == 53
    icmp = parse(send(1, "1.1.1.1", 0))
    assert icmp is not None and icmp["data"]["proto"] == "ICMP"


def test_a_browser_agents_connections_to_its_browser_are_explained_by_the_observer() -> None:
    sockets = [{"binary": "node", "dst": "10.40.0.171", "dport": 9222, "proto": "TCP"}]
    seen = coverage.reconcile_connections(
        sockets,
        gateway="10.40.0.10",
        resolver="10.40.0.53",
        refused=set(),
        exchanges=0,
        lookups=0,
        browser="10.40.0.171:9222",
        browser_connections=2,
    )
    assert seen["passed"] and "1 to the browser" in seen["detail"]
    unrecorded = coverage.reconcile_connections(
        sockets,
        gateway="10.40.0.10",
        resolver="10.40.0.53",
        refused=set(),
        exchanges=0,
        lookups=0,
        browser="10.40.0.171:9222",
    )
    assert not unrecorded["passed"]
    not_a_browser_run = coverage.reconcile_connections(
        sockets, gateway="10.40.0.10", resolver="10.40.0.53", refused=set(), exchanges=0, lookups=0
    )
    assert not_a_browser_run["unexplained"][0]["to"] == "10.40.0.171:9222"
