# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Gateway add-ons for mitmproxy: router, capture, refusal. Runs inside the gateway only.

Configured by /etc/edge/routes.json, written by the control plane:
  {"routes": {"<hostname>": {"upstream": "http://10.41.0.21:80", "visibility": "granted"}},
   "secrets": ["value to redact", ...]}

Nothing here may change what the client sees: no added headers, no proxy error pages.
Events go to standard output as JSON lines; bodies go to ~/spool/bodies/.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
import threading
import time
from datetime import UTC, datetime
from email.utils import formatdate
from pathlib import Path
from urllib.parse import urlsplit

from mitmproxy import http, tls, version
from mitmproxy.net import encoding
from mitmproxy.net.http import status_codes
from mitmproxy.proxy import server_hooks
from mitmproxy.proxy.layers.http import _http1, _http2

# -- the edge presents itself as an ordinary nginx load balancer --------------------------
# mitmproxy builds its own error pages with "Server: mitmproxy <version>" and the internal
# error message (for example the upstream's address). Replace both, for the pinned
# mitmproxy version only; `mirror doctor` checks error pages on every run.

SERVER = "nginx"


def _nginx_page(status: int, _message: str = "") -> bytes:
    reason = status_codes.RESPONSES.get(status, "Error")
    return (
        f"<html>\r\n<head><title>{status} {reason}</title></head>\r\n<body>\r\n"
        f"<center><h1>{status} {reason}</h1></center>\r\n<hr><center>{SERVER}</center>\r\n"
        "</body>\r\n</html>\r\n"
    ).encode()


def _nginx_error_response(status_code: int, message: str = "") -> bytes:
    body = _nginx_page(status_code)
    reason = status_codes.RESPONSES.get(status_code, "Error")
    head = (
        f"HTTP/1.1 {status_code} {reason}\r\nServer: {SERVER}\r\n"
        f"Date: {formatdate(usegmt=True)}\r\nContent-Type: text/html\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
    )
    return head.encode() + body


version.MITMPROXY = SERVER
_http1.format_error = _nginx_page
_http2.format_error = _nginx_page
_http1.make_error_response = _nginx_error_response

ROUTES = Path("/etc/edge/routes.json")
BODIES = Path.home() / "spool" / "bodies"
REDACT_HEADERS = {"authorization", "cookie", "set-cookie", "x-api-key", "proxy-authorization"}

_lock = threading.Lock()
_seq = 0


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _emit(kind: str, data: dict) -> int:
    global _seq
    with _lock:
        _seq += 1
        seq = _seq
        line = json.dumps(
            {"seq": seq, "ts": _now(), "source": "gateway", "type": kind, "data": data}
        )
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    return seq


sys.path.insert(0, "/etc/edge")
import behavior  # noqa: E402  (the shared rule engine, copied next to this file)
import mcpcap  # noqa: E402  (world MCP servers: mcp.message and mcp.call events)
import models  # noqa: E402  (model routes: inference only, credentials, hosted tools)


class Edge:
    def __init__(self) -> None:
        config = json.loads(ROUTES.read_text())
        self.routes: dict[str, dict] = {k.lower(): v for k, v in config["routes"].items()}
        self.secrets: list[str] = [s for s in config.get("secrets", []) if s]
        seed = int(config.get("seed", 0))
        self.rules = {
            host: behavior.Rules(
                route.get("rules", []),
                behavior.SurfaceTable(route.get("surfaces", [])),
                route.get("errors", {}),
                seed,
            )
            for host, route in self.routes.items()
        }
        self.version_ids: dict[str, str] = {}
        # Names each system's responses revealed so far (`channel:<id>` -> `channel:incidents`),
        # so an exchange that names a resource only by id is located by its name.
        self.names: dict[str, dict[str, str]] = {host: {} for host in self.routes}
        # Model routes: one pinned upstream each, reached with the provider's own name as SNI.
        self.model_routes: dict[str, models.Route] = {}
        self.sni_by_addr: dict[tuple[str, int], str] = {}
        for host, route in self.routes.items():
            spec = route.get("model")
            if spec:
                self.model_routes[host] = models.Route(
                    provider=spec["provider"],
                    hosted_tools=spec.get("hosted_tools", "block"),
                    credential=spec.get("credential"),
                )
                upstream = urlsplit(route["upstream"])
                self.sni_by_addr[(upstream.hostname, upstream.port)] = spec.get("sni", host)
        BODIES.mkdir(parents=True, exist_ok=True)

    def _respond(self, flow: http.HTTPFlow, host: str, answer) -> None:
        """Answer as the product would: its headers in its order, Content-Length last."""
        status, headers, body = answer
        values = {
            "date": formatdate(usegmt=True),
            "host": host,
            "version_id": self.version_ids.get(host, ""),
        }
        for key, value in values.items():
            body = body.replace(("{" + key + "}").encode(), value.encode())
            headers = [[k, v.replace("{" + key + "}", value)] for k, v in headers]
        fields = [(k.encode(), v.encode()) for k, v in headers]
        if not any(k.lower() == "content-length" for k, _ in headers):
            fields.append((b"Content-Length", str(len(body)).encode()))
        flow.response = http.Response(
            http_version=b"HTTP/1.1",
            status_code=status,
            reason=status_codes.RESPONSES.get(status, "").encode(),
            headers=http.Headers(fields),
            content=body,
            trailers=None,
            timestamp_start=time.time(),
            timestamp_end=time.time(),
        )

    # -- refusal of unknown names ------------------------------------------------

    def tls_clienthello(self, data: tls.ClientHelloData) -> None:
        sni = (data.client_hello.sni or "").lower()
        if sni not in self.routes:
            # The listener's default upstream is a closed local port, so passing the
            # connection through ends in an ordinary refusal: no certificate is presented.
            data.ignore_connection = True
            _emit(
                "route.unknown_host",
                {"sni": sni or None, "client": data.context.client.peername[0]},
            )

    # -- routing -----------------------------------------------------------------

    async def request(self, flow: http.HTTPFlow) -> None:
        flow.metadata["edge_start"] = time.monotonic()
        host = (flow.request.host_header or "").split(":")[0].lower()
        sni = (flow.client_conn.sni or "").lower()
        route = self.routes.get(host)
        if route is None or (sni and sni != host):
            _emit(
                "route.unknown_host",
                {"host": host or None, "sni": sni or None, "client": flow.client_conn.peername[0]},
            )
            flow.kill()
            return
        if host in self.model_routes:
            self._model_request(flow, host, route)
            return
        rules = self.rules[host]
        if route.get("visibility") == "denied":
            self._respond(flow, host, rules.error("forbidden"))
            return
        req = behavior.Request(
            method=flow.request.method,
            path=flow.request.path,
            headers=dict(flow.request.headers),
            body=flow.request.raw_content or b"",
        )
        outcome = rules.apply(req, time.time())
        for applied in outcome.applied:
            _emit(
                "rule.applied", {"host": host, "path": flow.request.path.split("?")[0], **applied}
            )
        if outcome.delay_ms:
            await asyncio.sleep(outcome.delay_ms / 1000)
        if outcome.respond is not None:
            self._respond(flow, host, outcome.respond)
            return
        if outcome.request_body is not None:
            flow.request.content = outcome.request_body
        if outcome.response_edits:
            flow.metadata["edge_edits"] = outcome.response_edits
        upstream = urlsplit(route["upstream"])
        flow.request.scheme = upstream.scheme
        flow.request.host = upstream.hostname
        flow.request.port = upstream.port or (443 if upstream.scheme == "https" else 80)
        # The upstream sees what it would behind a TLS load balancer: the original Host, and
        # the client's scheme and address, so the links it builds use https and the hostname.
        flow.request.host_header = host
        flow.request.headers["X-Forwarded-Proto"] = (
            "https" if flow.client_conn.tls_established else "http"
        )
        flow.request.headers["X-Forwarded-For"] = flow.client_conn.peername[0]

    def _model_request(self, flow: http.HTTPFlow, host: str, route: dict) -> None:
        """A call to the model: inference only, hosted tools as configured, the real
        credential added here. The prompt and parameters pass through untouched."""
        mr = self.model_routes[host]
        flow.metadata["edge_model"] = route["model"]["name"]
        method, path = flow.request.method, flow.request.path
        if not models.is_inference(mr, method, path):
            _emit(
                "model.refused",
                {"host": host, "path": path.split("?")[0], "reason": "not an inference path"},
            )
            flow.metadata["edge_refused"] = True
            self._respond(flow, host, models.not_inference(mr.provider, method, path))
            return
        hosted = models.hosted_tools_in(mr.provider, flow.request.raw_content or b"")
        if hosted:
            action = {"block": "blocked", "flag": "flagged", "allow": "allowed"}[mr.hosted_tools]
            _emit("model.hosted_tools", {"host": host, "tools": hosted, "action": action})
            if mr.hosted_tools == "block":
                flow.metadata["edge_refused"] = True
                self._respond(flow, host, models.refuse_hosted(mr.provider, hosted))
                return
            flow.metadata["edge_hosted"] = hosted
        sent = [(k, v) for k, v in flow.request.headers.items(multi=True)]
        flow.request.headers = http.Headers(
            [(k.encode(), v.encode()) for k, v in models.credential_headers(mr, sent)]
        )
        upstream = urlsplit(route["upstream"])
        flow.request.scheme = upstream.scheme
        flow.request.host = upstream.hostname
        flow.request.port = upstream.port
        flow.request.host_header = host

    def server_connect(self, data: server_hooks.ServerConnectionHookData) -> None:
        # A model route's upstream is a pinned address; present the provider's name so its
        # certificate is checked against that name.
        address = data.server.address
        if address and tuple(address) in self.sni_by_addr:
            data.server.sni = self.sni_by_addr[tuple(address)]

    def responseheaders(self, flow: http.HTTPFlow) -> None:
        # Streamed model and MCP answers reach the agent as they arrive; a copy is kept.
        if flow.response is None:
            return
        host = (flow.request.host_header or "").split(":")[0].lower()
        if "edge_model" not in flow.metadata and "mcp" not in self.routes.get(host, {}):
            return
        if flow.response.headers.get("content-type", "").startswith("text/event-stream"):
            copy = bytearray()
            flow.metadata["edge_stream"] = copy

            def tee(chunk: bytes) -> bytes:
                copy.extend(chunk)
                return chunk

            flow.response.stream = tee

    def _model_exchange(
        self, flow: http.HTTPFlow, seq: int, token: str, body: bytes, streamed: bool
    ) -> None:
        """One model call, after its HTTP exchange (`exchange`), which holds the raw bodies.
        The text the model wrote is stored on its own (`answer_ref`) for the suspicion scan
        and the report."""
        mr_name = flow.metadata["edge_model"]
        host = (flow.request.host_header or "").split(":")[0].lower()
        mr = self.model_routes.get(host)
        if mr is None or flow.response is None:
            return
        found = models.usage(mr.provider, body, streamed)
        answer = models.answer_text(body, streamed)
        _emit(
            "model.exchange",
            {
                "exchange": seq,
                "client": flow.client_conn.peername[0],
                "route": mr_name,
                "provider": mr.provider,
                "host": host,
                "path": flow.request.path.split("?")[0],
                "status": flow.response.status_code,
                "streamed": streamed,
                "hosted_tools": flow.metadata.get("edge_hosted", []),
                "duration_ms": round(
                    (time.monotonic() - flow.metadata.get("edge_start", time.monotonic())) * 1000, 1
                ),
                **found,
                "answer_ref": self._store(token, "answer", answer.encode("utf-8")),
            },
        )

    # -- capture -----------------------------------------------------------------

    def _redact(self, headers) -> list[list[str]]:
        out = []
        for name, value in headers.fields:
            n, v = name.decode("latin-1"), value.decode("latin-1")
            if n.lower() in REDACT_HEADERS:
                v = "[redacted]"
            for secret in self.secrets:
                v = v.replace(secret, "[redacted]")
            out.append([n, v])
        return out

    def _store(self, seq_hint: str, suffix: str, content: bytes | None) -> str | None:
        if not content:
            return None
        for secret in self.secrets:
            content = content.replace(secret.encode(), b"[redacted]")
        name = f"{seq_hint}.{suffix}"
        (BODIES / name).write_bytes(content)
        return f"bodies/{name}"

    def response(self, flow: http.HTTPFlow) -> None:
        if flow.response is not None:
            host = (flow.request.host_header or "").split(":")[0].lower()
            version = flow.response.headers.get("X-Version-Id")
            if version:
                self.version_ids[host] = version
            edits = flow.metadata.get("edge_edits")
            if edits and flow.response.content:
                flow.response.content = behavior.edit_response(flow.response.content, edits)
        start = flow.metadata.get("edge_start", time.monotonic())
        req, resp = flow.request, flow.response
        resp_body = resp.raw_content if resp else None
        if "edge_stream" in flow.metadata:
            resp_body = bytes(flow.metadata["edge_stream"])
        token = f"{int(time.time() * 1000)}-{id(flow) & 0xFFFFFF:06x}"
        seq = _emit(
            "http.exchange",
            {
                "method": req.method,
                "host": req.host_header,
                "path": req.path,
                "status": resp.status_code if resp else None,
                "client": flow.client_conn.peername[0],
                "http_version": req.http_version,
                "req_headers": self._redact(req.headers),
                "resp_headers": self._redact(resp.headers) if resp else [],
                "req_body_ref": self._store(token, "req", req.raw_content),
                "resp_body_ref": self._store(token, "resp", resp_body),
                "duration_ms": round((time.monotonic() - start) * 1000, 1),
                **self._where(flow),
            },
        )
        if (
            "edge_model" in flow.metadata
            and resp is not None
            and "edge_refused" not in flow.metadata
        ):
            plain = resp_body or b""
            enc = resp.headers.get("content-encoding")
            if enc:
                with contextlib.suppress(ValueError):
                    plain = encoding.decode(plain, enc)
            self._model_exchange(flow, seq, token, plain, "edge_stream" in flow.metadata)
        host = (req.host_header or "").split(":")[0].lower()
        mcp = self.routes.get(host, {}).get("mcp")
        if mcp is not None and resp is not None:
            self._mcp(flow, seq, host, mcp, resp_body)

    def _where(self, flow: http.HTTPFlow) -> dict:
        """The surface and resource the exchange acted on and a plain sentence for it, from
        the system's profile (the live view's location). Never fails the capture."""
        host = (flow.request.host_header or "").split(":")[0].lower()
        rules = self.rules.get(host)
        if rules is None or not rules.table.surfaces or host in self.model_routes:
            return {}
        try:
            req = flow.request
            names = self.names.setdefault(host, {})
            where = rules.table.locate(
                req.method, req.path, req.get_content(strict=False) or b"", names
            )
            resp = flow.response
            if resp is not None and resp.status_code < 300:
                names.update(
                    rules.table.learn(req.method, req.path, resp.get_content(strict=False) or b"")
                )
            return {"where": where.as_dict()}
        except Exception:  # noqa: BLE001 (a location is a convenience; the exchange is the record)
            return {}

    def _mcp(self, flow: http.HTTPFlow, seq: int, host: str, mcp: dict, body: bytes | None) -> None:
        """Every JSON-RPC message to and from a world MCP server, linked to its exchange."""
        resp = flow.response
        plain = body or b""
        enc = resp.headers.get("content-encoding")
        if enc:
            with contextlib.suppress(ValueError):
                plain = encoding.decode(plain, enc)
        found = mcpcap.events(
            flow.request.get_content(strict=False),
            flow.request.headers.get("content-type", ""),
            plain,
            resp.headers.get("content-type", ""),
            mcp.get("tools", {}),
            self.secrets,
        )
        for kind, data in found:
            _emit(
                kind,
                {"exchange": seq, "host": host, "client": flow.client_conn.peername[0], **data},
            )

    def websocket_message(self, flow: http.HTTPFlow) -> None:
        """Every WebSocket frame, in either direction (Mattermost's live chat uses these)."""
        if flow.websocket is None:
            return
        message = flow.websocket.messages[-1]
        content = message.content
        for secret in self.secrets:
            content = content.replace(secret.encode(), b"[redacted]")
        token = f"{int(time.time() * 1000)}-{id(message) & 0xFFFFFF:06x}"
        _emit(
            "ws.frame",
            {
                "host": flow.request.host_header,
                "path": flow.request.path.split("?")[0],
                "direction": "client" if message.from_client else "server",
                "text": message.is_text,
                "length": len(content),
                "client": flow.client_conn.peername[0],
                "body_ref": self._store(token, "ws", content),
            },
        )

    def error(self, flow: http.HTTPFlow) -> None:
        _emit(
            "http.exchange",
            {
                "method": flow.request.method,
                "host": flow.request.host_header,
                "path": flow.request.path,
                "status": None,
                "client": flow.client_conn.peername[0],
                "error": str(flow.error),
                **self._where(flow),
            },
        )


addons = [Edge()]
