# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Gitea: code hosting and issue tracking. Upstream image, configured, never modified.

Configured to look like a long-lived corporate install: registration closed, sign-in
required, no SSH (Git runs over HTTPS so it is captured), offline (no avatars or update
checks from the internet), webhooks limited to external hosts (which the engine firewall
then drops and logs), and the company's name as the site name.
"""

# Product APIs return untyped JSON.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import contextlib
import time
from typing import Any

from mirrordimensions.engine.docker_api import ContainerSpec, Docker
from mirrordimensions.errors import MirrorError
from mirrordimensions.twins.base import Identity, TwinContext
from mirrordimensions.twins.relay import Relay

IMAGE = "gitea/gitea:28.4.0-rootless@sha256:15ab7fadb44981a2b781f40c712cad07066197f395100ea1c6326e14e5bb073a"
DB_IMAGE = (
    "postgres:17-alpine@sha256:f9cf3e1f0066f0eb0c48707d864f0ac5941e9ff454a072077d97a4d278d07d73"
)
PORT = 3000
ADMIN = "git-admin"
PERMISSIONS = {"read": "read", "write": "write", "admin": "admin"}


class Gitea:
    product = "gitea"
    upstream_port = PORT
    static_path = "/assets/img/logo.svg"

    def _base(self, ctx: TwinContext) -> str:
        return f"http://{ctx.app_ip}:{PORT}"

    def volumes(self, ctx: TwinContext) -> list[str]:
        return [f"{ctx.volume_prefix}data", f"{ctx.volume_prefix}db"]

    def containers(self, ctx: TwinContext) -> list[ContainerSpec]:
        db_password = ctx.secrets["db_password"]
        settings = {"default_branch": "main", **ctx.settings}
        env = {
            "GITEA__database__DB_TYPE": "postgres",
            "GITEA__database__HOST": f"{ctx.db_ip}:5432",
            "GITEA__database__NAME": "gitea",
            "GITEA__database__USER": "gitea",
            "GITEA__database__PASSWD": db_password,
            # An empty section name targets app.ini's top level (environment-to-ini convention).
            "GITEA____APP_NAME": f"{ctx.company} Git",
            "GITEA__server__DOMAIN": ctx.hostname,
            "GITEA__server__ROOT_URL": f"https://{ctx.hostname}/",
            "GITEA__server__HTTP_PORT": str(PORT),
            "GITEA__server__DISABLE_SSH": "true",
            "GITEA__server__START_SSH_SERVER": "false",
            "GITEA__server__OFFLINE_MODE": "true",
            "GITEA__server__LFS_START_SERVER": "false",
            "GITEA__security__INSTALL_LOCK": "true",
            "GITEA__security__SECRET_KEY": ctx.secrets["secret_key"],
            "GITEA__security__INTERNAL_TOKEN": ctx.secrets["internal_token"],
            # Trust X-Forwarded-* from the gateway's address on the system network only.
            "GITEA__security__REVERSE_PROXY_TRUSTED_PROXIES": f"{ctx.gateway_ip}/32",
            "GITEA__service__DISABLE_REGISTRATION": "true",
            "GITEA__service__REQUIRE_SIGNIN_VIEW": "true",
            "GITEA__service__DEFAULT_KEEP_EMAIL_PRIVATE": "true",
            "GITEA__service__ENABLE_NOTIFY_MAIL": "false",
            "GITEA__mailer__ENABLED": "false",
            "GITEA__repository__DEFAULT_BRANCH": str(settings["default_branch"]),
            "GITEA__webhook__ALLOWED_HOST_LIST": "external",
            "GITEA__migrations__ALLOW_LOCALNETWORKS": "false",
            "GITEA__cron.update_checker__ENABLED": "false",
            "GITEA__actions__ENABLED": "false",
            "GITEA__log__LEVEL": "Warn",
        }
        return [
            ContainerSpec(
                name=ctx.db_container,
                image=DB_IMAGE,
                networks={ctx.network: ctx.db_ip},
                dns=ctx.dns,
                env={
                    "POSTGRES_USER": "gitea",
                    "POSTGRES_PASSWORD": db_password,
                    "POSTGRES_DB": "gitea",
                },
                cap_add=["CHOWN", "SETUID", "SETGID", "DAC_OVERRIDE", "FOWNER"],
                volumes={f"{ctx.volume_prefix}db": "/var/lib/postgresql/data"},
            ),
            ContainerSpec(
                name=ctx.app_container,
                image=IMAGE,
                networks={ctx.network: ctx.app_ip},
                dns=ctx.dns,
                env=env,
                volumes={f"{ctx.volume_prefix}data": "/var/lib/gitea"},
            ),
        ]

    def wait_ready(self, relay: Relay, ctx: TwinContext, timeout_s: float) -> None:
        relay.wait_for(f"{self._base(ctx)}/api/healthz", timeout_s)

    # -- administration ------------------------------------------------------

    def _admin(self, ctx: TwinContext) -> tuple[str, str]:
        return (ADMIN, ctx.secrets["admin_password"])

    def bootstrap(self, docker: Docker, relay: Relay, ctx: TwinContext) -> None:
        """The site administrator, created with Gitea's own CLI. Idempotent."""
        probe = relay.request("GET", f"{self._base(ctx)}/api/v1/user", basic=self._admin(ctx))
        if probe.status == 200:
            return
        out = docker.exec(
            ctx.app_container,
            [
                "gitea",
                "admin",
                "user",
                "create",
                "--admin",
                "--username",
                ADMIN,
                "--password",
                ctx.secrets["admin_password"],
                "--email",
                f"{ADMIN}@{ctx.hostname.split('.', 1)[-1]}",
                "--must-change-password=false",
                "--config",
                "/etc/gitea/app.ini",
            ],
        )
        if out.exit_code != 0 and "already exists" not in out.output:
            raise MirrorError(
                "Could not create the Gitea administrator.",
                out.output.strip()[-300:],
                "See: mirror logs code",
            )

    def api(
        self,
        relay: Relay,
        ctx: TwinContext,
        method: str,
        path: str,
        body: Any = None,
        ok: tuple[int, ...] = (200, 201, 204),
    ) -> Any:
        resp = relay.request(
            method, f"{self._base(ctx)}/api/v1{path}", body=body, basic=self._admin(ctx)
        )
        if resp.status not in ok:
            raise MirrorError(
                f"Gitea refused {method} {path}.",
                f"HTTP {resp.status}: {resp.body[:200]!r}",
                "See: mirror logs code",
            )
        return resp.json() if resp.body else None

    def issue_identity(
        self,
        relay: Relay,
        ctx: TwinContext,
        username: str,
        full_name: str,
        email: str,
        grants: dict[str, Any],
    ) -> Identity:
        """Ensure the account exists with exactly these grants; return production-form credentials."""
        password = ctx.secrets.get(f"user:{username}") or ctx.secrets["user_password"]
        existing = relay.request(
            "GET", f"{self._base(ctx)}/api/v1/users/{username}", basic=self._admin(ctx)
        )
        if existing.status == 404:
            self.api(
                relay,
                ctx,
                "POST",
                "/admin/users",
                {
                    "username": username,
                    "full_name": full_name,
                    "email": email,
                    "password": password,
                    "must_change_password": False,
                    "send_notify": False,
                    "visibility": "private",
                },
            )
        repos: dict[str, str] = dict(grants.get("repos", {}))
        owner = grants.get("owner")
        for repo, level in repos.items():
            if level not in PERMISSIONS:
                raise MirrorError(
                    f"Unknown Gitea permission {level!r} for {repo}.",
                    "Use read, write or admin.",
                    "Fix the agent file.",
                )
            full = repo if "/" in repo else f"{owner}/{repo}"
            self.api(
                relay,
                ctx,
                "PUT",
                f"/repos/{full}/collaborators/{username}",
                {"permission": PERMISSIONS[level]},
            )
        token_name = "automation"  # noqa: S105 (the token's name, not a secret)
        tokens = relay.request(
            "GET", f"{self._base(ctx)}/api/v1/users/{username}/tokens", basic=(username, password)
        )
        for tok in tokens.json() or []:
            if tok.get("name") == token_name:
                relay.request(
                    "DELETE",
                    f"{self._base(ctx)}/api/v1/users/{username}/tokens/{tok['id']}",
                    basic=(username, password),
                )
        created = relay.request(
            "POST",
            f"{self._base(ctx)}/api/v1/users/{username}/tokens",
            basic=(username, password),
            body={
                "name": token_name,
                "scopes": ["write:repository", "write:issue", "read:user", "read:organization"],
            },
        )
        if created.status != 201:
            raise MirrorError(
                "Could not issue a Gitea token.",
                f"HTTP {created.status}: {created.body[:200]!r}",
                "See: mirror logs code",
            )
        token = str(created.json()["sha1"])
        return Identity(
            username=username,
            password=password,
            token=token,
            env={"GITEA_URL": f"https://{ctx.hostname}", "GITEA_TOKEN": token},
        )

    def admin_fetch(
        self, relay: Relay, ctx: TwinContext, method: str, path: str, body: bytes
    ) -> tuple[int, bytes]:
        # The public Host, as the gateway sends it, so links in the answer use the real hostname.
        headers = {"Host": ctx.hostname, "X-Forwarded-Proto": "https"}
        if body:
            headers["Content-Type"] = "application/json"
        resp = relay.request(
            method,
            f"{self._base(ctx)}{path}",
            body=body or None,
            basic=self._admin(ctx),
            headers=headers,
        )
        return resp.status, resp.body

    def fetch_external(self, relay: Relay, ctx: TwinContext, url: str) -> None:
        """Ask Gitea to import a repository from a URL: its own outbound fetch feature."""
        # Gitea waits on the outbound connection, which the engine firewall drops silently,
        # so the call times out; the attempt itself is what the caller checks for.
        # A unique name each time: a timed-out import leaves its repository behind, and a second
        # import with the same name would fail at once without fetching anything.
        name = f"import-{time.time_ns() % 10**9}"
        with contextlib.suppress(MirrorError):
            relay.request(
                "POST",
                f"{self._base(ctx)}/api/v1/repos/migrate",
                basic=self._admin(ctx),
                timeout=6,
                body={"clone_addr": url, "repo_name": name, "repo_owner": ADMIN, "private": True},
            )
        for repo in self._all(relay, ctx, f"/users/{ADMIN}/repos"):
            if str(repo.get("name", "")).startswith("import-"):
                relay.request(
                    "DELETE",
                    f"{self._base(ctx)}/api/v1/repos/{ADMIN}/{repo['name']}",
                    basic=self._admin(ctx),
                )

    # -- state -----------------------------------------------------------------

    def dump_state(self, relay: Relay, ctx: TwinContext) -> dict[str, Any]:
        """What a user could observe, normalized and sorted so identical worlds dump identically."""
        users = sorted(
            (
                {
                    "login": u["login"],
                    "full_name": u.get("full_name", ""),
                    "admin": u.get("is_admin", False),
                    "active": u.get("active", True),
                }
                for u in self._all(relay, ctx, "/admin/users")
            ),
            key=lambda u: u["login"],
        )
        orgs = sorted(o["username"] for o in self._all(relay, ctx, "/admin/orgs"))
        repos: list[dict[str, Any]] = []
        for repo in sorted(
            self._all(relay, ctx, "/repos/search", key="data"), key=lambda r: r["full_name"]
        ):
            full = repo["full_name"]
            branch = repo.get("default_branch") or "main"
            tree = relay.request(
                "GET",
                f"{self._base(ctx)}/api/v1/repos/{full}/git/trees/{branch}?recursive=1&per_page=10000",
                basic=self._admin(ctx),
            )
            files = (
                sorted(
                    (
                        f"{e['path']}:{e['sha']}"
                        for e in (tree.json() or {}).get("tree", [])
                        if e.get("type") == "blob"
                    ),
                )
                if tree.status == 200
                else []
            )
            issues = [
                {
                    "number": i["number"],
                    "title": i["title"],
                    "state": i["state"],
                    "pull": i.get("pull_request") is not None,
                    "labels": sorted(lb["name"] for lb in i.get("labels", [])),
                    "comments": i.get("comments", 0),
                }
                for i in self._all(relay, ctx, f"/repos/{full}/issues?state=all&type=all")
            ]
            collaborators = sorted(
                f"{c['login']}:{self._permission(relay, ctx, full, c['login'])}"
                for c in self._all(relay, ctx, f"/repos/{full}/collaborators")
            )
            hooks = sorted(
                h.get("config", {}).get("url", "")
                for h in self._all(relay, ctx, f"/repos/{full}/hooks")
            )
            keys = sorted(k.get("title", "") for k in self._all(relay, ctx, f"/repos/{full}/keys"))
            repos.append(
                {
                    "name": full,
                    "private": repo.get("private"),
                    "default_branch": branch,
                    "files": files,
                    "issues": sorted(issues, key=lambda i: i["number"]),
                    "collaborators": collaborators,
                    "webhooks": hooks,
                    "deploy_keys": keys,
                }
            )
        tokens: dict[str, list[str]] = {}
        for user in users:
            listed = relay.request(
                "GET",
                f"{self._base(ctx)}/api/v1/users/{user['login']}/tokens",
                basic=self._admin(ctx),
                headers={"Sudo": user["login"]},
            )
            if listed.status == 200:
                tokens[user["login"]] = sorted(t["name"] for t in listed.json() or [])
        return {"product": "gitea", "users": users, "orgs": orgs, "repos": repos, "tokens": tokens}

    def _permission(self, relay: Relay, ctx: TwinContext, repo: str, login: str) -> str:
        resp = relay.request(
            "GET",
            f"{self._base(ctx)}/api/v1/repos/{repo}/collaborators/{login}/permission",
            basic=self._admin(ctx),
        )
        return str(resp.json().get("permission", "")) if resp.status == 200 else ""

    def _all(
        self, relay: Relay, ctx: TwinContext, path: str, key: str | None = None
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        sep = "&" if "?" in path else "?"
        page = 1
        while True:
            resp = relay.request(
                "GET",
                f"{self._base(ctx)}/api/v1{path}{sep}limit=50&page={page}",
                basic=self._admin(ctx),
            )
            if resp.status != 200:
                return items
            data = resp.json()
            batch: list[dict[str, Any]] = (
                data.get(key, []) if key and isinstance(data, dict) else (data or [])
            )
            items.extend(batch)
            if len(batch) < 50:
                return items
            page += 1
