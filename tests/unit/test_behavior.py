# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Surfaces, locate/describe/exposed, and every rule action, without a gateway."""

from __future__ import annotations

import json

import pytest

from mirrordimensions.network.payloads.behavior import Request, Rules, compile_path, edit_response
from mirrordimensions.twins.profile import Profile

GITEA = Profile("gitea")
MATTERMOST = Profile("mattermost")


def _rules(rules: list[dict[str, object]], profile: Profile = GITEA, seed: int = 7) -> Rules:
    return Rules(rules, profile.table, profile.errors, seed)


def _req(method: str, path: str, body: bytes = b"") -> Request:
    return Request(method=method, path=path, headers={}, body=body)


def test_path_patterns() -> None:
    regex = compile_path("/api/v1/repos/{owner}/{repo}/contents/{path+}")
    match = regex.match("/api/v1/repos/eng/billing/contents/config/settings.py")
    assert match is not None
    assert match.groupdict() == {"owner": "eng", "repo": "billing", "path": "config/settings.py"}
    assert compile_path("/{owner}/{repo}").match("/eng/billing/extra") is None


def test_locate_and_describe() -> None:
    loc = GITEA.locate("GET", "/api/v1/repos/eng/billing-service/issues/14?foo=1")
    assert (loc.surface, loc.resource, loc.access) == (
        "issue.read",
        "issue:eng/billing-service#14",
        "read",
    )
    assert (
        GITEA.describe("PUT", "/api/v1/repos/eng/billing/contents/config/settings.py")
        == "Commits a change to config/settings.py"
    )
    assert GITEA.locate("GET", "/somewhere/else/entirely/x/y").surface == "unknown"


def test_exposed_lists_every_resource_a_response_carried() -> None:
    issues = json.dumps([{"number": n, "title": f"t{n}"} for n in range(1, 31)]).encode()
    exposed = GITEA.exposed("GET", "/api/v1/repos/eng/billing/issues", issues)
    assert len(exposed) == 30
    assert exposed[0] == "issue:eng/billing#1"
    posts = json.dumps(
        {"order": ["a", "b"], "posts": {"a": {"id": "a"}, "b": {"id": "b"}}}
    ).encode()
    assert sorted(MATTERMOST.exposed("GET", "/api/v4/channels/x/posts", posts)) == [
        "post:a",
        "post:b",
    ]


def test_profiles_cover_the_scenarios_surfaces() -> None:
    gitea = {s["id"] for s in GITEA.surfaces}
    for needed in (
        "issue.read",
        "comment.create",
        "file.write",
        "pull.create",
        "branch.delete",
        "deploykey.create",
        "hook.create",
        "token.create",
        "git.push",
        "signin.page",
        "repo.search",
        "tag.list",
    ):
        assert needed in gitea, needed
    chat = {s["id"] for s in MATTERMOST.surfaces}
    for needed in (
        "post.create",
        "thread.read",
        "dm.create",
        "channel.member.add",
        "team.member.add",
        "post.search",
    ):
        assert needed in chat, needed


def test_input_rules_reject_with_the_products_error() -> None:
    rules = _rules(
        [
            {
                "name": "limit",
                "match": {"surface": "file.write"},
                "input": {"max_body_bytes": 10, "on_reject": "too_large"},
            }
        ]
    )
    out = rules.apply(_req("PUT", "/api/v1/repos/a/b/contents/x", b"x" * 11), 0)
    assert out.respond is not None
    assert out.respond[0] == 413
    assert out.applied == [{"rule": "limit", "changed": ["max_body_bytes"]}]
    assert rules.apply(_req("PUT", "/api/v1/repos/a/b/contents/x", b"x"), 0).respond is None


def test_forbid_require_set_and_rename_fields() -> None:
    rules = _rules(
        [
            {
                "name": "f",
                "match": {"surface": "issue.create"},
                "input": {"forbid_fields": ["assignees"]},
            },
            {
                "name": "s",
                "match": {"surface": "comment.create"},
                "input": {"set_fields": {"x": 1}, "rename_fields": {"b": "body"}},
            },
        ]
    )
    out = rules.apply(_req("POST", "/api/v1/repos/a/b/issues", b'{"assignees":[]}'), 0)
    assert out.respond is not None
    assert out.respond[0] == 403
    out = rules.apply(_req("POST", "/api/v1/repos/a/b/issues/1/comments", b'{"b":"hi"}'), 0)
    assert json.loads(out.request_body or b"") == {"x": 1, "body": "hi"}


def test_error_templates_match_the_products_header_order() -> None:
    status, headers, body = _rules([]).error("forbidden")
    assert status == 403
    assert [h[0] for h in headers] == [
        "Cache-Control",
        "Content-Type",
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Date",
    ]
    assert json.loads(body.decode().replace("{host}", "x"))["url"] == "https://x/api/swagger"
    status, headers, body = _rules([], MATTERMOST).error("forbidden")
    request_id = json.loads(body)["request_id"]
    assert len(request_id) == 26
    assert dict(headers)["X-Request-Id"] == request_id


def test_fail_rate_is_deterministic_for_a_seed() -> None:
    def outcomes(seed: int) -> list[bool]:
        rules = _rules(
            [
                {
                    "name": "flaky",
                    "match": {"surface": "commit.status"},
                    "output": {"fail": {"rate": 0.3, "error": "unavailable"}},
                }
            ],
            seed=seed,
        )
        return [
            rules.apply(_req("GET", "/api/v1/repos/a/b/commits/main/status"), 0).respond is not None
            for _ in range(40)
        ]

    assert outcomes(1) == outcomes(1)
    assert outcomes(1) != outcomes(2)
    assert 3 < sum(outcomes(1)) < 25


def test_delay_rate_limit_and_respond() -> None:
    rules = _rules(
        [
            {
                "name": "slow",
                "match": {"surface": "repo.search"},
                "output": {"delay_ms": [800, 900]},
            },
            {
                "name": "limit",
                "match": {"surface": "issue.list"},
                "output": {"rate_limit": {"calls": 2, "per_s": 60}},
            },
            {
                "name": "info",
                "match": {"method": "GET", "path": "/api/internal/build-info"},
                "output": {"respond": {"status": 200, "json": {"version": "4.12.1"}}},
            },
        ]
    )
    assert 800 <= rules.apply(_req("GET", "/api/v1/repos/search"), 0).delay_ms <= 900
    statuses = [rules.apply(_req("GET", "/api/v1/repos/a/b/issues"), 0).respond for _ in range(3)]
    assert statuses[:2] == [None, None]
    assert statuses[2] is not None
    assert statuses[2][0] == 429
    respond = rules.apply(_req("GET", "/api/internal/build-info"), 0).respond
    assert respond is not None
    assert respond[2] == b'{"version":"4.12.1"}'


def test_scoped_rules_apply_to_one_identity_only() -> None:
    rules = _rules(
        [
            {
                "name": "only",
                "match": {"surface": "repo.search"},
                "when": {"agent": "ops-assistant"},
                "output": {"delay_ms": 5},
            }
        ]
    )
    assert (
        rules.apply(
            Request("GET", "/api/v1/repos/search", {}, b"", identity="ops-assistant"), 0
        ).delay_ms
        == 5
    )
    assert (
        rules.apply(Request("GET", "/api/v1/repos/search", {}, b"", identity="someone"), 0).delay_ms
        == 0
    )


@pytest.mark.parametrize(
    ("edits", "expected"),
    [
        ([{"remove_fields": ["email"]}], {"login": "dana"}),
        ([{"set_fields": {"login": "x"}}], {"login": "x", "email": "d@x"}),
        (
            [{"insert_text": {"field": "login", "text": "NOTE"}}],
            {"login": "dana\n\nNOTE", "email": "d@x"},
        ),
    ],
)
def test_output_edits(edits: list[dict[str, object]], expected: dict[str, str]) -> None:
    body = edit_response(b'{"login":"dana","email":"d@x"}', edits)
    assert json.loads(body) == expected
    assert b": " not in body  # compact, like the Go servers


def test_page_size_and_non_json_bodies() -> None:
    assert json.loads(edit_response(b"[1,2,3,4]", [{"page_size": 2}])) == [1, 2]
    assert edit_response(b"<html>", [{"remove_fields": ["x"]}]) == b"<html>"
