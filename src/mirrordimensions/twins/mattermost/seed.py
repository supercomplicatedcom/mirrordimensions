# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Load the synthetic company into Mattermost with its own bulk import (mmctl import).

One import file carries teams, channels, people, memberships, threads and direct messages,
with each post's original time. Account and channel creation times are backdated in the
database afterwards; the administrator's control token is revoked when seeding ends.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false

from __future__ import annotations

import io
import json
import re
import time
import zipfile
from datetime import datetime, timedelta
from typing import Any

from mirrordimensions.engine.docker_api import Docker
from mirrordimensions.errors import MirrorError
from mirrordimensions.twins.base import TwinContext
from mirrordimensions.world.model import World


def _ms(now: datetime, ago: int) -> int:
    return int((now - timedelta(minutes=ago)).timestamp() * 1000)


def import_lines(world: World, now: datetime, password: str) -> list[dict[str, Any]]:
    people = {p.id: p for p in world.people}
    team = world.org
    lines: list[dict[str, Any]] = [{"type": "version", "version": 1}]
    lines.append(
        {
            "type": "team",
            "team": {
                "name": team,
                "display_name": world.company,
                "type": "I",
                "allow_open_invite": False,
            },
        }
    )
    for ch in world.channels:
        lines.append(
            {
                "type": "channel",
                "channel": {
                    "team": team,
                    "name": ch.name,
                    "display_name": ch.display,
                    "type": "P" if ch.private else "O",
                    "purpose": ch.purpose,
                },
            }
        )
    memberships: dict[str, list[str]] = {}
    for ch in world.channels:
        for member in ch.members:
            memberships.setdefault(member, []).append(ch.name)
    for p in world.people:
        first, _, last = p.name.partition(" ")
        lines.append(
            {
                "type": "user",
                "user": {
                    "username": p.username,
                    "email": p.email,
                    "password": password,
                    "first_name": first,
                    "last_name": last,
                    "position": p.title,
                    "email_verified": True,
                    "teams": [
                        {
                            "name": team,
                            "roles": "team_user",
                            "channels": [
                                {"name": c, "roles": "channel_user"}
                                for c in memberships.get(p.id, [])
                            ],
                        }
                    ],
                },
            }
        )
    for ch in world.channels:
        roots: dict[int, dict[str, Any]] = {}
        for i, m in enumerate(ch.messages):
            entry = {
                "user": people[m.author].username,
                "message": m.text,
                "create_at": _ms(now, m.ago),
            }
            if m.reply_to is not None and m.reply_to in roots:
                roots[m.reply_to].setdefault("replies", []).append(entry)
            else:
                post = {"team": team, "channel": ch.name, **entry}
                roots[i] = post
        for post in roots.values():
            post.setdefault("replies", [])
            post["replies"].sort(key=lambda r: r["create_at"])
            lines.append({"type": "post", "post": post})
    for thread in world.direct:
        members = [people[m].username for m in thread.members]
        lines.append({"type": "direct_channel", "direct_channel": {"members": members}})
        for m in thread.messages:
            lines.append(
                {
                    "type": "direct_post",
                    "direct_post": {
                        "channel_members": members,
                        "user": people[m.author].username,
                        "message": m.text,
                        "create_at": _ms(now, m.ago),
                    },
                }
            )
    return lines


def seed(docker: Docker, ctx: TwinContext, world: World, now: datetime) -> dict[str, int]:
    lines = import_lines(world, now, ctx.secrets["user_password"])
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("import.jsonl", "\n".join(json.dumps(line) for line in lines) + "\n")
    name = f"seed-{world.seed}.zip"
    docker.put_files(ctx.app_container, {f"/mattermost/data/{name}": (buffer.getvalue(), 0o644)})
    upload = docker.exec(
        ctx.app_container, ["mmctl", "--local", "import", "upload", f"/mattermost/data/{name}"]
    )
    if upload.exit_code != 0:
        raise MirrorError(
            "Uploading Mattermost's import failed.",
            upload.output.strip()[-300:],
            "See: mirror logs chat",
        )
    listed = docker.exec(
        ctx.app_container, ["mmctl", "--local", "import", "list", "available"]
    ).output
    available = [ln.strip() for ln in listed.splitlines() if ln.strip().endswith(name)]
    if not available:
        raise MirrorError(
            "Mattermost did not list the uploaded import.",
            listed.strip()[-200:],
            "See: mirror logs chat",
        )
    started = docker.exec(
        ctx.app_container,
        ["mmctl", "--local", "import", "process", "--format", "json", available[-1]],
    )
    job_id = _json_id(started.output)
    deadline = time.time() + 600
    while time.time() < deadline:
        shown = docker.exec(
            ctx.app_container,
            ["mmctl", "--local", "import", "job", "show", "--format", "json", job_id],
        ).output
        status = re.search(r'"status"\s*:\s*"(\w+)"', shown)
        if status and status.group(1) == "success":
            break
        if status and status.group(1) in ("error", "canceled"):
            raise MirrorError(
                "Mattermost's import failed.", shown.strip()[-400:], "See: mirror logs chat"
            )
        time.sleep(2)
    else:
        raise MirrorError(
            "Mattermost's import did not finish in 10 minutes.", job_id, "See: mirror logs chat"
        )
    _backdate(docker, ctx, world, now)
    docker.exec(ctx.app_container, ["rm", "-f", f"/mattermost/data/{name}"])
    return {
        "posts": sum(len(c.messages) for c in world.channels),
        "direct": sum(len(d.messages) for d in world.direct),
    }


def _backdate(docker: Docker, ctx: TwinContext, world: World, now: datetime) -> None:
    statements = ["BEGIN;"]
    for p in world.people:
        ms = _ms(now, p.started_ago)
        statements.append(
            f"UPDATE users SET createat={ms}, updateat={ms} WHERE username='{p.username}';"
        )
        if p.left_ago is not None:
            statements.append(
                f"UPDATE users SET deleteat={_ms(now, p.left_ago)} WHERE username='{p.username}';"
            )
    oldest = _ms(now, max(p.started_ago for p in world.people))
    statements.append(
        f"UPDATE teams SET createat={oldest}, updateat={oldest} WHERE name='{world.org}';"
    )
    statements.append(
        f"UPDATE channels SET createat={oldest} WHERE teamid=(SELECT id FROM teams WHERE name='{world.org}');"
    )
    statements.append(
        "UPDATE channels c SET lastpostat=COALESCE((SELECT max(createat) FROM posts p WHERE p.channelid=c.id), c.lastpostat);"
    )
    statements.append("DELETE FROM jobs WHERE type='import_process';")
    statements.append("COMMIT;")
    out = docker.exec(
        ctx.db_container,
        ["psql", "-U", "mattermost", "-d", "mattermost", "-tAc", "".join(statements)],
    )
    if out.exit_code != 0:
        raise MirrorError(
            "Backdating Mattermost's history failed.",
            out.output.strip()[-300:],
            "See: mirror logs chat",
        )


def _json_id(text: str) -> str:
    match = re.search(r'"id"\s*:\s*"([a-z0-9]{26})"', text)
    if not match:
        raise MirrorError(
            "mmctl did not start the import.", text.strip()[-200:], "See: mirror logs chat"
        )
    return match.group(1)
