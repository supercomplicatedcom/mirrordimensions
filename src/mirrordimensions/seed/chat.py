# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Chat history from the seed folder: a Slack export or a Mattermost bulk export
(decision 0030, point 2).

A Slack export is a folder holding `channels.json` and `users.json`, with one folder per
channel of daily files (`2025-03-04.json`). A Mattermost bulk export is one JSONL file of
`channel`, `user` and `post` lines. Both are read into one shape; markup is turned into the
plain text a person would see, and every message has its secrets taken out.
"""

# Exports are loosely shaped JSON: values are checked as they are read, not typed ahead.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from typing import Any, cast

from pydantic import BaseModel, Field

from mirrordimensions.seed.detect import without_secrets
from mirrordimensions.seed.reader import SeedFile


class SeedMessage(BaseModel):
    author: str | None = None
    text: str
    created: float | None = None
    reply_to: int | None = Field(default=None, description="Index of the thread root")


class SeedChannel(BaseModel):
    name: str
    purpose: str = ""
    messages: list[SeedMessage] = Field(default_factory=list[SeedMessage])


def _plain(text: str, users: dict[str, str]) -> str:
    """Slack's markup as a person reads it: mentions as names, links as their labels."""
    text = re.sub(
        r"<@([A-Z0-9]+)(\|[^>]+)?>", lambda m: users.get(m.group(1), "someone").split(" ")[0], text
    )
    text = re.sub(r"<#[A-Z0-9]+\|([^>]+)>", r"#\1", text)
    text = re.sub(r"<!(here|channel|everyone)>", r"@\1", text)
    text = re.sub(r"<([^|>]+)\|([^>]+)>", r"\2", text)
    text = re.sub(r"<(https?://[^>]+)>", r"\1", text)
    return text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def _clean(text: str) -> str:
    return without_secrets("", text)[0].strip()


def slack_roots(files: list[SeedFile]) -> list[str]:
    """Folders in the seed folder that hold a Slack export."""
    paths = {f.path for f in files}
    roots: list[str] = []
    for path in sorted(paths):
        p = PurePosixPath(path)
        if p.name == "channels.json":
            parent = str(p.parent) if str(p.parent) != "." else ""
            users = f"{parent}/users.json" if parent else "users.json"
            if users in paths:
                roots.append(parent)
    return roots


def from_slack(root: str, files: list[SeedFile]) -> tuple[list[SeedChannel], list[str]]:
    """The channels of the Slack export at `root`, and the files it used."""
    prefix = f"{root}/" if root else ""
    by_path = {f.path: f for f in files}

    def load(name: str) -> Any:
        try:
            return json.loads(by_path[prefix + name].text)
        except (KeyError, json.JSONDecodeError):
            return []

    users = {
        str(u.get("id")): str(
            (u.get("profile") or {}).get("real_name") or u.get("real_name") or u.get("name") or ""
        )
        for u in cast(list[Any], load("users.json"))
        if isinstance(u, dict)
    }
    used = [prefix + "channels.json", prefix + "users.json"]
    channels: list[SeedChannel] = []
    for c in cast(list[Any], load("channels.json")):
        if not isinstance(c, dict) or not c.get("name"):
            continue
        name = str(c["name"])
        purpose = str((c.get("purpose") or {}).get("value") or "")
        day_files = sorted(
            p for p in by_path if p.startswith(f"{prefix}{name}/") and p.endswith(".json")
        )
        raw: list[dict[str, Any]] = []
        for p in day_files:
            used.append(p)
            try:
                day = json.loads(by_path[p].text)
            except json.JSONDecodeError:
                continue
            raw += [m for m in cast(list[Any], day) if isinstance(m, dict)]
        raw.sort(key=lambda m: float(m.get("ts") or 0))
        channel = SeedChannel(name=name, purpose=_clean(purpose))
        roots: dict[str, int] = {}
        for m in raw:
            if m.get("subtype") in ("channel_join", "channel_leave", "bot_message"):
                continue
            text = _clean(_plain(str(m.get("text") or ""), users))
            if not text:
                continue
            ts = str(m.get("ts") or "")
            thread = str(m.get("thread_ts") or "")
            reply_to = roots.get(thread) if thread and thread != ts else None
            if reply_to is None:
                roots[ts] = len(channel.messages)
            author = users.get(str(m.get("user"))) or str(m.get("user_name") or "") or None
            channel.messages.append(
                SeedMessage(
                    author=author, text=text, created=float(ts) if ts else None, reply_to=reply_to
                )
            )
        if channel.messages:
            channels.append(channel)
    return channels, used


def from_mattermost(text: str) -> list[SeedChannel] | None:
    """A Mattermost bulk export (JSONL), or None if the file is not one."""
    lines = [line for line in text.split("\n") if line.strip()]
    try:
        records = [json.loads(line) for line in lines]
    except json.JSONDecodeError:
        return None
    if not records or not any(isinstance(r, dict) and r.get("type") == "post" for r in records):
        return None
    users: dict[str, str] = {}
    channels: dict[str, SeedChannel] = {}
    for r in records:
        if not isinstance(r, dict):
            continue
        kind = r.get("type")
        if kind == "user":
            u = r.get("user") or {}
            name = f"{u.get('first_name') or ''} {u.get('last_name') or ''}".strip()
            users[str(u.get("username"))] = name or str(u.get("username") or "")
        elif kind == "channel":
            c = r.get("channel") or {}
            if c.get("name"):
                channels[str(c["name"])] = SeedChannel(
                    name=str(c["name"]), purpose=_clean(str(c.get("purpose") or ""))
                )
    for r in records:
        if not isinstance(r, dict) or r.get("type") != "post":
            continue
        post = r.get("post") or {}
        name = str(post.get("channel") or "")
        if not name:
            continue
        channel = channels.setdefault(name, SeedChannel(name=name))
        message = _clean(str(post.get("message") or ""))
        if not message:
            continue
        root = len(channel.messages)
        channel.messages.append(
            SeedMessage(
                author=users.get(str(post.get("user"))) or str(post.get("user") or "") or None,
                text=message,
                created=float(post["create_at"]) / 1000 if post.get("create_at") else None,
            )
        )
        for reply in cast(list[Any], post.get("replies") or []):
            if not isinstance(reply, dict):
                continue
            body = _clean(str(reply.get("message") or ""))
            if body:
                channel.messages.append(
                    SeedMessage(
                        author=users.get(str(reply.get("user")))
                        or str(reply.get("user") or "")
                        or None,
                        text=body,
                        created=float(reply["create_at"]) / 1000
                        if reply.get("create_at")
                        else None,
                        reply_to=root,
                    )
                )
    found = [c for c in channels.values() if c.messages]
    return found or None
