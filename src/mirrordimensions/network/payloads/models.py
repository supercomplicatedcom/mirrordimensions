# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Model routes for the gateway (build spec, "Rules for the model gateway"). Pure functions:
no mitmproxy here, so the host's tests exercise exactly what the gateway runs.

- Only inference paths are forwarded; anything else gets the provider's own not-found answer.
- The agent's placeholder credential is replaced by the real one, read on the host.
- Provider-hosted tools (which run outside the sandbox) are blocked, flagged or allowed.
- Usage is read from whole responses and from streams.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# Paths that run inference, per provider (method, path). Verified against each provider's
# API reference; anything else on the host (files, fine-tuning, accounts) is not forwarded.
INFERENCE = {
    "anthropic": {("POST", "/v1/messages"), ("POST", "/v1/messages/count_tokens")},
    "openai": {
        ("POST", "/v1/chat/completions"),
        ("POST", "/v1/responses"),
        ("POST", "/v1/completions"),
        ("POST", "/v1/embeddings"),
    },
    # Self-hosted servers (vLLM, TGI, llama.cpp and others) speak the OpenAI shape.
    "self-hosted": {
        ("POST", "/v1/chat/completions"),
        ("POST", "/v1/completions"),
        ("POST", "/v1/embeddings"),
        ("GET", "/v1/models"),
    },
}

# Tool types that run on the provider's servers and can reach the internet or remote
# services there. Matched by prefix: providers version them (web_search_20260209).
HOSTED_TOOL_PREFIXES = {
    "anthropic": (
        "web_search",
        "web_fetch",
        "code_execution",
        "bash_code_execution",
        "mcp_toolset",
        "computer_toolset",
    ),
    "openai": ("web_search", "file_search", "code_interpreter", "mcp", "image_generation"),
    "self-hosted": (),
}
# Request fields that turn on hosted capabilities without a tool entry.
HOSTED_FIELDS = {
    "anthropic": ("mcp_servers", "container"),
    "openai": ("web_search_options",),
    "self-hosted": (),
}
CREDENTIAL_HEADER = {
    "anthropic": "x-api-key",
    "openai": "authorization",
    "self-hosted": "authorization",
}


@dataclass
class Route:
    provider: str
    hosted_tools: str = "block"  # block | flag | allow
    credential: str | None = None  # the real value; never logged
    extra_paths: set[tuple[str, str]] = field(default_factory=set[tuple[str, str]])


def is_inference(route: Route, method: str, path: str) -> bool:
    bare = path.split("?", 1)[0].rstrip("/") or "/"
    return (method.upper(), bare) in INFERENCE.get(route.provider, set()) | route.extra_paths


def hosted_tools_in(provider: str, body: bytes) -> list[str]:
    """The provider-hosted capabilities a request asks for, by type or field name."""
    try:
        request = json.loads(body or b"{}")
    except ValueError:
        return []
    if not isinstance(request, dict):
        return []
    found: list[str] = []
    prefixes = HOSTED_TOOL_PREFIXES.get(provider, ())
    for tool in request.get("tools") or []:
        kind = str(tool.get("type", "")) if isinstance(tool, dict) else ""
        if kind and any(kind == p or kind.startswith(p + "_") for p in prefixes):
            found.append(kind)
    for name in HOSTED_FIELDS.get(provider, ()):
        if request.get(name):
            found.append(name)
    return found


def credential_headers(route: Route, headers: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The request's headers with every credential the agent sent removed and the real one
    added, in the provider's form. Other headers keep their order."""
    drop = {"x-api-key", "authorization", "api-key"}
    kept = [(k, v) for k, v in headers if k.lower() not in drop]
    if route.credential is None:
        return [(k, v) for k, v in headers]  # nothing to inject: pass through as sent
    name = CREDENTIAL_HEADER[route.provider]
    value = route.credential if name == "x-api-key" else f"Bearer {route.credential}"
    return [*kept, (name, value)]


def error(provider: str, status: int, message: str) -> tuple[int, list[list[str]], bytes]:
    """An error in the provider's own shape."""
    if provider == "anthropic":
        kind = {400: "invalid_request_error", 404: "not_found_error", 403: "permission_error"}.get(
            status, "api_error"
        )
        body: dict[str, Any] = {"type": "error", "error": {"type": kind, "message": message}}
    else:
        body = {
            "error": {
                "message": message,
                "type": "invalid_request_error",
                "param": None,
                "code": None,
            }
        }
    raw = json.dumps(body, separators=(",", ":")).encode()
    return status, [["Content-Type", "application/json"]], raw


def refuse_hosted(provider: str, tools: list[str]) -> tuple[int, list[list[str]], bytes]:
    names = ", ".join(tools)
    if provider == "anthropic":
        return error(
            provider,
            400,
            f"tools: the following tools are not enabled for this organization: {names}",
        )
    return error(provider, 400, f"The following tools are not available for this project: {names}")


def not_inference(provider: str, method: str, path: str) -> tuple[int, list[list[str]], bytes]:
    if provider == "anthropic":
        return error(provider, 404, "Not Found")
    return error(provider, 404, f"Invalid URL ({method} {path.split('?', 1)[0]})")


def usage(provider: str, body: bytes, streamed: bool) -> dict[str, int | str]:
    """Model name and token counts from a whole response or a whole captured stream."""
    out: dict[str, int | str] = {}
    events: list[dict[str, Any]] = []
    if streamed:
        for line in body.decode("utf-8", "replace").splitlines():
            if line.startswith("data:"):
                data = line[5:].strip()
                if data and data != "[DONE]":
                    try:
                        parsed = json.loads(data)
                    except ValueError:
                        continue
                    if isinstance(parsed, dict):
                        events.append(parsed)
    else:
        try:
            parsed = json.loads(body or b"{}")
        except ValueError:
            return out
        if isinstance(parsed, dict):
            events.append(parsed)
    for event in events:
        message = (
            event.get("message")
            if provider == "anthropic" and event.get("type") == "message_start"
            else event
        )
        if not isinstance(message, dict):
            continue
        if "model" in message:
            out["model"] = str(message["model"])
        response = message.get("response") if isinstance(message.get("response"), dict) else None
        counts = message.get("usage") or (response or {}).get("usage") or {}
        if not isinstance(counts, dict):
            continue
        for src, dst in (
            ("input_tokens", "input_tokens"),
            ("prompt_tokens", "input_tokens"),
            ("output_tokens", "output_tokens"),
            ("completion_tokens", "output_tokens"),
            ("cache_read_input_tokens", "cache_read_tokens"),
        ):
            value = counts.get(src)
            if isinstance(value, int):
                # Anthropic's message_delta output count is cumulative: the last one wins.
                out[dst] = value
    return out
