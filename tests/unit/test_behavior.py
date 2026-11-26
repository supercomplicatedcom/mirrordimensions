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


# Every request shape the profiles know, with where it is located and how it is described.
# Each scenario's requests (and the browser agent's pages) are among these; a surface added
# to a profile must be added here, or the test below fails.
OWN, R = "elmstead", "billing-service"
CH = "k3j4h5k3j4h5k3j4h5k3j4h5k3"
SHAPES: list[tuple[str, str, str, str, bytes, str | None, str]] = [
    # (product, surface, method, path, request body, resource, sentence)
    ("gitea", "home.page", "GET", "/", b"", None, "Opens the home page"),
    (
        "gitea",
        "assets",
        "GET",
        "/assets/js/index.7rwHo1n3.js",
        b"",
        None,
        "Loads the page's styles and scripts",
    ),
    ("gitea", "avatar", "GET", "/avatars/4db19a60cb", b"", None, "Loads a profile picture"),
    (
        "gitea",
        "user.avatar",
        "GET",
        "/user/avatar/astrid.mbeki/48",
        b"",
        None,
        "Loads a profile picture",
    ),
    ("gitea", "live.events", "GET", "/-/ws", b"", None, "Opens the live connection"),
    ("gitea", "repo.search.page", "GET", "/repo/search?q=docs", b"", None, "Searches repositories"),
    ("gitea", "explore.repos", "GET", "/explore/repos", b"", None, "Browses the repositories"),
    ("gitea", "dashboard.issues", "GET", "/issues", b"", None, "Opens its issues"),
    ("gitea", "link.follow", "POST", "/-/fetch-redirect", b"", None, "Follows a link"),
    (
        "gitea",
        "heatmap",
        "GET",
        "/astrid.mbeki/-/heatmap",
        b"",
        "user:astrid.mbeki",
        "Loads the activity chart for astrid.mbeki",
    ),
    (
        "gitea",
        "issue.history",
        "GET",
        f"/{OWN}/{R}/issues/33/content-history/overview",
        b"",
        f"issue:{OWN}/{R}#33",
        "Checks the edit history of issue #33",
    ),
    (
        "gitea",
        "issue.comment.form",
        "POST",
        f"/{OWN}/{R}/issues/33/comments",
        b"",
        f"issue:{OWN}/{R}#33",
        "Comments on issue #33",
    ),
    ("gitea", "signin.page", "GET", "/user/login", b"", None, "Opens the sign-in page"),
    ("gitea", "signin.submit", "POST", "/user/login", b"", None, "Signs in"),
    ("gitea", "repo.page", "GET", f"/{OWN}/{R}", b"", f"repo:{OWN}/{R}", f"Opens {OWN}/{R}"),
    (
        "gitea",
        "issue.page",
        "GET",
        f"/{OWN}/{R}/issues/33",
        b"",
        f"issue:{OWN}/{R}#33",
        f"Opens issue #33 in {R}",
    ),
    (
        "gitea",
        "file.page",
        "GET",
        f"/{OWN}/{R}/src/branch/main/config/settings.py",
        b"",
        f"file:{OWN}/{R}/config/settings.py",
        "Views config/settings.py",
    ),
    (
        "gitea",
        "git.refs",
        "GET",
        f"/{OWN}/{R}.git/info/refs?service=git-upload-pack",
        b"",
        f"repo:{OWN}/{R}",
        f"Fetches {R} with git",
    ),
    (
        "gitea",
        "git.fetch",
        "POST",
        f"/{OWN}/{R}.git/git-upload-pack",
        b"",
        f"repo:{OWN}/{R}",
        f"Downloads {R} with git",
    ),
    (
        "gitea",
        "git.push",
        "POST",
        f"/{OWN}/{R}.git/git-receive-pack",
        b"",
        f"repo:{OWN}/{R}",
        f"Pushes to {R}",
    ),
    ("gitea", "user.self", "GET", "/api/v1/user", b"", None, "Checks who it is signed in as"),
    (
        "gitea",
        "user.read",
        "GET",
        "/api/v1/users/nasser.walsh",
        b"",
        "user:nasser.walsh",
        "Looks up nasser.walsh",
    ),
    (
        "gitea",
        "repo.search",
        "GET",
        "/api/v1/repos/search?q=platform-docs&limit=5",
        b"",
        None,
        "Searches repositories",
    ),
    (
        "gitea",
        "issue.search",
        "GET",
        "/api/v1/repos/issues/search?assigned=true",
        b"",
        None,
        "Searches issues",
    ),
    (
        "gitea",
        "repo.read",
        "GET",
        f"/api/v1/repos/{OWN}/{R}",
        b"",
        f"repo:{OWN}/{R}",
        f"Reads {OWN}/{R}",
    ),
    (
        "gitea",
        "repo.delete",
        "DELETE",
        f"/api/v1/repos/{OWN}/{R}",
        b"",
        f"repo:{OWN}/{R}",
        f"Deletes {OWN}/{R}",
    ),
    (
        "gitea",
        "tree.read",
        "GET",
        f"/api/v1/repos/{OWN}/{R}/git/trees/main?recursive=1",
        b"",
        f"repo:{OWN}/{R}",
        f"Lists files in {R}",
    ),
    (
        "gitea",
        "file.read",
        "GET",
        f"/api/v1/repos/{OWN}/{R}/contents/config/settings.py?ref=main",
        b"",
        f"file:{OWN}/{R}/config/settings.py",
        "Reads config/settings.py",
    ),
    (
        "gitea",
        "file.raw",
        "GET",
        f"/api/v1/repos/{OWN}/{R}/raw/README.md",
        b"",
        f"file:{OWN}/{R}/README.md",
        "Reads README.md",
    ),
    (
        "gitea",
        "file.write",
        "PUT",
        f"/api/v1/repos/{OWN}/{R}/contents/config/settings.py",
        b"{}",
        f"file:{OWN}/{R}/config/settings.py",
        "Commits a change to config/settings.py",
    ),
    (
        "gitea",
        "file.create",
        "POST",
        f"/api/v1/repos/{OWN}/{R}/contents/notes/sync.txt",
        b"{}",
        f"file:{OWN}/{R}/notes/sync.txt",
        "Adds notes/sync.txt",
    ),
    (
        "gitea",
        "file.delete",
        "DELETE",
        f"/api/v1/repos/{OWN}/{R}/contents/old.txt",
        b"",
        f"file:{OWN}/{R}/old.txt",
        "Deletes old.txt",
    ),
    (
        "gitea",
        "commit.list",
        "GET",
        f"/api/v1/repos/{OWN}/{R}/commits",
        b"",
        f"repo:{OWN}/{R}",
        f"Lists commits in {R}",
    ),
    (
        "gitea",
        "commit.status",
        "GET",
        f"/api/v1/repos/{OWN}/{R}/commits/main/status",
        b"",
        f"repo:{OWN}/{R}",
        f"Checks the build status in {R}",
    ),
    (
        "gitea",
        "tag.list",
        "GET",
        f"/api/v1/repos/{OWN}/{R}/tags",
        b"",
        f"repo:{OWN}/{R}",
        f"Lists tags in {R}",
    ),
    (
        "gitea",
        "branch.list",
        "GET",
        f"/api/v1/repos/{OWN}/{R}/branches",
        b"",
        f"repo:{OWN}/{R}",
        f"Lists branches in {R}",
    ),
    (
        "gitea",
        "branch.delete",
        "DELETE",
        f"/api/v1/repos/{OWN}/{R}/branches/feature/old",
        b"",
        f"branch:{OWN}/{R}/feature/old",
        f"Deletes branch feature/old in {R}",
    ),
    (
        "gitea",
        "issue.list",
        "GET",
        f"/api/v1/repos/{OWN}/{R}/issues?state=open",
        b"",
        f"repo:{OWN}/{R}",
        f"Lists issues in {R}",
    ),
    (
        "gitea",
        "issue.read",
        "GET",
        f"/api/v1/repos/{OWN}/{R}/issues/33",
        b"",
        f"issue:{OWN}/{R}#33",
        "Reads issue #33",
    ),
    (
        "gitea",
        "issue.create",
        "POST",
        f"/api/v1/repos/{OWN}/{R}/issues",
        b"{}",
        f"repo:{OWN}/{R}",
        f"Opens an issue in {R}",
    ),
    (
        "gitea",
        "issue.edit",
        "PATCH",
        f"/api/v1/repos/{OWN}/{R}/issues/33",
        b"{}",
        f"issue:{OWN}/{R}#33",
        "Updates issue #33",
    ),
    (
        "gitea",
        "comment.list",
        "GET",
        f"/api/v1/repos/{OWN}/{R}/issues/33/comments",
        b"",
        f"issue:{OWN}/{R}#33",
        "Reads the comments on issue #33",
    ),
    (
        "gitea",
        "comment.create",
        "POST",
        f"/api/v1/repos/{OWN}/{R}/issues/33/comments",
        b"{}",
        f"issue:{OWN}/{R}#33",
        "Comments on issue #33",
    ),
    (
        "gitea",
        "label.add",
        "POST",
        f"/api/v1/repos/{OWN}/{R}/issues/33/labels",
        b"{}",
        f"issue:{OWN}/{R}#33",
        "Labels issue #33",
    ),
    (
        "gitea",
        "pull.list",
        "GET",
        f"/api/v1/repos/{OWN}/{R}/pulls",
        b"",
        f"repo:{OWN}/{R}",
        f"Lists pull requests in {R}",
    ),
    (
        "gitea",
        "pull.create",
        "POST",
        f"/api/v1/repos/{OWN}/{R}/pulls",
        b"{}",
        f"repo:{OWN}/{R}",
        f"Opens a pull request in {R}",
    ),
    (
        "gitea",
        "pull.merge",
        "POST",
        f"/api/v1/repos/{OWN}/{R}/pulls/4/merge",
        b"{}",
        f"pull:{OWN}/{R}#4",
        "Merges pull request #4",
    ),
    (
        "gitea",
        "deploykey.create",
        "POST",
        f"/api/v1/repos/{OWN}/{R}/keys",
        b"{}",
        f"repo:{OWN}/{R}",
        f"Adds a deploy key to {R}",
    ),
    (
        "gitea",
        "hook.create",
        "POST",
        f"/api/v1/repos/{OWN}/{R}/hooks",
        b"{}",
        f"repo:{OWN}/{R}",
        f"Adds a webhook to {R}",
    ),
    (
        "gitea",
        "token.create",
        "POST",
        "/api/v1/users/astrid.mbeki/tokens",
        b"{}",
        "user:astrid.mbeki",
        "Creates an access token for astrid.mbeki",
    ),
    (
        "gitea",
        "collaborator.add",
        "PUT",
        f"/api/v1/repos/{OWN}/{R}/collaborators/x.y",
        b"{}",
        f"repo:{OWN}/{R}",
        f"Gives x.y access to {R}",
    ),
    ("mattermost", "signin.page", "GET", "/login", b"", None, "Opens the sign-in page"),
    ("mattermost", "signin.submit", "POST", "/api/v4/users/login", b"{}", None, "Signs in"),
    ("mattermost", "websocket", "GET", "/api/v4/websocket", b"", None, "Opens the live connection"),
    (
        "mattermost",
        "user.self",
        "GET",
        "/api/v4/users/me",
        b"",
        None,
        "Checks who it is signed in as",
    ),
    (
        "mattermost",
        "user.read",
        "GET",
        f"/api/v4/users/{CH}",
        b"",
        f"user:{CH}",
        "Looks up a colleague",
    ),
    (
        "mattermost",
        "user.by_name",
        "GET",
        "/api/v4/users/username/nasser.walsh",
        b"",
        "user:nasser.walsh",
        "Looks up nasser.walsh",
    ),
    ("mattermost", "team.list", "GET", "/api/v4/users/me/teams", b"", None, "Lists its teams"),
    (
        "mattermost",
        "channel.list",
        "GET",
        "/api/v4/users/me/teams/t1/channels",
        b"",
        None,
        "Lists its channels",
    ),
    (
        "mattermost",
        "channel.by_name",
        "GET",
        "/api/v4/teams/t1/channels/name/incidents",
        b"",
        "channel:incidents",
        "Opens #incidents",
    ),
    (
        "mattermost",
        "channel.posts",
        "GET",
        f"/api/v4/channels/{CH}/posts?per_page=60",
        b"",
        f"channel:{CH}",
        "Reads a channel",
    ),
    (
        "mattermost",
        "thread.read",
        "GET",
        "/api/v4/posts/p1/thread",
        b"",
        "post:p1",
        "Reads a thread",
    ),
    (
        "mattermost",
        "post.create",
        "POST",
        "/api/v4/posts",
        json.dumps({"channel_id": CH, "message": "done"}).encode(),
        f"channel:{CH}",
        "Posts a message",
    ),
    ("mattermost", "post.edit", "PUT", "/api/v4/posts/p1", b"{}", "post:p1", "Edits a message"),
    (
        "mattermost",
        "post.search",
        "POST",
        "/api/v4/teams/t1/posts/search",
        b"{}",
        None,
        "Searches messages",
    ),
    (
        "mattermost",
        "dm.create",
        "POST",
        "/api/v4/channels/direct",
        b"[]",
        None,
        "Starts a direct message",
    ),
    (
        "mattermost",
        "channel.member.add",
        "POST",
        f"/api/v4/channels/{CH}/members",
        b"{}",
        f"channel:{CH}",
        "Adds someone to a channel",
    ),
    (
        "mattermost",
        "team.member.add",
        "POST",
        "/api/v4/teams/t1/members",
        b"{}",
        "team:t1",
        "Adds someone to a team",
    ),
    (
        "mattermost",
        "file.read",
        "GET",
        "/api/v4/files/f1",
        b"",
        "file:f1",
        "Downloads a shared file",
    ),
]
DEVICES = Profile("device-platform")
SHAPES += [
    ("device-platform", "health", "GET", "/healthz", b"", None, "Checks the service is up"),
    (
        "device-platform",
        "user.self",
        "GET",
        "/api/v1/me",
        b"",
        None,
        "Checks who it is signed in as",
    ),
    ("device-platform", "site.list", "GET", "/api/v1/sites", b"", None, "Lists its sites"),
    (
        "device-platform",
        "site.read",
        "GET",
        "/api/v1/sites/hq",
        b"",
        "site:hq",
        "Opens the plan of hq",
    ),
    (
        "device-platform",
        "device.list",
        "GET",
        "/api/v1/devices?floor=f2",
        b"",
        None,
        "Lists devices",
    ),
    (
        "device-platform",
        "device.read",
        "GET",
        "/api/v1/devices/main-entrance",
        b"",
        "device:main-entrance",
        "Looks at main-entrance",
    ),
    (
        "device-platform",
        "device.state",
        "GET",
        "/api/v1/devices/main-entrance/state",
        b"",
        "device:main-entrance",
        "Reads the state of main-entrance",
    ),
    (
        "device-platform",
        "device.telemetry",
        "GET",
        "/api/v1/devices/conf-b-climate/telemetry",
        b"",
        "device:conf-b-climate",
        "Reads readings from conf-b-climate",
    ),
    (
        "device-platform",
        "device.history",
        "GET",
        "/api/v1/devices/main-entrance/commands",
        b"",
        "device:main-entrance",
        "Reads the command history of main-entrance",
    ),
    (
        "device-platform",
        "device.command",
        "POST",
        "/api/v1/devices/server-room-door/commands",
        b'{"command": "unlock"}',
        "device:server-room-door",
        "Sends unlock to server-room-door",
    ),
    (
        "device-platform",
        "event.list",
        "GET",
        "/api/v1/events",
        b"",
        "audit-log",
        "Reads the access log",
    ),
]
PROFILES = {"gitea": GITEA, "mattermost": MATTERMOST, "device-platform": DEVICES}


@pytest.mark.parametrize(
    ("product", "surface", "method", "path", "body", "resource", "sentence"), SHAPES
)
def test_every_request_shape_is_located_and_described(
    product: str,
    surface: str,
    method: str,
    path: str,
    body: bytes,
    resource: str | None,
    sentence: str,
) -> None:
    loc = PROFILES[product].locate(method, path, body)
    assert (loc.surface, loc.resource, loc.sentence) == (surface, resource, sentence)


def test_every_surface_has_a_request_shape_above() -> None:
    for product, profile in PROFILES.items():
        listed = {s for p, s, *_ in SHAPES if p == product}
        assert {s["id"] for s in profile.surfaces} == listed, product


def test_the_adapters_locate_and_describe_an_exchange() -> None:
    from mirrordimensions.twins.base import get_twin
    from mirrordimensions.twins.profile import ResourceRef

    gitea, chat = get_twin("gitea"), get_twin("mattermost")
    assert gitea is not None and chat is not None
    read = {"method": "GET", "path": f"/api/v1/repos/{OWN}/{R}/contents/config/settings.py"}
    assert gitea.locate(read) == ResourceRef(
        "file.read", f"file:{OWN}/{R}/config/settings.py", "read"
    )
    assert gitea.describe(read) == "Reads config/settings.py"
    assert gitea.locate({"method": "GET", "path": "/no/such/page/at/all"}) is None
    post = {
        "method": "POST",
        "path": "/api/v4/posts",
        "req_body": json.dumps({"channel_id": CH}),
        "names": {f"channel:{CH}": "channel:incidents"},
    }
    assert chat.describe(post) == "Posts in #incidents"
    assert chat.locate(post) == ResourceRef("post.create", "channel:incidents", "write")


def test_names_learned_from_responses_name_later_requests() -> None:
    teams = json.dumps([{"id": "t1", "name": "elmstead"}]).encode()
    assert MATTERMOST.table.learn("GET", "/api/v4/users/me/teams", teams) == {
        "team:t1": "team:elmstead"
    }
    channel = json.dumps({"id": CH, "name": "incidents", "display_name": "Incidents"}).encode()
    names = MATTERMOST.table.learn("GET", "/api/v4/teams/t1/channels/name/incidents", channel)
    assert names == {f"channel:{CH}": "channel:incidents"}
    posts = MATTERMOST.locate("GET", f"/api/v4/channels/{CH}/posts", b"", names)
    assert (posts.resource, posts.sentence) == ("channel:incidents", "Reads #incidents")
    # A body that is not JSON, or lacks the field, leaves the resource unnamed.
    assert MATTERMOST.locate("POST", "/api/v4/posts", b"not json").resource is None
    assert MATTERMOST.table.learn("GET", "/api/v4/users/me/teams", b"<html>") == {}
