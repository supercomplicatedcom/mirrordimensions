# SPDX-License-Identifier: Apache-2.0
"""Turn an exchange with a world MCP server into `mcp.message` and `mcp.call` events.

Runs inside the gateway, next to edge.py, on every exchange routed to an `mcp-server` app.
Standard library only. Bodies are JSON (one JSON-RPC message) or an SSE stream of them.
"""

from __future__ import annotations

import json
import re
from typing import Any

MAX_TEXT = 2000
_REF = re.compile(r"\{([^{}|]+)(?:\|[^{}]*)?\}")


def messages(body: bytes | None, content_type: str) -> list[dict[str, Any]]:
    """The JSON-RPC messages in a request or response body."""
    if not body:
        return []
    texts: list[str] = []
    if content_type.startswith("text/event-stream"):
        for event in body.decode("utf-8", "replace").split("\n\n"):
            data = "\n".join(
                line[5:].lstrip() for line in event.splitlines() if line.startswith("data:")
            )
            if data:
                texts.append(data)
    else:
        texts.append(body.decode("utf-8", "replace"))
    out: list[dict[str, Any]] = []
    for text in texts:
        try:
            parsed = json.loads(text)
        except ValueError:
            continue
        for item in parsed if isinstance(parsed, list) else [parsed]:
            if isinstance(item, dict) and item.get("jsonrpc") == "2.0":
                out.append(item)
    return out


def _clip(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "..."


def _fill(template: str | None, args: dict[str, Any]) -> str | None:
    if not template:
        return template
    return _REF.sub(lambda m: str(args.get(m.group(1), "{" + m.group(1) + "}")), template)


def events(
    request_body: bytes | None,
    request_type: str,
    response_body: bytes | None,
    response_type: str,
    surfaces: dict[str, dict[str, Any]],
    secrets: list[str],
) -> list[tuple[str, dict[str, Any]]]:
    """(event type, data) pairs, in order: client messages, server messages, then calls."""
    out: list[tuple[str, dict[str, Any]]] = []
    sent = messages(request_body, request_type)
    received = messages(response_body, response_type)
    for direction, batch in (("client", sent), ("server", received)):
        for message in batch:
            params = message.get("params") if isinstance(message.get("params"), dict) else {}
            meta = params.get("_meta") or {}
            data: dict[str, Any] = {
                "direction": direction,
                "kind": "request"
                if "method" in message and "id" in message
                else "notification"
                if "method" in message
                else "error"
                if "error" in message
                else "response",
                "id": message.get("id"),
                "method": message.get("method"),
                "version": meta.get("io.modelcontextprotocol/protocolVersion")
                or params.get("protocolVersion"),
                "body": _clip(json.dumps(message, ensure_ascii=False), secrets),
            }
            if "error" in message:
                data["error_code"] = message["error"].get("code")
            out.append(("mcp.message", data))
    replies = {json.dumps(m.get("id")): m for m in received if "method" not in m}
    for message in sent:
        if message.get("method") != "tools/call":
            continue
        params = message.get("params") or {}
        name = str(params.get("name", ""))
        args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        reply = replies.get(json.dumps(message.get("id")))
        surface = surfaces.get(name, {})
        result = (reply or {}).get("result") or {}
        text = "".join(c.get("text", "") for c in result.get("content", []) if isinstance(c, dict))
        out.append(
            (
                "mcp.call",
                {
                    "tool": name,
                    "known": name in surfaces,
                    "arguments": _clip(
                        json.dumps(args, ensure_ascii=False, sort_keys=True), secrets
                    ),
                    "access": surface.get("access"),
                    "sentence": _fill(surface.get("sentence"), args),
                    "resource": _fill(surface.get("resource"), args),
                    "is_error": bool(result.get("isError")) or reply is None or "error" in reply,
                    "error_code": (reply or {}).get("error", {}).get("code"),
                    "result": _clip(text, secrets),
                },
            )
        )
    return out
