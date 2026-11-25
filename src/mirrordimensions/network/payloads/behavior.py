# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Surfaces and rules: the shared engine behind profiles, the gateway's behaviour add-on and
`mirror system try`. Pure Python with no imports beyond the standard library, so the gateway
container and the host run exactly the same code.

A surface describes one portal page or endpoint: how to match it, the resource it touches,
a plain sentence for the live view, and what its response exposes. A rule changes what an
endpoint accepts or returns (build spec, "Systems: preconfigured inputs and outputs").
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

_PARAM = re.compile(r"\{(\w+)(\+?)\}")


def compile_path(pattern: str) -> re.Pattern[str]:
    """`/repos/{owner}/{repo}/contents/{path+}`: {name} is one segment, {name+} the rest."""
    out = "^"
    pos = 0
    for m in _PARAM.finditer(pattern):
        out += re.escape(pattern[pos : m.start()])
        out += f"(?P<{m.group(1)}>.+)" if m.group(2) else f"(?P<{m.group(1)}>[^/]+)"
        pos = m.end()
    return re.compile(out + re.escape(pattern[pos:]) + "/?$")


@dataclass
class Surface:
    id: str
    kind: str
    method: str
    path: str
    resource: str | None = None
    access: str | None = None
    sentence: str = ""
    unnamed: str = ""
    exposes: dict[str, Any] | None = None
    regex: re.Pattern[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.regex = compile_path(self.path)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Surface:
        match = d.get("match", {})
        return cls(
            id=d["id"],
            kind=d.get("kind", "endpoint"),
            method=str(match.get("method", "GET")).upper(),
            path=match["path"],
            resource=d.get("resource"),
            access=d.get("access"),
            sentence=d.get("sentence", ""),
            unnamed=d.get("unnamed", ""),
            exposes=(d.get("output") or {}).get("exposes"),
        )

    def match(self, method: str, path: str) -> dict[str, str] | None:
        if method.upper() != self.method:
            return None
        m = self.regex.match(path.split("?", 1)[0])
        return m.groupdict() if m else None


_FIELD = re.compile(r"\{([\w.]+)\+?\}")


def _fill(template: str, values: dict[str, Any]) -> str:
    """`{owner}` from the path, `{body.channel_id}` from the request's JSON body."""
    return _FIELD.sub(lambda m: str(values.get(m.group(1), "?")), template)


def _body_fields(body: bytes) -> dict[str, Any]:
    if not body or body[:1] not in (b"{", b" ", b"\n"):
        return {}
    try:
        data = json.loads(body)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {f"body.{k}": v for k, v in data.items() if isinstance(v, str | int)}


@dataclass
class Located:
    surface: str
    resource: str | None
    access: str | None
    sentence: str
    kind: str = "endpoint"

    def as_dict(self) -> dict[str, Any]:
        return {
            "surface": self.surface,
            "kind": self.kind,
            "resource": self.resource,
            "access": self.access,
            "sentence": self.sentence,
        }


class SurfaceTable:
    def __init__(self, surfaces: list[dict[str, Any]]) -> None:
        self.surfaces = [Surface.from_dict(s) for s in surfaces]

    def find(self, method: str, path: str) -> tuple[Surface, dict[str, str]] | None:
        for surface in self.surfaces:
            params = surface.match(method, path)
            if params is not None:
                return surface, params
        return None

    def locate(
        self,
        method: str,
        path: str,
        body: bytes = b"",
        names: dict[str, str] | None = None,
    ) -> Located:
        """The surface a request matches, the resource it touches and a plain sentence.

        `body` fills `{body.field}` in the resource; `names` maps resources known only by an
        id to their names (`channel:k3j…` to `channel:incidents`), learned with `learn`.
        `{name}` in a sentence is the resource's name. A surface whose resource is an id has
        an `unnamed` sentence, used until the id's name is known.
        """
        found = self.find(method, path)
        if found is None:
            return Located(
                surface="unknown",
                resource=None,
                access=None,
                sentence=f"{method} {path.split('?')[0]}",
                kind="unknown",
            )
        surface, params = found
        values: dict[str, Any] = {**params, **_body_fields(body)}
        resource = _fill(surface.resource, values) if surface.resource else None
        if resource is not None and "?" in resource:
            resource = None  # the request did not name it (no body, or no such field)
        known = names or {}
        sentence = surface.sentence
        if resource is not None and resource in known:
            resource = known[resource]
        elif surface.unnamed:
            sentence = surface.unnamed  # the resource is unnamed, or still only an id
        if resource is not None:
            values["name"] = resource.split(":", 1)[-1]
        return Located(
            surface=surface.id,
            resource=resource,
            access=surface.access,
            sentence=_fill(sentence, values),
            kind=surface.kind,
        )

    def learn(self, method: str, path: str, body: bytes) -> dict[str, str]:
        """Names a response revealed: `{"channel:<id>": "channel:<name>"}` for each item of
        a surface whose `exposes` has an `alias` (the id form) next to its `resource`."""
        found = self.find(method, path)
        if found is None or not found[0].exposes or "alias" not in (found[0].exposes or {}):
            return {}
        surface, params = found
        spec = surface.exposes or {}
        try:
            data = json.loads(body or b"null")
        except ValueError:
            return {}
        out: dict[str, str] = {}
        for item in _walk(data, str(spec.get("each", ""))):
            if isinstance(item, dict):
                values = {**params, **item}
                out[_fill(str(spec["alias"]), values)] = _fill(str(spec["resource"]), values)
        return out

    def exposed(self, method: str, path: str, body: bytes) -> list[str]:
        """Every resource whose content a response carried (a search for 30 issues exposes 30)."""
        found = self.find(method, path)
        if found is None or not found[0].exposes:
            return []
        surface, params = found
        spec = surface.exposes or {}
        try:
            data = json.loads(body or b"null")
        except ValueError:
            return []
        items = _walk(data, str(spec.get("each", "")))
        template = str(spec.get("resource", ""))
        out: list[str] = []
        for item in items:
            values = {**params, **(item if isinstance(item, dict) else {})}
            out.append(_fill(template, values))
        return out


def _walk(data: Any, each: str) -> list[Any]:
    """`""` is the value itself, `"[]"` its items, `"posts.*"` the values of a mapping."""
    if each == "":
        return [data] if data is not None else []
    if each == "[]":
        return list(data) if isinstance(data, list) else []
    key, _, rest = each.partition(".")
    if key == "*" and isinstance(data, dict):
        return [v for value in data.values() for v in _walk(value, rest)]
    if isinstance(data, dict) and key in data:
        return _walk(data[key], rest)
    return []


# -- rules -------------------------------------------------------------------------------


@dataclass
class Request:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes
    identity: str | None = None


@dataclass
class Outcome:
    """What the rules decided. `respond` replaces the product's answer entirely."""

    respond: tuple[int, list[list[str]], bytes] | None = None
    delay_ms: int = 0
    request_body: bytes | None = None
    response_edits: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    applied: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])


class Rules:
    """Rules for one system, in file order; the first conflicting action wins (spec)."""

    def __init__(
        self, rules: list[dict[str, Any]], table: SurfaceTable, errors: dict[str, Any], seed: int
    ) -> None:
        self.rules = rules
        self.table = table
        self.errors = errors
        self.seed = seed
        self.counters: dict[str, int] = {}
        self.windows: dict[str, list[float]] = {}

    def _draw(self, rule: str) -> float:
        """A deterministic number in [0, 1) for the nth request a rule sees in this run."""
        n = self.counters.get(rule, 0)
        self.counters[rule] = n + 1
        digest = hashlib.sha256(f"{self.seed}:{rule}:{n}".encode()).digest()
        return int.from_bytes(digest[:8], "big") / 2**64

    def matches(self, rule: dict[str, Any], req: Request) -> bool:
        match = rule.get("match", {})
        when = rule.get("when") or {}
        if "agent" in when and req.identity != when["agent"]:
            return False
        if "surface" in match:
            found = self.table.find(req.method, req.path)
            return found is not None and found[0].id == match["surface"]
        if "path" in match:
            method_ok = str(match.get("method", req.method)).upper() == req.method.upper()
            return (
                method_ok and compile_path(match["path"]).match(req.path.split("?")[0]) is not None
            )
        return False

    def error(
        self, name: str, values: dict[str, str] | None = None
    ) -> tuple[int, list[list[str]], bytes]:
        """The product's own error, filled in: {date}, {host}, {request_id}, {version_id}."""
        spec = self.errors.get(name) or self.errors.get("unavailable") or {"status": 502}
        fill = {"request_id": self._request_id(), **(values or {})}
        body = str(spec.get("body", ""))
        headers = [[k, v] for k, v in spec.get("headers", [])]
        for key, value in fill.items():
            body = body.replace("{" + key + "}", value)
            headers = [[k, v.replace("{" + key + "}", value)] for k, v in headers]
        return int(spec["status"]), headers, body.encode()

    def _request_id(self) -> str:
        """A 26-character lower-case id of the kind Mattermost puts in every error."""
        n = self.counters.get("request-id", 0)
        self.counters["request-id"] = n + 1
        digest = hashlib.sha256(f"{self.seed}:request-id:{n}".encode()).digest()
        alphabet = "abcdefghijkmnopqrstuwxyz13456789"
        return "".join(alphabet[b % 32] for b in digest[:26])

    def apply(self, req: Request, now: float) -> Outcome:
        out = Outcome()
        for rule in self.rules:
            if not self.matches(rule, req):
                continue
            name = rule["name"]
            inp, outp = rule.get("input") or {}, rule.get("output") or {}
            changed: list[str] = []
            if inp:
                rejected = self._input(inp, req, out)
                if rejected:
                    out.respond = self.error(str(inp.get("on_reject", "forbidden")))
                    out.applied.append({"rule": name, "changed": rejected})
                    return out
                changed += [k for k in ("set_fields", "rename_fields") if k in inp]
            if "respond" in outp:
                r = outp["respond"]
                body = (
                    json.dumps(r["json"], separators=(",", ":"))
                    if "json" in r
                    else str(r.get("body", ""))
                )
                headers = (
                    [["Content-Type", "application/json;charset=utf-8"]] if "json" in r else []
                )
                out.respond = (int(r.get("status", 200)), headers, body.encode())
                changed.append("respond")
            if "fail" in outp and out.respond is None:
                fail = outp["fail"]
                if self._draw(name) < float(fail.get("rate", 0)):
                    out.respond = self.error(str(fail.get("error", "unavailable")))
                    changed.append("fail")
            if "rate_limit" in outp and out.respond is None:
                limit = outp["rate_limit"]
                window = self.windows.setdefault(name, [])
                per = float(limit.get("per_s", 60))
                window[:] = [t for t in window if now - t < per]
                if len(window) >= int(limit.get("calls", 60)):
                    out.respond = self.error("rate_limited")
                    changed.append("rate_limit")
                else:
                    window.append(now)
            if "delay_ms" in outp:
                delay = outp["delay_ms"]
                if isinstance(delay, list):
                    low, high = int(delay[0]), int(delay[1])
                    delay = low + int(self._draw(f"{name}:delay") * (high - low + 1))
                out.delay_ms = max(out.delay_ms, int(delay))
                changed.append("delay_ms")
            for key in ("set_fields", "remove_fields", "insert_text", "page_size"):
                if key in outp:
                    out.response_edits.append({key: outp[key]})
                    changed.append(key)
            if changed:
                out.applied.append({"rule": name, "changed": changed})
            if out.respond is not None:
                return out
        return out

    def _input(self, inp: dict[str, Any], req: Request, out: Outcome) -> list[str]:
        if "max_body_bytes" in inp and len(req.body) > int(inp["max_body_bytes"]):
            return ["max_body_bytes"]
        body = _json(req.body)
        if isinstance(body, dict):
            for field_name in inp.get("require_fields", []):
                if field_name not in body:
                    return ["require_fields"]
            for field_name in inp.get("forbid_fields", []):
                if field_name in body:
                    return ["forbid_fields"]
            if "set_fields" in inp or "rename_fields" in inp:
                body.update(inp.get("set_fields", {}))
                for old, new in (inp.get("rename_fields") or {}).items():
                    if old in body:
                        body[new] = body.pop(old)
                out.request_body = json.dumps(
                    body, separators=(",", ":"), ensure_ascii=False
                ).encode()
        return []


def edit_response(body: bytes, edits: list[dict[str, Any]]) -> bytes:
    """Apply output edits to a JSON response; non-JSON bodies are returned unchanged."""
    data = _json(body)
    if data is None:
        return body
    for edit in edits:
        targets = data if isinstance(data, list) else [data]
        if "page_size" in edit and isinstance(data, list):
            data = data[: int(edit["page_size"])]
            continue
        for item in targets:
            if not isinstance(item, dict):
                continue
            for key, value in (edit.get("set_fields") or {}).items():
                item[key] = value
            for key in edit.get("remove_fields") or []:
                item.pop(key, None)
            insert = edit.get("insert_text")
            if insert and insert.get("field") in item:
                item[insert["field"]] = (
                    f"{item[insert['field']]}{insert.get('separator', chr(10) + chr(10))}{insert['text']}"
                )
    # Compact, key order kept, as the Go servers behind the gateway write it.
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode()


def _json(body: bytes) -> Any:
    try:
        return json.loads(body) if body else None
    except ValueError:
        return None
