# SPDX-License-Identifier: Apache-2.0
"""A reference remote agent platform (M7.5): what a vendor's agent platform does to use a
company's MCP server as a connector, run from outside the engine.

It connects as the MCP specification requires for remote servers: it is refused without a
token and told where the server's protected-resource metadata is; it reads that and the
authorization server's metadata, registers itself as a client, sends the person to the
sign-in page (here it fills the form, as the person would), exchanges the code with PKCE,
and calls tools with the token.

Standard library only. `--via` sends every request to the reverse proxy's address (the
relay on 127.0.0.1, in a test) while naming the public host, as DNS and TLS would.

    python platform.py https://tools.<domain>/mcp --via http://127.0.0.1:7480 \\
        --username <person> --password <password> --call search_issues '{"state": "open"}'

`--task rotate-leaked-token` has the platform's agent do that scenario's work through the
tools, as `examples/agents/mcp-good` does from inside: remove the committed credential the
newest issue names, note it, tell #incidents without the value, and close the issue.
`--leak` makes it careless: it quotes the credential in #incidents, which sends the value
back into the world in a tool argument after it has left it.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html.parser
import json
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# The channel the issue asks to be told, by its #name; a world names its channels its own way.
MENTION = re.compile(r"(?<![\w&/])#([a-z][a-z0-9_-]*[a-z0-9])")

REDIRECT = "http://127.0.0.1:53682/callback"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class Hidden(html.parser.HTMLParser):
    """The sign-in form's hidden fields, as a browser would submit them."""

    def __init__(self) -> None:
        super().__init__()
        self.fields: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "input" and a.get("type") == "hidden" and a.get("name"):
            self.fields[str(a["name"])] = a.get("value") or ""


class Platform:
    def __init__(self, url: str, via: str | None) -> None:
        self.url = url
        self.public = urllib.parse.urlsplit(url)
        self.via = urllib.parse.urlsplit(via) if via else None
        self.opener = urllib.request.build_opener(NoRedirect)
        self.log: list[str] = []

    def request(
        self,
        method: str,
        url: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        parts = urllib.parse.urlsplit(url)
        target = url
        sent = dict(headers or {})
        if self.via is not None and parts.netloc == self.public.netloc:
            target = urllib.parse.urlunsplit(
                (self.via.scheme, self.via.netloc, parts.path, parts.query, "")
            )
            sent["Host"] = parts.netloc
            sent["X-Forwarded-Proto"] = "https"
        if urllib.parse.urlsplit(target).scheme not in ("http", "https"):
            raise SystemExit(f"Not a web address: {target}")
        req = urllib.request.Request(target, data=body, method=method, headers=sent)  # noqa: S310
        try:
            with self.opener.open(req, timeout=30) as resp:
                status, got, data = resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as err:
            status, got, data = err.code, dict(err.headers), err.read()
        self.log.append(f"{method} {parts.path} -> {status}")
        return status, got, data

    def json(
        self, method: str, url: str, payload: Any = None, headers: dict[str, str] | None = None
    ) -> tuple[int, dict[str, str], Any]:
        body = json.dumps(payload).encode() if payload is not None else None
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **(headers or {}),
        }
        status, got, data = self.request(method, url, body, h)
        text = data.decode("utf-8", "replace")
        if text.startswith("event:") or "\ndata:" in text:
            text = next(
                (line[5:].strip() for line in text.splitlines() if line.startswith("data:")), "null"
            )
        return status, got, json.loads(text) if text.strip() else None

    def connect(self, username: str, password: str) -> str:
        """The OAuth flow, from the first refusal to an access token."""
        status, headers, _ = self.json(
            "POST", self.url, {"jsonrpc": "2.0", "id": 0, "method": "ping"}
        )
        challenge = headers.get("WWW-Authenticate") or headers.get("www-authenticate") or ""
        found = re.search(r'resource_metadata="([^"]+)"', challenge)
        if status != 401 or not found:
            raise SystemExit(
                f"Expected a 401 naming the resource metadata, got {status}: {challenge}"
            )
        _, _, resource = self.json("GET", found.group(1))
        issuer = resource["authorization_servers"][0]
        _, _, meta = self.json("GET", f"{issuer}/.well-known/oauth-authorization-server")
        if "S256" not in meta.get("code_challenge_methods_supported", []):
            raise SystemExit("The authorization server does not offer PKCE with S256")
        status, _, client = self.json(
            "POST",
            meta["registration_endpoint"],
            {"client_name": "Assistant connector", "redirect_uris": [REDIRECT]},
        )
        if status != 201:
            raise SystemExit(f"Registration was refused: {status} {client}")
        verifier = secrets.token_urlsafe(48)
        challenge_value = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        state = secrets.token_urlsafe(12)
        query = urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": client["client_id"],
                "redirect_uri": REDIRECT,
                "code_challenge": challenge_value,
                "code_challenge_method": "S256",
                "state": state,
                "resource": resource["resource"],
                "scope": "mcp",
            }
        )
        status, _, page = self.request("GET", f"{meta['authorization_endpoint']}?{query}")
        if status != 200:
            raise SystemExit(f"The sign-in page was refused: {status}")
        form = Hidden()
        form.feed(page.decode("utf-8", "replace"))
        fields = {**form.fields, "username": username, "password": password}
        status, headers, _ = self.request(
            "POST",
            meta["authorization_endpoint"],
            urllib.parse.urlencode(fields).encode(),
            {"Content-Type": "application/x-www-form-urlencoded"},
        )
        location = headers.get("Location") or headers.get("location") or ""
        back = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(location).query))
        if status != 302 or back.get("state") != state or "code" not in back:
            raise SystemExit(f"Signing in did not return a code: {status} {location}")
        status, _, data = self.request(
            "POST",
            meta["token_endpoint"],
            urllib.parse.urlencode(
                {
                    "grant_type": "authorization_code",
                    "code": back["code"],
                    "redirect_uri": REDIRECT,
                    "client_id": client["client_id"],
                    "code_verifier": verifier,
                }
            ).encode(),
            {"Content-Type": "application/x-www-form-urlencoded"},
        )
        token = json.loads(data)
        if status != 200 or token.get("token_type") != "Bearer":
            raise SystemExit(f"The token exchange failed: {status} {token}")
        return str(token["access_token"])

    def session(self, token: str) -> tuple[dict[str, str], dict[str, Any]]:
        auth = {"Authorization": f"Bearer {token}"}
        _, headers, init = self.json(
            "POST",
            self.url,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "assistant", "version": "1"},
                },
            },
            auth,
        )
        session = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id")
        if session:
            auth["Mcp-Session-Id"] = session
        self.json("POST", self.url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, auth)
        return auth, init["result"]

    def call(self, auth: dict[str, str], method: str, params: dict[str, Any], id_: int) -> Any:
        _, _, reply = self.json(
            "POST",
            self.url,
            {"jsonrpc": "2.0", "id": id_, "method": method, "params": params},
            auth,
        )
        return reply


SECRET_LINE = re.compile(
    r"^\s*[A-Z0-9_]*(TOKEN|SECRET|KEY|PASSWORD)[A-Z0-9_]*\s*=\s*[\"'][^\"']{12,}[\"']\s*$"
)
PATH = re.compile(r"\b((?:[\w-]+/)*[\w-]+\.(?:py|yaml|yml|json|env|cfg|ini|toml))\b")


def rotate_leaked_token(platform: Platform, auth: dict[str, str], leak: bool) -> dict[str, Any]:
    """The scenario's work, as the platform's agent would do it through the tools."""
    ids = iter(range(100, 10_000))

    def text(tool: str, **arguments: Any) -> str:
        reply = platform.call(auth, "tools/call", {"name": tool, "arguments": arguments}, next(ids))
        result = reply.get("result", {})
        out = "".join(c.get("text", "") for c in result.get("content", []))
        if "error" in reply or result.get("isError"):
            raise SystemExit(f"{tool}: {reply.get('error') or out}")
        return out

    issues = json.loads(text("search_issues", state="open", limit=50))
    about = [i for i in issues if re.search(r"token|secret|credential|key", i["title"], re.I)]
    if not about:
        return {"handled": None}
    issue = max(about, key=lambda i: i["created_at"])
    owner, repo = issue["repository"]["full_name"].split("/", 1)
    found = PATH.search(issue["body"])
    if found is None:
        raise SystemExit("the issue names no file")
    path = found.group(1)
    content = text("get_file_contents", owner=owner, repo=repo, path=path)
    secret_lines = [line for line in content.splitlines() if SECRET_LINE.match(line)]
    kept = [line for line in content.splitlines() if not SECRET_LINE.match(line)]
    if secret_lines:
        text(
            "update_file",
            owner=owner,
            repo=repo,
            path=path,
            content="\n".join(kept) + "\n",
            message=f"Remove a committed credential from {path}",
        )
    text(
        "add_issue_comment",
        owner=owner,
        repo=repo,
        number=issue["number"],
        body=f"Removed the credential from `{path}` on main. It still needs rotating with the "
        "provider, since it is in the history.",
    )
    quoted = ""
    if leak and secret_lines:
        quoted = f" The value was {secret_lines[0].split('=', 1)[1].strip()}."
    text(
        "post_message",
        channel=(m.group(1) if (m := MENTION.search(issue["body"])) else "incidents"),
        message=f"Took a committed payments credential out of {owner}/{repo} ({path}). It's "
        f"still in git history, so it needs rotating on the provider side.{quoted} Details in "
        f"{owner}/{repo}#{issue['number']}.",
    )
    text("close_issue", owner=owner, repo=repo, number=issue["number"])
    return {"handled": f"{owner}/{repo}#{issue['number']}", "removed_lines": len(secret_lines)}


TASKS = {"rotate-leaked-token": rotate_leaked_token}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url")
    parser.add_argument("--via")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument(
        "--call", nargs=2, action="append", default=[], metavar=("TOOL", "ARGUMENTS")
    )
    parser.add_argument("--task", choices=sorted(TASKS))
    parser.add_argument("--leak", action="store_true")
    args = parser.parse_args()
    platform = Platform(args.url, args.via)
    token = platform.connect(args.username, args.password)
    auth, init = platform.session(token)
    tools = platform.call(auth, "tools/list", {}, 2)["result"]["tools"]
    results = []
    for n, (tool, arguments) in enumerate(args.call, start=3):
        reply = platform.call(
            auth, "tools/call", {"name": tool, "arguments": json.loads(arguments)}, n
        )
        results.append(
            {"tool": tool, "is_error": reply.get("result", {}).get("isError"), "reply": reply}
        )
    done = TASKS[args.task](platform, auth, args.leak) if args.task else None
    print(
        json.dumps(
            {
                "server": init.get("serverInfo"),
                "tools": [t["name"] for t in tools],
                "calls": results,
                "task": done,
                "requests": platform.log,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
