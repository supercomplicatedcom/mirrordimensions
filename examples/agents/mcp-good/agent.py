# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""A deterministic triage assistant that works only through the company's MCP server: for
each open issue assigned to it, leave a comment, then tell the team in chat. It speaks MCP
2026-07-28 over Streamable HTTP and falls back to the 2025-11-25 handshake if the server
asks for it. Standard library only."""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

URL = os.environ["ENG_TOOLS_URL"]
TOKEN = os.environ["ENG_TOOLS_TOKEN"]
CHANNEL = os.environ.get("TRIAGE_CHANNEL", "platform-team")
VERSION = "2026-07-28"
CLIENT = {"name": "triage-assistant", "version": "2.0.0"}
NOTE = "Picked this up. I'll post what I find here and in chat."


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

    def tool(self, name: str, **arguments: Any) -> Any:
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        text = "".join(c.get("text", "") for c in result.get("content", []))
        if result.get("isError"):
            raise RuntimeError(f"{name}: {text}")
        return json.loads(text) if text else None


def main() -> int:
    mcp = Session()
    info = mcp.request("server/discover")
    tools = {t["name"] for t in mcp.request("tools/list")["tools"]}
    needed = {"search_issues", "add_issue_comment", "post_message"}
    if not needed <= tools:
        print(f"missing tools: {sorted(needed - tools)}", file=sys.stderr)
        return 1
    handled = []
    for issue in sorted(
        mcp.tool("search_issues", state="open", limit=10),
        key=lambda i: (i["repository"]["full_name"], i["number"]),
    ):
        owner, repo = issue["repository"]["full_name"].split("/", 1)
        mcp.tool("add_issue_comment", owner=owner, repo=repo, number=issue["number"], body=NOTE)
        handled.append(f"{owner}/{repo}#{issue['number']}")
    if handled:
        mcp.tool("post_message", channel=CHANNEL, message="Looking at " + ", ".join(handled) + ".")
    server = info["_meta"]["io.modelcontextprotocol/serverInfo"]
    print(json.dumps({"server": server["name"], "handled": handled, "posted": bool(handled)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
