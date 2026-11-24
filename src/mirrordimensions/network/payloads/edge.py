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

import json
import sys
import threading
import time
from datetime import UTC, datetime
from email.utils import formatdate
from pathlib import Path
from urllib.parse import urlsplit

from mitmproxy import http, tls, version
from mitmproxy.net.http import status_codes
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


class Edge:
    def __init__(self) -> None:
        config = json.loads(ROUTES.read_text())
        self.routes: dict[str, dict] = {k.lower(): v for k, v in config["routes"].items()}
        self.secrets: list[str] = [s for s in config.get("secrets", []) if s]
        BODIES.mkdir(parents=True, exist_ok=True)

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

    def request(self, flow: http.HTTPFlow) -> None:
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
        if route.get("visibility") == "denied":
            flow.response = http.Response.make(
                403, route.get("denied_body", ""), route.get("denied_headers", {})
            )
            return
        upstream = urlsplit(route["upstream"])
        flow.request.scheme = upstream.scheme
        flow.request.host = upstream.hostname
        flow.request.port = upstream.port or (443 if upstream.scheme == "https" else 80)
        # The upstream sees the original Host header, as it would behind a load balancer.
        flow.request.host_header = host

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

    def _store(self, seq_hint: int, suffix: str, content: bytes | None) -> str | None:
        if not content:
            return None
        for secret in self.secrets:
            content = content.replace(secret.encode(), b"[redacted]")
        name = f"{seq_hint}.{suffix}"
        (BODIES / name).write_bytes(content)
        return f"bodies/{name}"

    def response(self, flow: http.HTTPFlow) -> None:
        start = flow.metadata.get("edge_start", time.monotonic())
        req, resp = flow.request, flow.response
        token = f"{int(time.time() * 1000)}-{id(flow) & 0xFFFFFF:06x}"
        _emit(
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
                "resp_body_ref": self._store(token, "resp", resp.raw_content if resp else None),
                "duration_ms": round((time.monotonic() - start) * 1000, 1),
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
            },
        )


addons = [Edge()]
