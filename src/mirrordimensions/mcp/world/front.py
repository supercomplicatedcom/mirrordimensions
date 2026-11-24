# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The world MCP front: the company's MCP server, as its tools are exported (decision 0009).

Runs inside the world on the system network, behind the gateway, from one file: the standard
library only. It holds the tool definitions, the routes from tools to the twins' APIs and the
tokens it has issued, and nothing else. It reaches the twins through the gateway, by their
production names, as the person the token was issued to.

Streamable HTTP, dual-era (MCP 2026-07-28):
- modern requests carry their protocol version in `_meta` and the `MCP-Protocol-Version`,
  `Mcp-Method` and `Mcp-Name` headers, and are served statelessly;
- legacy clients open with `initialize` and get an `Mcp-Session-Id`.

It writes nothing: the gateway captures every message (`mcp.message`, `mcp.call`).
Configured by /etc/tools/config.json, re-read when it changes.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import re
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

CONFIG = os.environ.get("TOOLS_CONFIG", "/etc/tools/config.json")
CA_FILE = os.environ.get("TOOLS_CA", "/etc/tools/ca.crt")
PORT = int(os.environ.get("TOOLS_PORT", "8000"))
MODERN = "2026-07-28"
META_VERSION = "io.modelcontextprotocol/protocolVersion"
META_SERVER = "io.modelcontextprotocol/serverInfo"
_REF = re.compile(r"\{([^{}]+)\}")

# JSON-RPC and MCP error codes
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602
HEADER_MISMATCH, UNSUPPORTED_VERSION = -32020, -32022


class Config:
    """The configuration file, re-read whenever it changes (tokens are issued while running)."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.mtime = -1.0
        self.data: dict[str, Any] = {}
        self.lock = threading.Lock()

    def get(self) -> dict[str, Any]:
        with self.lock:
            try:
                mtime = os.stat(self.path).st_mtime
            except OSError:
                return self.data
            if mtime != self.mtime:
                with open(self.path, encoding="utf-8") as handle:
                    self.data = json.load(handle)
                self.mtime = mtime
            return self.data


def decode_header(value: str) -> str:
    """`=?base64?...?=` values are Base64 of UTF-8 (Streamable HTTP, Value Encoding)."""
    if value.startswith("=?base64?") and value.endswith("?="):
        return base64.b64decode(value[9:-2]).decode("utf-8")
    return value


def error(id_: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        body["data"] = data
    return {"jsonrpc": "2.0", "id": id_, "error": body}


# -- tools -----------------------------------------------------------------------------


def fill(template: Any, args: dict[str, Any], results: list[Any], person: str) -> Any:
    """Fill a step's references. A string that is exactly one reference keeps its type."""
    if isinstance(template, dict):
        return {k: fill(v, args, results, person) for k, v in template.items()}
    if isinstance(template, list):
        return [fill(v, args, results, person) for v in template]
    if not isinstance(template, str):
        return template

    def value(ref: str) -> Any:
        if ref.endswith("!b64"):  # an argument sent base64-encoded, as some APIs want file content
            return base64.b64encode(str(value(ref[:-4])).encode()).decode()
        name, has_default, default = ref.partition("|")
        if name == "$person":
            return person
        if name.startswith("$"):
            index, _, path = name[1:].partition(".")
            current: Any = results[int(index)]
            for part in path.split(".") if path else []:
                current = current[int(part)] if isinstance(current, list) else current.get(part)
            return current
        if name in args and args[name] is not None:
            return args[name]
        if has_default:
            return default  # may be empty: "{body|}" makes an argument optional
        raise KeyError(name)

    whole = _REF.fullmatch(template)
    if whole:
        return value(whole.group(1))
    return _REF.sub(lambda m: str(value(m.group(1))), template)


class ToolError(Exception):
    """A tool execution error: reported to the model as a result with isError."""


def call_backend(
    backend: dict[str, str], token: str, step: dict[str, Any], context: ssl.SSLContext
) -> Any:
    method = str(step["method"]).upper()
    url = backend["base"] + urllib.parse.quote(str(step["path"]), safe="/:@")
    query = {k: str(v) for k, v in (step.get("query") or {}).items() if v not in (None, "")}
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = None
    request = urllib.request.Request(url, method=method)
    request.add_header("Authorization", f"{backend['auth']} {token}")
    request.add_header("Accept", "application/json")
    if step.get("body") is not None:
        data = json.dumps(step["body"]).encode()
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, data=data, timeout=30, context=context) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        message = raw.decode("utf-8", "replace").strip()
        with contextlib.suppress(ValueError, AttributeError):
            message = json.loads(raw).get("message") or message
        raise ToolError(f"{exc.code} {exc.reason}: {message}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ToolError(f"upstream request failed: {exc}") from exc
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", "replace")  # a raw file, served as text


def run_tool(
    config: dict[str, Any],
    caller: dict[str, Any],
    name: str,
    args: dict[str, Any],
    context: ssl.SSLContext,
) -> dict[str, Any]:
    results: list[Any] = []
    try:
        for step in config["routes"][name]:
            filled = fill(
                {k: v for k, v in step.items() if k != "app"}, args, results, caller["person"]
            )
            app = step["app"]
            token = caller["backends"].get(app)
            if token is None:
                raise ToolError("403 Forbidden: you do not have access to this resource")
            results.append(call_backend(config["backends"][app], token, filled, context))
    except KeyError as exc:
        return tool_result(f"missing required argument: {exc.args[0]}", error=True)
    except ToolError as exc:
        return tool_result(str(exc), error=True)
    last = results[-1]
    return tool_result(last if isinstance(last, str) else json.dumps(last, ensure_ascii=False))


def tool_result(text: str, *, error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": error}


def visible_tools(config: dict[str, Any], caller: dict[str, Any]) -> list[dict[str, Any]]:
    allowed = caller.get("tools")
    return [t for t in config["tools"] if allowed is None or t["name"] in allowed]


# -- HTTP --------------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = "uvicorn"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    config: Config
    sessions: dict[str, str]  # legacy session id -> negotiated version
    context: ssl.SSLContext

    def version_string(self) -> str:
        return self.server_version  # exactly "uvicorn", as the production server sends

    def log_message(self, format: str, *args: Any) -> None:
        return  # the gateway captures every exchange; nothing is logged here

    # responses

    def _send(self, status: int, body: Any = None, headers: dict[str, str] | None = None) -> None:
        payload = b"" if body is None else json.dumps(body).encode()
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        if body is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _not_found(self) -> None:
        self._send(404, {"detail": "Not Found"})

    # routing

    def _endpoint(self) -> bool:
        return urllib.parse.urlsplit(self.path).path == self.config.get()["endpoint"]

    def do_GET(self) -> None:
        if not self._endpoint():
            return self._not_found()
        self._send(405, None, {"Allow": "POST"})

    def do_DELETE(self) -> None:
        if not self._endpoint():
            return self._not_found()
        session = self.headers.get("Mcp-Session-Id")
        if session and self.sessions.pop(session, None) is not None:
            return self._send(200)
        self._send(405, None, {"Allow": "POST"})

    def do_POST(self) -> None:
        if not self._endpoint():
            return self._not_found()
        config = self.config.get()
        host = (self.headers.get("Host") or "").split(":")[0]
        origin = self.headers.get("Origin")
        if origin and urllib.parse.urlsplit(origin).hostname != host:
            return self._send(
                403,
                {
                    "jsonrpc": "2.0",
                    "error": {"code": INVALID_REQUEST, "message": "Forbidden: invalid Origin"},
                },
            )
        auth = self.headers.get("Authorization", "")
        caller = config["tokens"].get(auth[7:]) if auth.startswith("Bearer ") else None
        if caller is None:
            return self._send(
                401,
                {"error": "invalid_token", "error_description": "Missing or invalid access token"},
                {"WWW-Authenticate": 'Bearer error="invalid_token"'},
            )
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            message = json.loads(raw)
        except ValueError:
            return self._send(400, error(None, PARSE_ERROR, "Parse error"))
        if (
            not isinstance(message, dict)
            or message.get("jsonrpc") != "2.0"
            or "method" not in message
        ):
            return self._send(400, error(None, INVALID_REQUEST, "Invalid Request"))
        params = message.get("params") or {}
        meta = params.get("_meta") or {} if isinstance(params, dict) else {}
        if META_VERSION in meta:
            return self._modern(config, caller, message, params, meta)
        return self._legacy(config, caller, message, params)

    # modern: stateless, every request carries its version

    def _modern(
        self,
        config: dict[str, Any],
        caller: dict[str, Any],
        message: dict[str, Any],
        params: dict[str, Any],
        meta: dict[str, Any],
    ) -> None:
        id_, method = message.get("id"), str(message["method"])
        version = str(meta[META_VERSION])
        header_version = self.headers.get("MCP-Protocol-Version")
        if header_version is None or self.headers.get("Mcp-Method") is None:
            return self._send(
                400,
                error(id_, HEADER_MISMATCH, "Header mismatch: required MCP headers are missing"),
            )
        if header_version != version:
            return self._send(
                400,
                error(
                    id_,
                    HEADER_MISMATCH,
                    f"Header mismatch: MCP-Protocol-Version header value '{header_version}' does not match body value '{version}'",
                ),
            )
        if self.headers["Mcp-Method"] != method:
            return self._send(
                400,
                error(
                    id_,
                    HEADER_MISMATCH,
                    f"Header mismatch: Mcp-Method header value '{self.headers['Mcp-Method']}' does not match body value '{method}'",
                ),
            )
        if method in ("tools/call", "resources/read", "prompts/get"):
            body_name = str(params.get("name") or params.get("uri") or "")
            header_name = self.headers.get("Mcp-Name")
            if header_name is None or decode_header(header_name) != body_name:
                return self._send(
                    400,
                    error(
                        id_,
                        HEADER_MISMATCH,
                        f"Header mismatch: Mcp-Name header value '{header_name or ''}' does not match body value '{body_name}'",
                    ),
                )
        if version not in config["versions"] or version < MODERN:
            return self._send(
                400,
                error(
                    id_,
                    UNSUPPORTED_VERSION,
                    "Unsupported protocol version",
                    {"supported": config["versions"], "requested": version},
                ),
            )
        if "id" not in message:  # a notification
            return self._send(202)
        if method == "server/discover":
            result: dict[str, Any] = {
                "supportedVersions": config["versions"],
                "capabilities": {"tools": {}},
                "_meta": {META_SERVER: config["server"]},
            }
            if config.get("instructions"):
                result["instructions"] = config["instructions"]
        elif method == "tools/list":
            result = {"tools": visible_tools(config, caller)}
        elif method == "tools/call":
            reply = self._call(config, caller, params)
            if "error" in reply:
                return self._send(200, {"jsonrpc": "2.0", "id": id_, "error": reply["error"]})
            result = reply
        else:
            return self._send(404, error(id_, METHOD_NOT_FOUND, "Method not found"))
        self._send(
            200, {"jsonrpc": "2.0", "id": id_, "result": {"resultType": "complete", **result}}
        )

    # legacy: initialize, then a session

    def _legacy(
        self,
        config: dict[str, Any],
        caller: dict[str, Any],
        message: dict[str, Any],
        params: dict[str, Any],
    ) -> None:
        id_, method = message.get("id"), str(message["method"])
        legacy = [v for v in config["versions"] if v < MODERN]
        if method == "initialize":
            if not legacy:
                return self._send(
                    400,
                    error(
                        id_,
                        UNSUPPORTED_VERSION,
                        "Unsupported protocol version",
                        {
                            "supported": config["versions"],
                            "requested": params.get("protocolVersion"),
                        },
                    ),
                )
            requested = str(params.get("protocolVersion", ""))
            version = requested if requested in legacy else legacy[0]
            session = os.urandom(16).hex()
            self.sessions[session] = version
            result: dict[str, Any] = {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": config["server"],
            }
            if config.get("instructions"):
                result["instructions"] = config["instructions"]
            return self._send(
                200, {"jsonrpc": "2.0", "id": id_, "result": result}, {"Mcp-Session-Id": session}
            )
        session = self.headers.get("Mcp-Session-Id")
        if not session:
            return self._send(
                400, error(None, INVALID_REQUEST, "Bad Request: No valid session ID provided")
            )
        if session not in self.sessions:
            return self._send(404, error(None, -32001, "Session not found"))
        if "id" not in message:
            return self._send(202)
        if method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": visible_tools(config, caller)}
        elif method == "tools/call":
            reply = self._call(config, caller, params)
            if "error" in reply:
                return self._send(200, {"jsonrpc": "2.0", "id": id_, "error": reply["error"]})
            result = reply
        else:
            return self._send(200, error(id_, METHOD_NOT_FOUND, "Method not found"))
        self._send(200, {"jsonrpc": "2.0", "id": id_, "result": result})

    def _call(
        self, config: dict[str, Any], caller: dict[str, Any], params: dict[str, Any]
    ) -> dict[str, Any]:
        name = str(params.get("name", ""))
        if name not in {t["name"] for t in visible_tools(config, caller)}:
            return {"error": {"code": INVALID_PARAMS, "message": f"Unknown tool: {name}"}}
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return {"error": {"code": INVALID_PARAMS, "message": "Invalid arguments"}}
        return run_tool(config, caller, name, args, self.context)


def main() -> None:
    context = ssl.create_default_context(cafile=CA_FILE if os.path.exists(CA_FILE) else None)
    Handler.config = Config(CONFIG)
    Handler.sessions = {}
    Handler.context = context
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)  # noqa: S104 (the system network)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
