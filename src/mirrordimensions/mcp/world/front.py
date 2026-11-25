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
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import ssl
import threading
import time
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


# -- OAuth 2.1 for remote clients (decision 0024) -----------------------------------------
#
# When the world is exposed, config["oauth"] holds the issuer (the public address), the
# company's name and, for the one person the agent acts as, a salted password hash and the
# MCP token to issue. Registered clients and codes live in memory: a restart makes a client
# register again, as production servers that rotate their stores do.

CODE_TTL = 600
ACCESS_TTL = 3600


class OAuthState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.clients: dict[str, dict[str, Any]] = {}
        self.codes: dict[str, dict[str, Any]] = {}
        self.refresh: dict[str, str] = {}  # refresh token -> username


def s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def password_ok(person: dict[str, Any], password: str) -> bool:
    digest = hashlib.sha256((str(person["salt"]) + password).encode()).hexdigest()
    return hmac.compare_digest(digest, str(person["sha256"]))


SIGN_IN = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in · {company}</title>
<style>body{{font-family:system-ui,sans-serif;background:#f4f5f7;margin:0}}main{{max-width:360px;margin:12vh auto;background:#fff;border:1px solid #dcdfe4;border-radius:8px;padding:28px}}h1{{font-size:20px;margin:0 0 4px}}p{{color:#555;margin:0 0 18px;font-size:14px}}label{{display:block;font-size:14px;margin:12px 0 4px}}input{{width:100%;box-sizing:border-box;padding:9px;border:1px solid #c4c8cf;border-radius:6px;font-size:15px}}button{{margin-top:18px;width:100%;padding:10px;background:#1f4fd1;color:#fff;border:0;border-radius:6px;font-size:15px}}.error{{color:#a3261b}}</style>
</head><body><main><h1>{company}</h1><p>Sign in to allow <b>{client}</b> to use your tools.</p>{message}
<form method="post" action="/authorize">{hidden}
<label for="username">Username</label><input id="username" name="username" autocomplete="username" required>
<label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password" required>
<button type="submit">Sign in</button></form></main></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "uvicorn"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    config: Config
    sessions: dict[str, str]  # legacy session id -> negotiated version
    context: ssl.SSLContext
    oauth: OAuthState

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

    def _html(self, status: int, page: str) -> None:
        payload = page.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        return {k: v[0] for k, v in urllib.parse.parse_qs(raw, keep_blank_values=True).items()}

    # OAuth (decision 0024)

    def _oauth_get(self, oauth: dict[str, Any], path: str) -> bool:
        issuer = str(oauth["issuer"])
        if path.startswith("/.well-known/oauth-protected-resource"):
            self._send(
                200,
                {
                    "resource": f"{issuer}{self.config.get()['endpoint']}",
                    "authorization_servers": [issuer],
                    "bearer_methods_supported": ["header"],
                },
            )
            return True
        if path in ("/.well-known/oauth-authorization-server", "/.well-known/openid-configuration"):
            self._send(
                200,
                {
                    "issuer": issuer,
                    "authorization_endpoint": f"{issuer}/authorize",
                    "token_endpoint": f"{issuer}/token",
                    "registration_endpoint": f"{issuer}/register",
                    "response_types_supported": ["code"],
                    "grant_types_supported": ["authorization_code", "refresh_token"],
                    "code_challenge_methods_supported": ["S256"],
                    "token_endpoint_auth_methods_supported": ["none"],
                    "scopes_supported": ["mcp"],
                },
            )
            return True
        if path == "/authorize":
            query = {
                k: v[0]
                for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).items()
            }
            self._authorize_page(oauth, query, "")
            return True
        return False

    def _request_problem(self, query: dict[str, str]) -> str:
        client = self.oauth.clients.get(query.get("client_id", ""))
        if client is None:
            return "This application is not registered."
        if query.get("redirect_uri") not in client["redirect_uris"]:
            return "The redirect address does not match the application's registration."
        if query.get("response_type") != "code":
            return "Unsupported response type."
        if not query.get("code_challenge") or query.get("code_challenge_method") != "S256":
            return "A PKCE code challenge (S256) is required."
        return ""

    def _authorize_page(self, oauth: dict[str, Any], query: dict[str, str], message: str) -> None:
        problem = self._request_problem(query)
        company = html.escape(str(oauth.get("company", "")))
        if problem:
            self._html(400, f"<!doctype html><title>{company}</title><p>{html.escape(problem)}</p>")
            return
        client = self.oauth.clients[query["client_id"]]
        hidden = "".join(
            f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">'
            for k, v in query.items()
            if k
            in (
                "client_id",
                "redirect_uri",
                "response_type",
                "code_challenge",
                "code_challenge_method",
                "state",
                "scope",
                "resource",
            )
        )
        notice = f'<p class="error" role="alert">{html.escape(message)}</p>' if message else ""
        self._html(
            200 if not message else 401,
            SIGN_IN.format(
                company=company,
                client=html.escape(str(client.get("client_name") or "this application")),
                message=notice,
                hidden=hidden,
            ),
        )

    def _oauth_post(self, oauth: dict[str, Any], path: str) -> bool:
        if path == "/register":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                body = None
            uris = body.get("redirect_uris") if isinstance(body, dict) else None
            if not isinstance(uris, list) or not uris or not all(isinstance(u, str) for u in uris):
                self._send(
                    400,
                    {
                        "error": "invalid_redirect_uri",
                        "error_description": "redirect_uris is required",
                    },
                )
                return True
            client_id = secrets.token_urlsafe(18)
            client = {
                "client_id": client_id,
                "client_id_issued_at": int(time.time()),
                "client_name": str(body.get("client_name") or ""),
                "redirect_uris": uris,
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            }
            with self.oauth.lock:
                self.oauth.clients[client_id] = client
            self._send(201, client)
            return True
        if path == "/authorize":
            form = self._form()
            problem = self._request_problem(form)
            if problem:
                self._authorize_page(oauth, form, "")
                return True
            person = oauth["people"].get(form.get("username", ""))
            if person is None or not password_ok(person, form.get("password", "")):
                self._authorize_page(oauth, form, "Incorrect username or password.")
                return True
            code = secrets.token_urlsafe(24)
            with self.oauth.lock:
                self.oauth.codes[code] = {
                    "client_id": form["client_id"],
                    "redirect_uri": form["redirect_uri"],
                    "challenge": form["code_challenge"],
                    "username": form["username"],
                    "expires": time.time() + CODE_TTL,
                }
            target = form["redirect_uri"]
            joiner = "&" if "?" in target else "?"
            params = {"code": code, **({"state": form["state"]} if form.get("state") else {})}
            self.send_response(302)
            self.send_header("Location", target + joiner + urllib.parse.urlencode(params))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return True
        if path == "/token":
            form = self._form()
            self._token(oauth, form)
            return True
        return False

    def _token(self, oauth: dict[str, Any], form: dict[str, str]) -> None:
        def fail(error: str, why: str) -> None:
            self._send(
                400, {"error": error, "error_description": why}, {"Cache-Control": "no-store"}
            )

        grant = form.get("grant_type")
        if grant == "authorization_code":
            with self.oauth.lock:
                entry = self.oauth.codes.pop(form.get("code", ""), None)
            if entry is None or entry["expires"] < time.time():
                return fail("invalid_grant", "The authorization code is invalid or expired")
            if (
                form.get("client_id") != entry["client_id"]
                or form.get("redirect_uri") != entry["redirect_uri"]
            ):
                return fail("invalid_grant", "The code was issued to another client")
            if not hmac.compare_digest(s256(form.get("code_verifier", "")), entry["challenge"]):
                return fail("invalid_grant", "The code verifier does not match")
            username = entry["username"]
        elif grant == "refresh_token":
            with self.oauth.lock:
                username = self.oauth.refresh.get(form.get("refresh_token", ""), "")
            if not username:
                return fail("invalid_grant", "The refresh token is invalid")
        else:
            return fail("unsupported_grant_type", "Use authorization_code or refresh_token")
        person = oauth["people"].get(username)
        if person is None:
            return fail("invalid_grant", "The account is no longer allowed")
        refresh = secrets.token_urlsafe(32)
        with self.oauth.lock:
            self.oauth.refresh[refresh] = username
        self._send(
            200,
            {
                "access_token": person["token"],
                "token_type": "Bearer",
                "expires_in": ACCESS_TTL,
                "refresh_token": refresh,
                "scope": "mcp",
            },
            {"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    # routing

    def _endpoint(self) -> bool:
        return urllib.parse.urlsplit(self.path).path == self.config.get()["endpoint"]

    def do_GET(self) -> None:
        oauth = self.config.get().get("oauth")
        if oauth and self._oauth_get(oauth, urllib.parse.urlsplit(self.path).path):
            return None
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
        oauth = self.config.get().get("oauth")
        if oauth and self._oauth_post(oauth, urllib.parse.urlsplit(self.path).path):
            return None
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
            challenge = 'Bearer error="invalid_token"'
            if config.get("oauth"):
                metadata = f"{config['oauth']['issuer']}/.well-known/oauth-protected-resource"
                challenge += f', resource_metadata="{metadata}"'
            return self._send(
                401,
                {"error": "invalid_token", "error_description": "Missing or invalid access token"},
                {"WWW-Authenticate": challenge},
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
    Handler.oauth = OAuthState()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)  # noqa: S104 (the system network)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
