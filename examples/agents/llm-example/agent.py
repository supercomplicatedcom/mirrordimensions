# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""A minimal real agent: for each open issue assigned to it, ask Claude for a short triage
note and post it as a comment. Settings come from the environment, as deployed."""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from typing import Any

import anthropic

GIT = os.environ["GITEA_URL"].rstrip("/")
GIT_TOKEN = os.environ["GITEA_TOKEN"]


def gitea(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    request = urllib.request.Request(
        f"{GIT}/api/v1{path}", data=json.dumps(body).encode() if body else None, method=method
    )
    request.add_header("Authorization", f"token {GIT_TOKEN}")
    request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
    return json.loads(raw) if raw else None


def main() -> int:
    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY from the environment
    issues = gitea("GET", "/repos/issues/search?assigned=true&state=open&type=issues&limit=5")
    for issue in issues:
        response = client.beta.messages.create(
            model="claude-opus-5-5",
            max_tokens=1024,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system="You triage engineering issues. Reply with three short lines: likely cause, first check, owner team.",
            messages=[
                {"role": "user", "content": f"Issue: {issue['title']}\n\n{issue.get('body') or ''}"}
            ],
        )
        if response.stop_reason == "refusal":
            print(f"skipped {issue['number']}: declined", file=sys.stderr)
            continue
        note = "".join(block.text for block in response.content if block.type == "text").strip()
        repo = issue["repository"]["full_name"]
        gitea("POST", f"/repos/{repo}/issues/{issue['number']}/comments", {"body": note})
        print(
            json.dumps(
                {"issue": f"{repo}#{issue['number']}", "tokens": response.usage.output_tokens}
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
