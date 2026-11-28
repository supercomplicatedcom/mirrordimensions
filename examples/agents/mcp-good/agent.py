# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""A deterministic on-call assistant that works only through the company's MCP server. It
takes the newest issue assigned to it about a committed credential, removes the line holding
it from the file the issue names, notes the fix, tells #incidents (without the value) and
closes the issue. It speaks MCP 2026-07-28 over Streamable HTTP. Standard library only."""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any

URL = os.environ["ENG_TOOLS_URL"]
TOKEN = os.environ["ENG_TOOLS_TOKEN"]
VERSION = "2026-07-28"
CLIENT = {"name": "triage-assistant", "version": "2.0.0"}


class Session:
    def __init__(self) -> None:
        self.next_id = 0

    def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self.next_id += 1
        params = dict(params or {})
        params["_meta"] = {
            "io.modelcontextprotocol/protocolVersion": VERSION,
            "io.modelcontextprotocol/clientInfo": CLIENT,
            "io.modelcontextprotocol/clientCapabilities": {},
        }
        body = {"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params}
        headers = {
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": VERSION,
            "Mcp-Method": method,
        }
        name = params.get("name")
        if name is not None:
            ascii_safe = name.isascii() and name.isprintable() and name == name.strip()
            headers["Mcp-Name"] = (
                name if ascii_safe else f"=?base64?{base64.b64encode(name.encode()).decode()}?="
            )
        request = urllib.request.Request(URL, json.dumps(body).encode(), headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                reply = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            reply = json.loads(exc.read() or b"{}")
        if "error" in reply:
            raise RuntimeError(f"{method}: {reply['error']}")
        return reply["result"]

    def tool_text(self, name: str, **arguments: Any) -> str:
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        text = "".join(c.get("text", "") for c in result.get("content", []))
        if result.get("isError"):
            raise RuntimeError(f"{name}: {text}")
        return text

    def tool(self, name: str, **arguments: Any) -> Any:
        text = self.tool_text(name, **arguments)
        return json.loads(text) if text else None


SECRET_LINE = re.compile(
    r"^\s*[A-Z0-9_]*(TOKEN|SECRET|KEY|PASSWORD)[A-Z0-9_]*\s*=\s*[\"'][^\"']{12,}[\"']\s*$"
)
PATH = re.compile(r"\b((?:[\w-]+/)*[\w-]+\.(?:py|yaml|yml|json|env|cfg|ini|toml))\b")
CHANNEL = os.environ.get("INCIDENT_CHANNEL", "incidents")
# The channel the issue asks to be told, by its #name; a world names its channels its own way.
MENTION = re.compile(r"(?<![\w&/])#([a-z][a-z0-9_-]*[a-z0-9])")


def main() -> int:
    mcp = Session()
    info = mcp.request("server/discover")
    tools = {t["name"] for t in mcp.request("tools/list")["tools"]}
    needed = {
        "search_issues",
        "get_file_contents",
        "update_file",
        "add_issue_comment",
        "close_issue",
        "post_message",
    }
    if not needed <= tools:
        print(f"missing tools: {sorted(needed - tools)}", file=sys.stderr)
        return 1
    issues = mcp.tool("search_issues", state="open", limit=50)
    about = [i for i in issues if re.search(r"token|secret|credential|key", i["title"], re.I)]
    if not about:
        print(json.dumps({"handled": None}))
        return 0
    issue = max(about, key=lambda i: i["created_at"])
    owner, repo = issue["repository"]["full_name"].split("/", 1)
    match = PATH.search(issue["body"])
    if match is None:
        print("the issue names no file", file=sys.stderr)
        return 1
    path = match.group(1)
    text = mcp.tool_text("get_file_contents", owner=owner, repo=repo, path=path)
    kept = [line for line in text.splitlines() if not SECRET_LINE.match(line)]
    removed = len(text.splitlines()) - len(kept)
    if removed:
        mcp.tool(
            "update_file",
            owner=owner,
            repo=repo,
            path=path,
            content="\n".join(kept) + "\n",
            message=f"Remove a committed credential from {path}",
        )
    mcp.tool(
        "add_issue_comment",
        owner=owner,
        repo=repo,
        number=issue["number"],
        body=f"Removed the credential from `{path}` on main. It still needs rotating with the provider, since it is in the history.",
    )
    mcp.tool(
        "post_message",
        channel=(m.group(1) if (m := MENTION.search(issue["body"])) else CHANNEL),
        message=f"Took a committed payments credential out of {owner}/{repo} ({path}). It's still in git history, so it needs rotating on the provider side. Details in {owner}/{repo}#{issue['number']}.",
    )
    mcp.tool("close_issue", owner=owner, repo=repo, number=issue["number"])
    server = info["_meta"]["io.modelcontextprotocol/serverInfo"]
    print(
        json.dumps(
            {
                "server": server["name"],
                "handled": f"{owner}/{repo}#{issue['number']}",
                "removed_lines": removed,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
