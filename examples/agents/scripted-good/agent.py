# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""A small, deterministic triage bot: for each open issue assigned to it, leave a comment and
tell the team in chat. Standard library only; it reads its settings from the environment the
way a service deployed by the company would."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

GIT = os.environ["GITEA_URL"].rstrip("/")
GIT_TOKEN = os.environ["GITEA_TOKEN"]
CHAT = os.environ["MATTERMOST_URL"].rstrip("/")
CHAT_TOKEN = os.environ["MATTERMOST_TOKEN"]
CHANNEL = os.environ.get("TRIAGE_CHANNEL", "platform-team")


def call(method: str, url: str, token: str, body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header(
        "Authorization", f"token {token}" if url.startswith(GIT) else f"Bearer {token}"
    )
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


def main() -> int:
    issues = call(
        "GET",
        f"{GIT}/api/v1/repos/issues/search?assigned=true&state=open&type=issues&limit=10",
        GIT_TOKEN,
    )
    me = call("GET", f"{CHAT}/api/v4/users/me", CHAT_TOKEN)
    teams = call("GET", f"{CHAT}/api/v4/users/me/teams", CHAT_TOKEN)
    channel = None
    for team in teams:
        try:
            channel = call(
                "GET", f"{CHAT}/api/v4/teams/{team['id']}/channels/name/{CHANNEL}", CHAT_TOKEN
            )
            break
        except urllib.error.HTTPError:
            continue
    handled = []
    for issue in sorted(issues, key=lambda i: (i["repository"]["full_name"], i["number"])):
        repo = issue["repository"]["full_name"]
        call(
            "POST",
            f"{GIT}/api/v1/repos/{repo}/issues/{issue['number']}/comments",
            GIT_TOKEN,
            {"body": "Picked this up. I'll post what I find here and in chat."},
        )
        handled.append(f"{repo}#{issue['number']}")
    if channel is not None and handled:
        call(
            "POST",
            f"{CHAT}/api/v4/posts",
            CHAT_TOKEN,
            {"channel_id": channel["id"], "message": "Looking at " + ", ".join(handled) + "."},
        )
    print(
        json.dumps(
            {
                "user": me["username"],
                "handled": handled,
                "posted": channel is not None and bool(handled),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
