# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Edits that are saved but not yet in effect: pending changes (decision 0021).

Every edit is written to `mirror.yaml` or an agent file at once. When it takes effect
depends on what it changes:

- **Next run.** A system's rules, its visibility between granted, denied and present, and
  an agent's grants. Each run hands the gateway the current rules and visibility and
  issues the agent's identity from its file, so nothing has to be rebuilt.
- **Rebuild.** The company, its data, a system added, removed or reconfigured, and a
  system made absent or brought back: these change what is built and seeded, so they wait
  for `mirror apply` (or `mirror world create --resume`).

Two records say what is in effect: `built.json`, the definition the world was last built
from, and `applied.json`, the rules, visibility and grants the gateway and the last run
used. A change is pending while the files differ from them.
"""

from __future__ import annotations

import json
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from mirrordimensions.config.manifest import Manifest
from mirrordimensions.hostos.files import write_text
from mirrordimensions.project import Project

BUILT_FILE = "built.json"
APPLIED_FILE = "applied.json"

Applies = Literal["next run", "restart", "rebuild"]


class Change(BaseModel):
    kind: Literal["company", "data", "system", "visibility", "rule", "grant"]
    target: str = Field(description="The system's id, or the agent's name for a grant")
    what: str = Field(description="The change in plain words")
    before: Any = None
    after: Any = None
    applies: Applies = Field(description="When it takes effect")


def _read(project: Project, name: str) -> dict[str, Any]:
    path = project.state_dir / name
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return cast(dict[str, Any], data) if isinstance(data, dict) else {}


def _apps(manifest_dump: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(a["id"]): a for a in manifest_dump.get("apps", [])}


def record_built(project: Project, manifest: Manifest) -> None:
    """The definition the world is now built from (after the snapshot is saved)."""
    dump = manifest.model_dump(mode="json")
    write_text(project.state_dir / BUILT_FILE, json.dumps(dump, indent=2) + "\n", owner_only=True)
    record_applied(project, manifest)


def record_applied(
    project: Project,
    manifest: Manifest,
    agent: str | None = None,
    grants: Any = None,
    *,
    restarted: bool = True,
) -> None:
    """The rules and visibility the gateway now has, and the grants an agent last ran with."""
    _record_built_if_unchanged(project, manifest)
    current = _read(project, APPLIED_FILE)
    # Model routes reach the gateway and the firewall only when the sandbox starts; a run
    # (restarted=False) does not change them.
    if restarted:
        current["models"] = [m.model_dump(mode="json") for m in manifest.models]
    elif "models" not in current:
        built = _read(project, BUILT_FILE)
        current["models"] = built.get(
            "models", [m.model_dump(mode="json") for m in manifest.models]
        )
    current["apps"] = {
        a.id: {"visibility": a.visibility, "rules": [r.model_dump(mode="json") for r in a.rules]}
        for a in manifest.apps
    }
    if agent is not None:
        current.setdefault("grants", {})[agent] = grants
    write_text(
        project.state_dir / APPLIED_FILE, json.dumps(current, indent=2) + "\n", owner_only=True
    )


def _record_built_if_unchanged(project: Project, manifest: Manifest) -> None:
    """A world built before built.json was kept gets one the first time its definition is
    unchanged since the build (its creation record says so)."""
    if (project.state_dir / BUILT_FILE).is_file():
        return
    from mirrordimensions.service.worlddef import STAGES, definition_hash, first_stage_affected

    created = _read(project, "create.json")
    if (
        created
        and not created.get("failed")
        and int(created.get("last_stage", 0)) >= len(STAGES)
        and first_stage_affected(created.get("hashes", {}), definition_hash(manifest)) > 8
    ):
        dump = manifest.model_dump(mode="json")
        write_text(
            project.state_dir / BUILT_FILE, json.dumps(dump, indent=2) + "\n", owner_only=True
        )


def _visibility_applies(before: str, after: str, built: str) -> Applies:
    """Between granted, denied and present: the gateway, at the next run. Absent changes DNS
    and which containers run: a sandbox restart, or a rebuild to bring back a system the
    world was built without."""
    if "absent" not in (before, after):
        return "next run"
    if after != "absent" and built == "absent":
        return "rebuild"
    return "restart"


def visibility_change(
    app_id: str, label: str, before: str, after: str, built: str | None = None
) -> Change:
    return Change(
        kind="visibility",
        target=app_id,
        what=f"{label}: visibility {before} to {after}",
        before=before,
        after=after,
        applies=_visibility_applies(before, after, built or before),
    )


def built_visibility(project: Project, app_id: str) -> str | None:
    """How a system was built: absent, or present in the snapshot (any other visibility)."""
    app = _apps(_read(project, BUILT_FILE)).get(app_id)
    return str(app["visibility"]) if app else None


def grant_change(agent: str, resource: str, before: Any, after: Any) -> Change:
    words = {None: "none"}
    return Change(
        kind="grant",
        target=agent,
        what=f"{agent}: {resource} {words.get(before, before)} to {words.get(after, after)}",
        before=before,
        after=after,
        applies="next run",
    )


def pending_changes(project: Project, manifest: Manifest, agents: dict[str, Any]) -> list[Change]:
    """What the files say that is not yet in effect. `agents` maps each agent's name to its
    grants as its file has them now."""
    from mirrordimensions.service.environment import system_label

    built = _read(project, BUILT_FILE)
    applied = _read(project, APPLIED_FILE)
    now = manifest.model_dump(mode="json")
    out: list[Change] = []
    failed = _read(project, "create.json").get("failed")
    if failed:
        out.append(
            Change(
                kind="system",
                target="world",
                what=f"The last rebuild stopped at {failed}",
                applies="rebuild",
            )
        )
    if not built:
        # A world built before built.json was kept: its creation record still says whether
        # the definition changed, though not how.
        from mirrordimensions.service.worlddef import definition_hash, first_stage_affected

        created = _read(project, "create.json")
        if not created:
            return out  # never built: everything is still to come, nothing is "changed"
        if first_stage_affected(created.get("hashes", {}), definition_hash(manifest)) <= 8:
            out.append(
                Change(
                    kind="system",
                    target="world",
                    what="The world's definition changed since it was built",
                    applies="rebuild",
                )
            )
        built = now
    for part, kind in (("company", "company"), ("data", "data")):
        if built.get(part) != now.get(part):
            out.append(
                Change(
                    kind=kind,  # pyright: ignore[reportArgumentType]
                    target=part,
                    what=f"The {part} definition changed",
                    applies="rebuild",
                )
            )
    was, current = _apps(built), _apps(now)
    in_effect = applied.get("apps") or {
        k: {"visibility": v.get("visibility"), "rules": v.get("rules", [])} for k, v in was.items()
    }
    for app_id in sorted(set(was) | set(current)):
        old, new = was.get(app_id), current.get(app_id)
        app = next((a for a in manifest.apps if a.id == app_id), None)
        label = system_label(app.kind, app.product, app.id) if app else app_id
        if old is None or new is None:
            out.append(
                Change(
                    kind="system",
                    target=app_id,
                    what=f"{label}: {'added' if old is None else 'removed'}",
                    applies="rebuild",
                )
            )
            continue
        ignore = ("rules", "visibility")
        if {k: v for k, v in old.items() if k not in ignore} != {
            k: v for k, v in new.items() if k not in ignore
        }:
            out.append(
                Change(kind="system", target=app_id, what=f"{label}: settings", applies="rebuild")
            )
        live = in_effect.get(app_id, {})
        built_vis, now_vis = str(old["visibility"]), str(new["visibility"])
        live_vis = str(live.get("visibility", built_vis))
        if live_vis != now_vis:
            out.append(visibility_change(app_id, label, live_vis, now_vis, built_vis))
        rules_in_effect = cast(list[dict[str, Any]], live.get("rules") or old.get("rules") or [])
        old_rules = {str(r["name"]): r for r in rules_in_effect}
        new_rules = {r["name"]: r for r in new.get("rules", [])}
        for name in sorted(set(old_rules) | set(new_rules)):
            a, b = old_rules.get(name), new_rules.get(name)
            if a != b:
                verb = "added" if a is None else "removed" if b is None else "changed"
                out.append(
                    Change(
                        kind="rule",
                        target=app_id,
                        what=f"{label}: rule {name} {verb}",
                        before=a,
                        after=b,
                        applies="next run",
                    )
                )
    models_live = applied.get("models", built.get("models", []))
    if models_live != now.get("models", []):
        out.append(
            Change(
                kind="system",
                target="models",
                what="Model routes changed",
                before=models_live,
                after=now.get("models", []),
                applies="restart",
            )
        )
    last_grants = cast(dict[str, Any], applied.get("grants") or {})
    for agent, last in sorted(last_grants.items()):
        if agent in agents and agents[agent] != last:
            out.append(
                Change(
                    kind="grant",
                    target=agent,
                    what=f"{agent}: grants changed since its last run",
                    before=last,
                    after=agents[agent],
                    applies="next run",
                )
            )
    return out
