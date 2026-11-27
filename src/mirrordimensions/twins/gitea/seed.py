# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Load the synthetic company into Gitea.

Through Gitea's API as each person (the administrator acting with `Sudo`), so activity is
attributed to its author. Commits carry backdated author and committer dates. Times the API
cannot set (issues, comments, accounts, the activity feed) are backdated in the database
afterwards, and seeding leaves no tokens behind (build spec: "Seeding traces").
"""

# Product APIs return untyped JSON.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from mirrordimensions.engine.docker_api import Docker
from mirrordimensions.errors import MirrorError
from mirrordimensions.twins.base import TwinContext
from mirrordimensions.twins.relay import Relay
from mirrordimensions.world.clock import WorkClock
from mirrordimensions.world.model import World

LABEL_COLORS = {
    "bug": "#d73a4a",
    "enhancement": "#a2eeef",
    "docs": "#0075ca",
    "chore": "#cfd3d7",
    "incident": "#b60205",
    "task": "#fbca04",
    "question": "#d876e3",
    "needs-decision": "#e4e669",
    "performance": "#5319e7",
    "good-first-issue": "#7057ff",
}


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class GiteaSeeder:
    def __init__(self, gitea: Any, relay: Relay, ctx: TwinContext, docker: Docker) -> None:
        self.g = gitea
        self.relay = relay
        self.ctx = ctx
        self.docker = docker

    def api(
        self,
        method: str,
        path: str,
        body: Any = None,
        sudo: str | None = None,
        ok: tuple[int, ...] = (200, 201, 204),
    ) -> Any:
        headers = {"Sudo": sudo} if sudo else None
        resp = self.relay.request(
            method,
            f"http://{self.ctx.app_ip}:3000/api/v1{path}",
            body=body,
            basic=("git-admin", self.ctx.secrets["admin_password"]),
            headers=headers,
        )
        if resp.status not in ok:
            raise MirrorError(
                f"Gitea refused {method} {path} while seeding.",
                f"HTTP {resp.status}: {resp.body[:200]!r}",
                "Run mirror world create --resume; if it repeats, see: mirror logs code",
            )
        return resp.json() if resp.body else None

    def sql(self, statement: str) -> str:
        out = self.docker.exec(
            self.ctx.db_container, ["psql", "-U", "gitea", "-d", "gitea", "-tAc", statement]
        )
        if out.exit_code != 0:
            raise MirrorError(
                "Backdating Gitea's history failed.",
                out.output.strip()[-300:],
                "See: mirror logs code",
            )
        return out.output

    def seed(self, world: World, now: datetime) -> dict[str, int]:
        self.clock = WorkClock(now, world.utc_offset)
        people = {p.id: p for p in world.people}
        password = self.ctx.secrets["user_password"]
        for p in world.people:
            if (
                self.relay.request(
                    "GET",
                    f"http://{self.ctx.app_ip}:3000/api/v1/users/{p.username}",
                    basic=("git-admin", self.ctx.secrets["admin_password"]),
                ).status
                == 404
            ):
                self.api(
                    "POST",
                    "/admin/users",
                    {
                        "username": p.username,
                        "full_name": p.name,
                        "email": p.email,
                        "password": password,
                        "must_change_password": False,
                        "send_notify": False,
                        # Signed-in colleagues can find each other, as on a company server.
                        "visibility": "limited",
                    },
                )
        org = world.org
        if (
            self.relay.request(
                "GET",
                f"http://{self.ctx.app_ip}:3000/api/v1/orgs/{org}",
                basic=("git-admin", self.ctx.secrets["admin_password"]),
            ).status
            == 404
        ):
            self.api(
                "POST",
                "/orgs",
                {"username": org, "full_name": world.company, "visibility": "private"},
            )
        # Engineers can write; everyone else at the company can read and comment.
        engineers = [p.username for p in world.people if "engineer" in p.roles]
        staff = [p.username for p in world.people if "engineer" not in p.roles]
        for name, permission, members in (
            ("engineering", "write", engineers),
            ("staff", "read", staff),
        ):
            team = self.api(
                "POST",
                f"/orgs/{org}/teams",
                {
                    "name": name,
                    "permission": permission,
                    "units": ["repo.code", "repo.issues", "repo.pulls"],
                    "includes_all_repositories": True,
                },
                ok=(201, 409, 422),
            )
            if team and "id" in team:
                for username in members:
                    self.api("PUT", f"/teams/{team['id']}/members/{username}", ok=(204,))
        counts = {"repositories": 0, "commits": 0, "issues": 0, "comments": 0}
        backdates: list[str] = []
        # Create repositories one at a time (concurrent creation in one organization races
        # inside Gitea), then fill them in parallel: their contents are independent.
        self.created: set[str] = set()
        for repo in world.repositories:
            full = f"{org}/{repo.name}"
            if (
                self.relay.request(
                    "GET",
                    f"http://{self.ctx.app_ip}:3000/api/v1/repos/{full}",
                    basic=("git-admin", self.ctx.secrets["admin_password"]),
                ).status
                == 200
            ):
                continue
            self.api(
                "POST",
                f"/orgs/{org}/repos",
                {
                    "name": repo.name,
                    "description": repo.description,
                    "private": repo.private,
                    "default_branch": "main",
                    "auto_init": False,
                },
            )
            self.created.add(repo.name)
        with ThreadPoolExecutor(max_workers=6) as pool:
            for repo_counts, repo_backdates in pool.map(
                lambda r: self._seed_repo(world, r, people, now), list(world.repositories)
            ):
                for key, value in repo_counts.items():
                    counts[key] += value
                backdates += repo_backdates
        for p in world.people:
            started = self.clock.unix(p.started_ago, f"user:{p.username}")
            backdates.append(
                f"UPDATE \"user\" SET created_unix={started}, updated_unix={started} WHERE lower_name='{p.username}';"
            )
            if p.left_ago is not None:
                backdates.append(
                    f"UPDATE \"user\" SET is_active=false, prohibit_login=true WHERE lower_name='{p.username}';"
                )
        self._apply_backdates(backdates, now, world)
        return counts

    def _seed_repo(
        self, world: World, repo: Any, people: dict[str, Any], now: datetime
    ) -> tuple[dict[str, int], list[str]]:
        org = world.org
        counts = {"repositories": 0, "commits": 0, "issues": 0, "comments": 0}
        backdates: list[str] = []
        if repo.name not in self.created:
            return (
                counts,
                backdates,
            )  # existed before this run: seeding is idempotent per repository
        if True:
            full = f"{org}/{repo.name}"
            counts["repositories"] += 1
            existing: set[str] = set()
            for commit in repo.commits:
                author = people[commit.author]
                files: list[dict[str, Any]] = []
                for path, text in commit.files.items():
                    if text is None:
                        if path in existing:
                            sha = self.api("GET", f"/repos/{full}/contents/{path}?ref=main")["sha"]
                            files.append({"operation": "delete", "path": path, "sha": sha})
                            existing.discard(path)
                        continue
                    entry: dict[str, Any] = {
                        "operation": "update" if path in existing else "create",
                        "path": path,
                        "content": base64.b64encode(text.encode()).decode(),
                    }
                    if path in existing:
                        entry["sha"] = self.api("GET", f"/repos/{full}/contents/{path}?ref=main")[
                            "sha"
                        ]
                    files.append(entry)
                    existing.add(path)
                if not files:
                    continue
                when = _iso(self.clock.at(commit.ago, f"commit:{repo.name}:{commit.message}"))
                body = {
                    "files": files,
                    "message": commit.message,
                    "branch": "main",
                    "author": {"name": author.name, "email": author.email},
                    "committer": {"name": author.name, "email": author.email},
                    "dates": {"author": when, "committer": when},
                }
                if counts["commits"] == 0 and not existing - {f["path"] for f in files}:
                    pass
                self.api("POST", f"/repos/{full}/contents", body)
                counts["commits"] += 1
            shas = [
                c["sha"]
                for c in self.api(
                    "GET", f"/repos/{full}/commits?sha=main&limit=200&stat=false&files=false"
                )
            ]
            for branch, back in repo.branches.items():
                base = shas[min(back, len(shas) - 1)]
                self.api(
                    "POST",
                    f"/repos/{full}/branches",
                    {"new_branch_name": branch, "old_ref_name": base},
                    ok=(201, 409),
                )
            labels: dict[str, int] = {}
            for name in sorted({lb for issue in repo.issues for lb in issue.labels}):
                made = self.api(
                    "POST",
                    f"/repos/{full}/labels",
                    {"name": name, "color": LABEL_COLORS.get(name, "#ededed")},
                )
                labels[name] = made["id"]
            for issue in sorted(repo.issues, key=lambda i: i.number):
                author = people[issue.author]
                created = self.api(
                    "POST",
                    f"/repos/{full}/issues",
                    {
                        "title": issue.title,
                        "body": issue.body,
                        "assignees": [people[issue.assignee].username] if issue.assignee else [],
                        "labels": [labels[lb] for lb in issue.labels],
                    },
                    sudo=author.username,
                )
                counts["issues"] += 1
                number = created["number"]
                backdates.append(
                    _issue_sql(
                        created["id"],
                        self.clock.at(issue.ago, f"issue:{repo.name}:{issue.number}"),
                        self.clock.at(issue.closed_ago, f"closed:{repo.name}:{issue.number}")
                        if issue.closed_ago
                        else None,
                    )
                )
                for comment in issue.comments:
                    made = self.api(
                        "POST",
                        f"/repos/{full}/issues/{number}/comments",
                        {"body": comment.body},
                        sudo=people[comment.author].username,
                    )
                    counts["comments"] += 1
                    ts = self.clock.unix(comment.ago, f"comment:{repo.name}:{made['id']}")
                    backdates.append(
                        f"UPDATE comment SET created_unix={ts}, updated_unix={ts} WHERE id={made['id']};"
                    )
                if issue.closed_ago is not None:
                    self.api(
                        "PATCH",
                        f"/repos/{full}/issues/{number}",
                        {"state": "closed"},
                        sudo=author.username,
                    )
        return counts, backdates

    def _apply_backdates(self, statements: list[str], now: datetime, world: World) -> None:
        for i in range(0, len(statements), 200):
            self.sql("BEGIN;" + "".join(statements[i : i + 200]) + "COMMIT;")
        firsts = {r.name: max(c.ago for c in r.commits) for r in world.repositories if r.commits}
        created = "".join(
            # Each repository was created shortly before its first commit.
            f"UPDATE repository SET created_unix={self.clock.unix(ago + 20, f'repo:{name}')} "
            f"WHERE lower_name='{name}';"
            for name, ago in firsts.items()
        )
        # The administrator account dates from when the server was installed, and has the
        # name an IT team gives it.
        installed = self.clock.unix(
            max([*firsts.values(), *(p.started_ago for p in world.people if "admin" in p.roles)])
            + 3 * 24 * 60,
            "install",
        )
        it_name = f"{world.company} IT".replace("'", "''")
        self.sql(
            "BEGIN;"
            + created
            + f'UPDATE "user" SET created_unix={installed}, updated_unix={installed}, '
            f"full_name='{it_name}' WHERE lower_name='git-admin';"
            "UPDATE repository r SET updated_unix=COALESCE((SELECT max(i.updated_unix) FROM issue i WHERE i.repo_id=r.id), r.updated_unix);"
            # The activity feed: each entry takes the time of what it refers to. Pushes take
            # their head commit's (backdated) time; repository creation takes the repository's.
            "UPDATE action a SET created_unix=c.created_unix FROM comment c WHERE a.comment_id=c.id AND a.comment_id>0;"
            "UPDATE action a SET created_unix=i.created_unix FROM issue i WHERE a.comment_id=0 AND a.repo_id=i.repo_id "
            "AND a.content LIKE (i.index::text || '|%');"
            f"UPDATE action SET created_unix={PUSH_TIME} WHERE op_type=5 AND content LIKE '{{%';"
            "UPDATE action a SET created_unix=r.created_unix FROM repository r WHERE a.op_type=1 AND a.repo_id=r.id;"
            "DELETE FROM action WHERE op_type=18;"
            "DELETE FROM access_token;"
            "COMMIT;"
        )


# The head commit's time, from the push entry's own JSON (Gitea's PushCommits).
PUSH_TIME = (
    "COALESCE(extract(epoch FROM (content::json->'HeadCommit'->>'Timestamp')::timestamptz),"
    " extract(epoch FROM (content::json->'Commits'->0->>'Timestamp')::timestamptz), created_unix)::bigint"
)


def _issue_sql(issue_id: int, created: datetime, closed: datetime | None) -> str:
    c = int(created.timestamp())
    sql = (
        f"UPDATE issue SET created_unix={c}, updated_unix={c}, deadline_unix=0 WHERE id={issue_id};"
    )
    if closed is not None:
        k = int(closed.timestamp())
        sql += f"UPDATE issue SET closed_unix={k}, updated_unix={k} WHERE id={issue_id};"
        sql += f"UPDATE comment SET created_unix={k}, updated_unix={k} WHERE issue_id={issue_id} AND type=2;"
    return sql


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)
