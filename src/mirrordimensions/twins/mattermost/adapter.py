# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Mattermost Team Edition: team chat. Upstream image, configured, never modified.

The official image is amd64 only; on Apple Silicon it runs under Rosetta (decision 0005).
Configured like a long-lived corporate install: open sign-up off, no onboarding tours,
no link previews or other fetches of outside URLs, no marketplace, telemetry off, and
local mode on for administration through Mattermost's own CLI (mmctl), never over the network.
"""

# Product APIs return untyped JSON.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import json
import re
from typing import Any

from mirrordimensions.engine.docker_api import ContainerSpec, Docker
from mirrordimensions.errors import MirrorError
from mirrordimensions.twins.base import Identity, TwinContext
from mirrordimensions.twins.relay import Relay

IMAGE = "mattermost/mattermost-team-edition:12.1@sha256:35927b9c535a9eb74f0e45385d3fe5d8308b16e0464031f157a834da8af3ee73"
DB_IMAGE = (
    "postgres:17-alpine@sha256:f9cf3e1f0066f0eb0c48707d864f0ac5941e9ff454a072077d97a4d278d07d73"
)
PORT = 8065
ADMIN = "chat-admin"


class Mattermost:
    product = "mattermost"
    upstream_port = PORT
    static_path = "/static/images/favicon/favicon-default-16x16.png"

    def _base(self, ctx: TwinContext) -> str:
        return f"http://{ctx.app_ip}:{PORT}"

    def volumes(self, ctx: TwinContext) -> list[str]:
        return [f"{ctx.volume_prefix}data", f"{ctx.volume_prefix}db"]

    def containers(self, ctx: TwinContext) -> list[ContainerSpec]:
        db_password = ctx.secrets["db_password"]
        env = {
            "MM_SQLSETTINGS_DRIVERNAME": "postgres",
            "MM_SQLSETTINGS_DATASOURCE": (
                f"postgres://mattermost:{db_password}@{ctx.db_ip}:5432/mattermost?sslmode=disable&connect_timeout=10"
            ),
            "MM_SERVICESETTINGS_SITEURL": f"https://{ctx.hostname}",
            "MM_SERVICESETTINGS_LISTENADDRESS": f":{PORT}",
            "MM_SERVICESETTINGS_ENABLELOCALMODE": "true",
            "MM_SERVICESETTINGS_ENABLEONBOARDINGFLOW": "false",
            "MM_SERVICESETTINGS_ENABLETUTORIAL": "false",
            "MM_SERVICESETTINGS_ENABLELINKPREVIEWS": "false",
            "MM_SERVICESETTINGS_ENABLEPERMALINKPREVIEWS": "false",
            "MM_SERVICESETTINGS_ENABLESECURITYFIXALERT": "false",
            "MM_SERVICESETTINGS_ENABLEUSERACCESSTOKENS": "true",
            "MM_SERVICESETTINGS_ENABLEDEVELOPER": "false",
            "MM_SERVICESETTINGS_ENABLEGIFPICKER": "false",
            "MM_SERVICESETTINGS_ENABLECUSTOMEMOJI": "false",
            "MM_TEAMSETTINGS_SITENAME": f"{ctx.company} Chat",
            "MM_TEAMSETTINGS_ENABLEOPENSERVER": "false",
            "MM_TEAMSETTINGS_ENABLEUSERCREATION": "false",
            "MM_EMAILSETTINGS_SENDEMAILNOTIFICATIONS": "false",
            "MM_EMAILSETTINGS_SENDPUSHNOTIFICATIONS": "false",
            "MM_PLUGINSETTINGS_ENABLEMARKETPLACE": "false",
            "MM_PLUGINSETTINGS_ENABLEREMOTEMARKETPLACE": "false",
            "MM_PLUGINSETTINGS_AUTOMATICPREPACKAGEDPLUGINS": "false",
            "MM_LOGSETTINGS_ENABLEDIAGNOSTICS": "false",
            "MM_LOGSETTINGS_CONSOLELEVEL": "WARN",
            "MM_IMAGEPROXYSETTINGS_ENABLE": "false",
            "MM_ANNOUNCEMENTSETTINGS_ADMINNOTICESENABLED": "false",
            "MM_ANNOUNCEMENTSETTINGS_USERNOTICESENABLED": "false",
        }
        return [
            ContainerSpec(
                name=ctx.db_container,
                image=DB_IMAGE,
                networks={ctx.network: ctx.db_ip},
                dns=ctx.dns,
                env={
                    "POSTGRES_USER": "mattermost",
                    "POSTGRES_PASSWORD": db_password,
                    "POSTGRES_DB": "mattermost",
                },
                cap_add=["CHOWN", "SETUID", "SETGID", "DAC_OVERRIDE", "FOWNER"],
                volumes={f"{ctx.volume_prefix}db": "/var/lib/postgresql/data"},
            ),
            ContainerSpec(
                name=ctx.app_container,
                image=IMAGE,
                platform="linux/amd64",
                networks={ctx.network: ctx.app_ip},
                dns=ctx.dns,
                env=env,
                volumes={f"{ctx.volume_prefix}data": "/mattermost/data"},
            ),
        ]

    def wait_ready(self, relay: Relay, ctx: TwinContext, timeout_s: float) -> None:
        relay.wait_for(f"{self._base(ctx)}/api/v4/system/ping", timeout_s)

    def _mmctl(self, docker: Docker, ctx: TwinContext, *args: str) -> str:
        out = docker.exec(ctx.app_container, ["mmctl", "--local", "--format", "json", *args])
        if out.exit_code != 0:
            raise MirrorError(
                f"mmctl {' '.join(args[:2])} failed.",
                out.output.strip()[-300:],
                "See: mirror logs chat",
            )
        return out.output

    def bootstrap(self, docker: Docker, relay: Relay, ctx: TwinContext) -> None:
        """The system administrator, created with mmctl in local mode. Idempotent."""
        self.docker = docker
        listed = docker.exec(
            ctx.app_container, ["mmctl", "--local", "user", "list", "--all", "--format", "json"]
        )
        try:
            start = listed.output.find("[")
            existing = json.JSONDecoder().raw_decode(listed.output[start:])[0] if start >= 0 else []
        except ValueError:
            existing = []
        if any(u.get("username") == ADMIN for u in existing or []):
            return
        self._mmctl(
            docker,
            ctx,
            "user",
            "create",
            "--username",
            ADMIN,
            "--email",
            f"{ADMIN}@{ctx.hostname.split('.', 1)[-1]}",
            "--password",
            ctx.secrets["admin_password"],
            "--system-admin",
            "--email-verified",
        )

    def api(
        self,
        relay: Relay,
        ctx: TwinContext,
        method: str,
        path: str,
        body: Any = None,
        token: str | None = None,
        ok: tuple[int, ...] = (200, 201),
    ) -> Any:
        headers = {"Authorization": f"Bearer {token or self.admin_token(relay, ctx)}"}
        resp = relay.request(method, f"{self._base(ctx)}/api/v4{path}", body=body, headers=headers)
        if resp.status not in ok:
            raise MirrorError(
                f"Mattermost refused {method} {path}.",
                f"HTTP {resp.status}: {resp.body[:200]!r}",
                "See: mirror logs chat",
            )
        return resp.json() if resp.body else None

    def admin_token(self, relay: Relay, ctx: TwinContext) -> str:
        cached = getattr(self, "_admin_token", None)
        if cached:
            return cached
        # One control token at a time: revoke any left by an earlier process first.
        listed = self.docker.exec(
            ctx.app_container,
            ["mmctl", "--local", "token", "list", ADMIN, "--all", "--format", "json"],
        ).output
        for match in re.finditer(
            r'"id"\s*:\s*"([a-z0-9]{26})"[^}]*?"description"\s*:\s*"control"', listed
        ):
            self.docker.exec(
                ctx.app_container, ["mmctl", "--local", "token", "revoke", match.group(1)]
            )
        out = self._mmctl(self.docker, ctx, "token", "generate", ADMIN, "control")
        token = _json_field(out, "token")
        self._admin_token = token
        return token

    def admin_fetch(
        self, relay: Relay, ctx: TwinContext, method: str, path: str, body: bytes
    ) -> tuple[int, bytes]:
        headers = {
            "Authorization": f"Bearer {self.admin_token(relay, ctx)}",
            "Host": ctx.hostname,
            "X-Forwarded-Proto": "https",
        }
        if body:
            headers["Content-Type"] = "application/json"
        resp = relay.request(method, f"{self._base(ctx)}{path}", body=body or None, headers=headers)
        return resp.status, resp.body

    def ensure_team(self, relay: Relay, ctx: TwinContext, name: str, display: str) -> str:
        resp = relay.request(
            "GET",
            f"{self._base(ctx)}/api/v4/teams/name/{name}",
            headers={"Authorization": f"Bearer {self.admin_token(relay, ctx)}"},
        )
        if resp.status == 200:
            return str(resp.json()["id"])
        created = self.api(
            relay, ctx, "POST", "/teams", {"name": name, "display_name": display, "type": "I"}
        )
        return str(created["id"])

    def ensure_channel(
        self, relay: Relay, ctx: TwinContext, team_id: str, name: str, private: bool = False
    ) -> str:
        resp = relay.request(
            "GET",
            f"{self._base(ctx)}/api/v4/teams/{team_id}/channels/name/{name}?include_deleted=true",
            headers={"Authorization": f"Bearer {self.admin_token(relay, ctx)}"},
        )
        if resp.status == 200:
            return str(resp.json()["id"])
        created = self.api(
            relay,
            ctx,
            "POST",
            "/channels",
            {
                "team_id": team_id,
                "name": name,
                "display_name": name.replace("-", " ").title(),
                "type": "P" if private else "O",
            },
        )
        return str(created["id"])

    def issue_identity(
        self,
        relay: Relay,
        ctx: TwinContext,
        username: str,
        full_name: str,
        email: str,
        grants: dict[str, Any],
    ) -> Identity:
        password = ctx.secrets.get(f"user:{username}") or ctx.secrets["user_password"]
        first, _, last = full_name.partition(" ")
        found = relay.request(
            "GET",
            f"{self._base(ctx)}/api/v4/users/username/{username}",
            headers={"Authorization": f"Bearer {self.admin_token(relay, ctx)}"},
        )
        if found.status == 404:
            user = self.api(
                relay,
                ctx,
                "POST",
                "/users",
                {
                    "username": username,
                    "email": email,
                    "password": password,
                    "first_name": first,
                    "last_name": last,
                },
            )
        else:
            user = found.json()
        user_id = str(user["id"])
        self.api(
            relay,
            ctx,
            "PUT",
            f"/users/{user_id}/roles",
            {"roles": "system_user system_user_access_token"},
        )
        team_name = str(grants.get("team", "")) or None
        if team_name:
            team_id = self.ensure_team(relay, ctx, team_name, team_name.replace("-", " ").title())
            self.api(
                relay,
                ctx,
                "POST",
                f"/teams/{team_id}/members",
                {"team_id": team_id, "user_id": user_id},
                ok=(200, 201),
            )
            for channel in grants.get("channels", []):
                channel_id = self.ensure_channel(relay, ctx, team_id, str(channel))
                self.api(
                    relay,
                    ctx,
                    "POST",
                    f"/channels/{channel_id}/members",
                    {"user_id": user_id},
                    ok=(200, 201),
                )
        for tok in self.api(relay, ctx, "GET", f"/users/{user_id}/tokens") or []:
            if tok.get("description") == "automation":
                self.api(relay, ctx, "POST", "/users/tokens/revoke", {"token_id": tok["id"]})
        created = self.api(
            relay, ctx, "POST", f"/users/{user_id}/tokens", {"description": "automation"}
        )
        token = str(created["token"])
        return Identity(
            username=username,
            password=password,
            token=token,
            env={"MATTERMOST_URL": f"https://{ctx.hostname}", "MATTERMOST_TOKEN": token},
        )

    def dump_state(self, relay: Relay, ctx: TwinContext) -> dict[str, Any]:
        users = sorted(
            (
                {
                    "username": u["username"],
                    "roles": " ".join(sorted(u.get("roles", "").split())),
                    "deleted": bool(u.get("delete_at")),
                }
                for u in self._pages(relay, ctx, "/users?sort=")
            ),
            key=lambda u: u["username"],
        )
        teams: list[dict[str, Any]] = []
        for team in sorted(
            self.api(relay, ctx, "GET", "/teams?per_page=200") or [], key=lambda t: t["name"]
        ):
            channels: list[dict[str, Any]] = []
            for ch in self._pages(
                relay, ctx, f"/teams/{team['id']}/channels/private?"
            ) + self._pages(relay, ctx, f"/teams/{team['id']}/channels?"):
                members = sorted(
                    m["username"] for m in self._pages(relay, ctx, f"/users?in_channel={ch['id']}&")
                )
                ordered: list[dict[str, Any]] = []
                page = 0
                while True:
                    url = f"/channels/{ch['id']}/posts?per_page=200&page={page}"
                    posts = self.api(relay, ctx, "GET", url) or {}
                    batch = [posts["posts"][pid] for pid in posts.get("order", [])]
                    ordered.extend(batch)
                    if len(batch) < 200:
                        break
                    page += 1
                ordered.sort(key=lambda p: (p.get("create_at", 0), p.get("message", "")))
                channels.append(
                    {
                        "name": ch["name"],
                        "type": ch["type"],
                        "members": members,
                        "posts": [
                            {
                                "user": _username(users, p, self, relay, ctx),
                                "message": p["message"],
                                "thread": bool(p.get("root_id")),
                            }
                            for p in ordered
                            if not p.get("type")
                        ],
                    }
                )
            team_members = sorted(
                m["username"] for m in self._pages(relay, ctx, f"/users?in_team={team['id']}&")
            )
            teams.append(
                {
                    "name": team["name"],
                    "members": team_members,
                    "channels": sorted(channels, key=lambda c: c["name"]),
                }
            )
        tokens: dict[str, list[str]] = {}
        for u in self._pages(relay, ctx, "/users?sort="):
            listed = self.api(relay, ctx, "GET", f"/users/{u['id']}/tokens") or []
            # The control plane's own token is machinery, not state a user could have made.
            active = sorted(
                t.get("description", "")
                for t in listed
                if t.get("is_active", True)
                and not (u["username"] == ADMIN and t.get("description") == "control")
            )
            if active:
                tokens[u["username"]] = active
        return {"product": "mattermost", "users": users, "teams": teams, "tokens": tokens}

    def _pages(self, relay: Relay, ctx: TwinContext, path: str) -> list[dict[str, Any]]:
        sep = "" if path.endswith(("?", "&")) else "&"
        items: list[dict[str, Any]] = []
        page = 0
        while True:
            batch = self.api(relay, ctx, "GET", f"{path}{sep}per_page=200&page={page}") or []
            items.extend(batch)
            if len(batch) < 200:
                return items
            page += 1


_user_names: dict[str, str] = {}


def _username(
    users: list[dict[str, Any]],
    post: dict[str, Any],
    mm: Mattermost,
    relay: Relay,
    ctx: TwinContext,
) -> str:
    uid = post.get("user_id", "")
    if uid not in _user_names:
        user = mm.api(relay, ctx, "GET", f"/users/{uid}")
        _user_names[uid] = user["username"]
    return _user_names[uid]


def _json_field(text: str, key: str) -> str:
    import json

    start = text.find("{")
    data = json.JSONDecoder().raw_decode(text[start:])[0] if start >= 0 else {}
    if isinstance(data, list):
        data = data[0] if data else {}
    value = data.get(key)
    if not value:
        raise MirrorError(
            "mmctl did not return a token.", text.strip()[-200:], "See: mirror logs chat"
        )
    return str(value)
