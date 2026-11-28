# SPDX-License-Identifier: Apache-2.0
"""Systems: their surfaces, settings, data shape and rules; rule edits; dry runs."""

from __future__ import annotations

import re
import time
from io import StringIO
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from ruamel.yaml import YAML

# ruamel.yaml's round-trip API is only partly annotated.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
from mirrordimensions.config.loader import load_model, read_yaml
from mirrordimensions.config.manifest import App, Manifest, Rule
from mirrordimensions.errors import MirrorError
from mirrordimensions.network.payloads.behavior import Request, Rules, Surface, edit_response
from mirrordimensions.project import Project
from mirrordimensions.service.changes import Change
from mirrordimensions.twins.base import get_twin
from mirrordimensions.twins.profile import Profile


class SystemSummary(BaseModel):
    id: str
    kind: str | None
    product: str | None
    hostname: str
    visibility: str
    surfaces: int
    rules: int
    twin: bool


class SurfaceInfo(BaseModel):
    id: str
    kind: str
    method: str
    path: str
    resource: str | None
    access: str | None
    sentence: str
    customized_by: list[str]
    takes: str = Field(default="", description="What a request carries, in plain words")
    gives: str = Field(default="", description="What the answer carries, in plain words")


class SystemDetail(BaseModel):
    summary: SystemSummary
    settings: dict[str, Any]
    data: dict[str, Any]
    surfaces: list[SurfaceInfo]
    rules: list[dict[str, Any]]
    errors: list[str] = Field(
        default_factory=list[str], description="The product's own errors a rule can answer with"
    )


class TryResult(BaseModel):
    surface: str
    resource: str | None
    sentence: str
    rules_fired: list[dict[str, Any]]
    status: int
    headers: list[list[str]]
    body: str
    from_rule: bool


def _manifest(project: Project) -> Manifest:
    manifest, problems = load_model(project.manifest_path, Manifest)
    if manifest is None:
        raise MirrorError(
            "mirror.yaml is not valid.",
            problems[0].render() if problems else "",
            "Run: mirror validate",
        )
    return manifest


def _app(manifest: Manifest, app_id: str) -> App:
    for app in manifest.apps:
        if app.id == app_id:
            return app
    raise MirrorError(
        f"No system called {app_id!r}.",
        f"Systems in mirror.yaml: {', '.join(a.id for a in manifest.apps) or 'none'}.",
        "Run: mirror system list",
    )


def _summary(app: App) -> SystemSummary:
    twin = get_twin(app.product)
    surfaces = len(Profile(app.product).surfaces) if twin and app.product else 0
    return SystemSummary(
        id=app.id,
        kind=app.kind,
        product=app.product,
        hostname=app.hostname,
        visibility=app.visibility,
        surfaces=surfaces,
        rules=len(app.rules),
        twin=twin is not None,
    )


def list_systems(project: Project) -> list[SystemSummary]:
    return [_summary(a) for a in _manifest(project).apps]


KIND_WORDS = {
    "repo": "repository",
    "file": "file",
    "issue": "issue",
    "pull": "pull request",
    "branch": "branch",
    "comment": "comment",
    "user": "profile",
    "channel": "channel",
    "post": "message",
    "team": "team",
}
PLURALS = {
    "repo": "repositories",
    "branch": "branches",
    "pull": "pull requests",
    "post": "messages",
}
_NAMES = re.compile(r"\{(\w+)\+?\}")


def describe_io(surface: Surface) -> tuple[str, str]:
    """What a surface takes in and gives back, in plain words, from the profile alone: the
    names in its path, a body for a change, and what its answer exposes."""
    names = [n.replace("_", " ") for n in _NAMES.findall(surface.path)]
    takes = ", ".join(names)
    git = ".git/" in surface.path
    if surface.method in ("POST", "PUT", "PATCH"):
        body = "a form" if surface.kind == "portal" else "git's own data" if git else "a JSON body"
        takes = f"{takes} and {body}" if takes else body
    takes = takes[:1].upper() + takes[1:] if takes else "Nothing"
    kind = (surface.resource or "").split(":", 1)[0]
    exposes = surface.exposes or {}
    listed = str(exposes.get("resource", "")).split(":", 1)[0]
    if git:
        gives = "Repository data, as git sends it"
    elif surface.kind == "portal":
        gives = "A page"
    elif surface.kind == "asset":
        gives = "A file for the page"
    elif surface.kind == "background" or surface.path.endswith("/websocket"):
        gives = "A live connection"
    elif exposes and exposes.get("each") not in ("", None):
        gives = f"A list of {PLURALS.get(listed, (listed or 'item') + 's')}"
    elif kind and surface.method == "GET":
        gives = f"The {KIND_WORDS.get(kind, kind)}"
    elif kind and surface.method == "DELETE":
        gives = "Confirmation"
    elif kind:
        gives = f"The {KIND_WORDS.get(kind, kind)}, as changed"
    else:
        gives = "An answer"
    return takes, gives


def show_system(project: Project, app_id: str) -> SystemDetail:
    app = _app(_manifest(project), app_id)
    rules = [r.model_dump(exclude_none=True) for r in app.rules]
    surfaces: list[SurfaceInfo] = []
    settings: dict[str, Any] = dict(app.settings)
    if app.product and get_twin(app.product):
        profile = Profile(app.product)
        settings = {**profile.defaults.get("settings", {}), **app.settings}
        engine = Rules(rules, profile.table, profile.errors, 0)
        for s in profile.table.surfaces:
            probe = Request(method=s.method, path=s.path, headers={}, body=b"")
            fired = [
                r["name"]
                for r in rules
                if ("surface" in r.get("match", {}) and r["match"]["surface"] == s.id)
                or ("path" in r.get("match", {}) and engine.matches(r, probe))
            ]
            surfaces.append(
                SurfaceInfo(
                    id=s.id,
                    kind=s.kind,
                    method=s.method,
                    path=s.path,
                    resource=s.resource,
                    access=s.access,
                    sentence=s.sentence,
                    customized_by=fired,
                    takes=describe_io(s)[0],
                    gives=describe_io(s)[1],
                )
            )
    return SystemDetail(
        summary=_summary(app),
        settings=settings,
        data=dict(app.data),
        surfaces=surfaces,
        rules=rules,
        errors=sorted(Profile(app.product).errors) if app.product and get_twin(app.product) else [],
    )


def list_rules(project: Project, app_id: str) -> list[dict[str, Any]]:
    return [r.model_dump(exclude_none=True) for r in _app(_manifest(project), app_id).rules]


def validate_rule(app: App, rule: dict[str, Any]) -> list[str]:
    """Problems with a rule: unknown surfaces or errors (build spec: `mirror validate`)."""
    problems: list[str] = []
    if not app.product or get_twin(app.product) is None:
        return [f"{app.id} has no twin yet, so it has no surfaces to customize"]
    profile = Profile(app.product)
    surface = rule.get("match", {}).get("surface")
    if surface and surface not in {s["id"] for s in profile.surfaces}:
        problems.append(f"rule {rule.get('name')}: unknown surface {surface!r}")
    for error in (
        (rule.get("input") or {}).get("on_reject"),
        ((rule.get("output") or {}).get("fail") or {}).get("error"),
    ):
        if error and error not in profile.errors:
            problems.append(
                f"rule {rule.get('name')}: unknown error {error!r} (known: {', '.join(profile.errors)})"
            )
    return problems


def edit_manifest(project: Project, edit: Any) -> str:
    """Change mirror.yaml in place, keeping comments and key order; return the new text."""
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    data, problems = read_yaml(project.manifest_path)
    if problems:
        raise MirrorError(
            "mirror.yaml cannot be read.", problems[0].render(), "Run: mirror validate"
        )
    edit(data)
    buffer = StringIO()
    yaml.dump(data, buffer)
    text = buffer.getvalue()
    try:
        Manifest.model_validate(yaml.load(text))  # refuse to write an invalid manifest
    except ValidationError as exc:
        first = exc.errors()[0]
        raise MirrorError(
            "That change would make mirror.yaml invalid, so it was not written.",
            str(first.get("msg", exc)).removeprefix("Value error, "),
            "Fix the conflicting entry in mirror.yaml, then try again.",
        ) from exc
    Path(project.manifest_path).write_bytes(text.encode("utf-8"))
    return text


def _rule_change(app: App, name: str, before: Any, after: Any) -> Change:
    from mirrordimensions.service.environment import system_label

    verb = "added" if before is None else "removed" if after is None else "changed"
    return Change(
        kind="rule",
        target=app.id,
        what=f"{system_label(app.kind, app.product, app.id)}: rule {name} {verb}",
        before=before,
        after=after,
        applies="next run",
    )


def set_rule(project: Project, app_id: str, rule: dict[str, Any]) -> Change:
    """Add or replace a rule; it takes effect at the next run (decision 0021)."""
    Rule.model_validate(rule)
    app = _app(_manifest(project), app_id)
    before = next(
        (r.model_dump(mode="json", exclude_none=True) for r in app.rules if r.name == rule["name"]),
        None,
    )
    problems = validate_rule(app, rule)
    if problems:
        raise MirrorError(
            "The rule is not valid.", "; ".join(problems), "Fix the rule file and try again."
        )

    def edit(data: Any) -> None:
        for entry in data["apps"]:
            if entry["id"] == app_id:
                rules = entry.setdefault("rules", [])
                for i, existing in enumerate(rules):
                    if existing.get("name") == rule["name"]:
                        rules[i] = rule
                        return
                rules.append(rule)

    edit_manifest(project, edit)
    return _rule_change(app, str(rule["name"]), before, rule)


def remove_rule(project: Project, app_id: str, name: str) -> Change:
    app = _app(_manifest(project), app_id)
    before = next(
        (r.model_dump(mode="json", exclude_none=True) for r in app.rules if r.name == name), None
    )

    def edit(data: Any) -> None:
        for entry in data["apps"]:
            if entry["id"] == app_id:
                before = len(entry.get("rules", []))
                entry["rules"] = [r for r in entry.get("rules", []) if r.get("name") != name]
                if len(entry["rules"]) == before:
                    raise MirrorError(
                        f"{app_id} has no rule called {name!r}.",
                        "Nothing was changed.",
                        f"Run: mirror system rules {app_id}",
                    )
                if not entry["rules"]:
                    del entry["rules"]

    edit_manifest(project, edit)
    return _rule_change(app, name, before, None)


def try_request(
    project: Project, app_id: str, method: str, path: str, body: bytes = b"", fetch: Any = None
) -> TryResult:
    """A dry run: the surface, the rules that would fire, and the answer the agent would get.

    The product is asked directly through the control relay (`fetch`), never through the
    gateway, so nothing appears in the agent's view of the system.
    """
    manifest = _manifest(project)
    app = _app(manifest, app_id)
    if not app.product or get_twin(app.product) is None:
        raise MirrorError(
            f"{app_id} has no twin yet.",
            "Only systems with a twin can be tried.",
            "Run: mirror system list",
        )
    profile = Profile(app.product)
    located = profile.locate(method, path)
    engine = Rules(
        [r.model_dump(exclude_none=True) for r in app.rules],
        profile.table,
        profile.errors,
        manifest.company.seed,
    )
    outcome = engine.apply(
        Request(method=method.upper(), path=path, headers={}, body=body), time.time()
    )
    if outcome.respond is not None:
        status, headers, raw = outcome.respond
        return TryResult(
            surface=located.surface,
            resource=located.resource,
            sentence=located.sentence,
            rules_fired=outcome.applied,
            status=status,
            headers=headers,
            body=raw.decode("utf-8", "replace").replace("{host}", app.hostname),
            from_rule=True,
        )
    if fetch is None:
        raise MirrorError(
            "The sandbox is not up.",
            "A dry run asks the product itself for its answer.",
            "Run: mirror up",
        )
    status, raw = fetch(
        method.upper(), path, outcome.request_body if outcome.request_body is not None else body
    )
    if outcome.response_edits:
        raw = edit_response(raw, outcome.response_edits)
    return TryResult(
        surface=located.surface,
        resource=located.resource,
        sentence=located.sentence,
        rules_fired=outcome.applied,
        status=status,
        headers=[],
        body=raw.decode("utf-8", "replace")[:4000],
        from_rule=False,
    )
