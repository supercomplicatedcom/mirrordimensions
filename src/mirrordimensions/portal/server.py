# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The portal's HTTP server: `/api/v1` over the service layer, and the built front end.

Each endpoint calls one service function and returns its model as JSON; there is no logic
in the handlers. The server binds to 127.0.0.1 only and is never attached to any sandbox
network.

Access (build spec, "Portal", Access): a random token is made at start and printed in the
address. Opening that address once sets an HttpOnly, SameSite=Strict cookie; every other
request needs the cookie or `Authorization: Bearer <token>`. This keeps out other local
users and stray browser tabs; it is not multi-user authentication. Two more checks close
the browser-side gaps a token alone leaves:

- the Host header must name the loopback address and port, so a web page cannot reach the
  portal by pointing its own domain at 127.0.0.1 (DNS rebinding);
- requests that change anything must carry `X-Mirror-Portal: 1`, which a cross-site form
  or image cannot send.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import secrets
import threading
import webbrowser
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from mirrordimensions.errors import LockHeldError, MirrorError
from mirrordimensions.hostos.files import write_text
from mirrordimensions.project import MANIFEST, Project
from mirrordimensions.service import agents as agents_svc
from mirrordimensions.service import changes as changes_svc
from mirrordimensions.service import company as company_svc
from mirrordimensions.service import environment as env_svc
from mirrordimensions.service import health as health_svc
from mirrordimensions.service import imports as imports_svc
from mirrordimensions.service import load_project, runlog
from mirrordimensions.service import onboard as onboard_svc
from mirrordimensions.service import runs as runs_svc
from mirrordimensions.service import sandbox as sandbox_svc
from mirrordimensions.service import scenarios as scen_svc
from mirrordimensions.service import systems as systems_svc
from mirrordimensions.service import world as world_svc
from mirrordimensions.service import worlds as worlds_svc
from mirrordimensions.service.changes import Change
from mirrordimensions.trace import steps as steps_mod
from mirrordimensions.trace import timeline

HOST = "127.0.0.1"
COOKIE = "mirror_portal"
WRITE_HEADER = "x-mirror-portal"
STATIC = Path(__file__).parent / "static"
POLL_S = 0.25

Next = Callable[[Request], Awaitable[Response]]


class ProjectInfo(BaseModel):
    name: str | None
    state: str
    root: str
    isolation: str | None
    pending_changes: int


class StartRun(BaseModel):
    scenario: str
    agent: str


class PortalState:
    """Which world the portal serves now. Switching moves the marker `mirror doctor` reads
    to find the portal's port, so the egress check probes the portal of the world it checks."""

    def __init__(self, project: Project, port: int) -> None:
        self.project = project
        self.port = port

    def switch(self, project: Project) -> None:
        marker = self.project.state_dir / sandbox_svc.PORTAL_FILE
        if marker.is_file():
            marker.unlink(missing_ok=True)
            write_text(
                project.state_dir / sandbox_svc.PORTAL_FILE,
                json.dumps({"port": self.port, "pid": os.getpid()}) + "\n",
                owner_only=True,
            )
        self.project = project


class SetVisibility(BaseModel):
    visibility: str


class SetGrant(BaseModel):
    resource: str
    grant: str


class TryRequest(BaseModel):
    method: str
    path: str
    body: str = ""


class BuildJob(BaseModel):
    """A long operation started from the portal (applying changes, creating a world): its
    steps so far, then its result."""

    running: bool = False
    steps: list[str] = []
    result: Any = None
    error: dict[str, str] | None = None


def _start(job: BuildJob, what: str, work: Callable[[], Any]) -> BuildJob:
    """Run `work` in the background, recording its steps and its result or error."""
    if job.running:
        raise MirrorError(f"{what} is already under way.", "", "Wait for it to finish.")
    job.running, job.steps, job.result, job.error = True, [], None, None

    def run() -> None:
        try:
            job.result = work()
        except MirrorError as exc:
            job.error = {"what": exc.what, "why": exc.why, "fix": exc.fix}
        except Exception as exc:  # noqa: BLE001 (shown to the person who started it)
            job.error = {"what": f"{what} failed.", "why": str(exc), "fix": ""}
        finally:
            job.running = False

    threading.Thread(target=run, name=what, daemon=True).start()
    return job


def _grant_choices(project: Project) -> list[GrantChoice]:
    """Every repository and channel of the world, under the system that grants it."""
    from mirrordimensions.service.agents import _manifest, _world  # pyright: ignore[reportPrivateUsage]

    manifest, world = _manifest(project), _world(project)
    out: list[GrantChoice] = []
    for app in manifest.apps:
        if app.visibility == "absent" or app.build == "unavailable":
            continue
        key, levels = env_svc.grant_vocabulary(manifest, app.id)
        if key == "repos":
            names = sorted(r.name for r in world.repositories)
        elif key == "channels":
            names = sorted(c.name for c in world.channels if c.name != "town-square")
        elif key == "tools":
            from mirrordimensions.service.sandbox import world_plan

            planned = next((a for a in world_plan(project, manifest).apps if a.id == app.id), None)
            names = list(planned.tools.names) if planned and planned.tools else []
        else:
            continue
        out.append(
            GrantChoice(
                app_id=app.id,
                label=env_svc.system_label(app.kind, app.product, app.id),
                key=key,
                levels=list(levels),
                names=names,
            )
        )
    return out


async def _job_events(request: Request, job: BuildJob) -> AsyncIterator[bytes]:
    sent = 0
    while not await request.is_disconnected():
        while sent < len(job.steps):
            yield f"event: step\ndata: {json.dumps(job.steps[sent])}\n\n".encode()
            sent += 1
        if not job.running:
            yield f"event: end\ndata: {job.model_dump_json()}\n\n".encode()
            return
        await asyncio.sleep(POLL_S)


class Folder(BaseModel):
    folder: str


class WorldDraftUpdate(BaseModel):
    folder: str
    fields: worlds_svc.DraftFields


class ImportRead(BaseModel):
    folder: str | None = Field(default=None, description="A world the wizard is defining")
    paths: list[str] = Field(description="Files on this machine, read in place")
    kind: str | None = Field(default=None, description="The kind of file, if not recognized")


class ImportDecision(BaseModel):
    folder: str | None = None
    decision: str


class ImportTarget(BaseModel):
    folder: str | None = None


class ImportApplied(BaseModel):
    changes: list[Change]
    wizard: bool = Field(description="The world is still being defined in the wizard")


class NewAgent(BaseModel):
    name: str


class ModelChoice(BaseModel):
    where: str = Field(description="cloud, self-hosted, in-sandbox or none")
    provider: str | None = None
    host: str | None = None
    upstream: str | None = None
    credential_env: str | None = None
    hosted_tools: str = "block"


class AgentStep(BaseModel):
    step: int
    fields: dict[str, Any] = {}
    model: ModelChoice | None = None


class GrantChoice(BaseModel):
    app_id: str
    label: str
    key: str
    levels: list[str]
    names: list[str]


class RoleDefaults(BaseModel):
    role: str
    person: dict[str, str]
    grants: dict[str, Any]
    lines: list[str]
    options: list[GrantChoice] = Field(description="What could be granted, system by system")


class AddAgent(BaseModel):
    path: str


def _error(exc: MirrorError, status: int = 400) -> JSONResponse:
    return JSONResponse({"what": exc.what, "why": exc.why, "fix": exc.fix}, status_code=status)


def guard(token: str, port: int) -> Callable[[Request, Next], Awaitable[Response]]:
    """Every request: the Host header, the token, and the header changes must carry."""
    hosts = {f"{HOST}:{port}", f"localhost:{port}"}

    def authorized(request: Request) -> bool:
        given = request.cookies.get(COOKIE, "")
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            given = header[7:]
        return bool(given) and hmac.compare_digest(given, token)

    async def check(request: Request, call_next: Next) -> Response:
        if request.headers.get("host", "") not in hosts:
            return Response("Unknown host.", status_code=421)
        offered = request.query_params.get("token")
        if request.url.path == "/" and offered is not None:
            if not hmac.compare_digest(offered, token):
                return HTMLResponse(_LOCKED, status_code=401)
            response = Response(status_code=303, headers={"location": "/"})
            response.set_cookie(COOKIE, token, httponly=True, samesite="strict", path="/")
            return response
        if not authorized(request):
            if request.url.path.startswith("/api/"):
                return JSONResponse(
                    {
                        "what": "Not signed in to the portal.",
                        "why": "Requests need the portal's token.",
                        "fix": "Open the address mirror portal printed.",
                    },
                    status_code=401,
                )
            return HTMLResponse(_LOCKED, status_code=401)
        if (
            request.method not in ("GET", "HEAD", "OPTIONS")
            and request.headers.get(WRITE_HEADER) != "1"
        ):
            return JSONResponse(
                {"what": "Refused.", "why": f"Changes need the {WRITE_HEADER} header.", "fix": ""},
                status_code=403,
            )
        response = await call_next(request)
        response.headers["cache-control"] = "no-store"
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["referrer-policy"] = "no-referrer"
        response.headers.setdefault(
            "content-security-policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        )  # an endpoint's own, stricter policy (stored bodies) is kept
        return response

    return check


_HEAD = '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Mirror</title></head>'
_LOCKED = (
    _HEAD
    + """
<body style="font-family:system-ui,sans-serif;margin:48px;color:#111827">
<h1 style="font-size:20px">Open the portal from its address</h1>
<p>This page needs the address <code>mirror portal</code> printed, which includes a token.
Run <code>mirror portal</code> again to get a new one.</p></body></html>"""
)

_NOT_BUILT = (
    _HEAD
    + """
<body style="font-family:system-ui,sans-serif;margin:48px;color:#111827">
<h1 style="font-size:20px">The portal's web files are not built</h1>
<p>This is a source checkout. Build them once with
<code>npm --prefix src/mirrordimensions/portal/web ci &amp;&amp;
npm --prefix src/mirrordimensions/portal/web run build</code>, then reload.
The API works without them: <a href="/api/v1/project">/api/v1/project</a>.</p></body></html>"""
)


def create_app(project: Project, token: str, port: int, static: Path = STATIC) -> FastAPI:
    app = FastAPI(
        title="MirrorDimensions portal",
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
    )
    app.middleware("http")(guard(token, port))
    # The world the portal serves; the world wizard can point it at another (decision 0022).
    holder = PortalState(project=project, port=port)
    app.state.portal = holder

    @app.exception_handler(LockHeldError)
    async def _locked(_: Request, exc: LockHeldError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return _error(exc, 409)

    @app.exception_handler(MirrorError)
    async def _mirror_error(_: Request, exc: MirrorError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        missing = exc.what.startswith(("There is no", "There are no")) or " has no " in exc.what
        return _error(exc, 404 if missing else 400)

    api = "/api/v1"

    @app.get(f"{api}/project")
    def get_project() -> ProjectInfo:  # pyright: ignore[reportUnusedFunction]
        h = health_svc.health(holder.project, containers=False)
        return ProjectInfo(
            name=h.project,
            state=h.state,
            root=str(holder.project.root),
            isolation=(h.doctor or {}).get("isolation"),
            pending_changes=len(env_svc.pending_changes(holder.project)),
        )

    @app.get(f"{api}/environment/graph")
    def get_graph() -> env_svc.Graph:  # pyright: ignore[reportUnusedFunction]
        return env_svc.environment_graph(holder.project)

    @app.get(f"{api}/agents")
    def get_agents() -> list[agents_svc.AgentSummary]:  # pyright: ignore[reportUnusedFunction]
        return agents_svc.list_agents(holder.project)

    @app.post(f"{api}/agents")
    def post_agent(body: AddAgent) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        agent = agents_svc.add_agent(holder.project, Path(body.path).expanduser())
        return {"name": agent.name}

    @app.delete(f"{api}/agents/{{name}}")
    def delete_agent(name: str) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        agents_svc.remove_agent(holder.project, name)
        return {"removed": name}

    @app.get(f"{api}/agents/{{name}}/reach")
    def get_reach(name: str, run: str | None = None) -> runs_svc.Reach:  # pyright: ignore[reportUnusedFunction]
        return runs_svc.agent_reach(holder.project, name, run)

    @app.get(f"{api}/agents/{{name}}/grants")
    def get_grants(name: str) -> list[env_svc.GrantSystem]:  # pyright: ignore[reportUnusedFunction]
        return env_svc.grant_options(holder.project, name)

    @app.patch(f"{api}/agents/{{name}}/grants")
    def patch_grant(name: str, body: SetGrant) -> changes_svc.Change:  # pyright: ignore[reportUnusedFunction]
        return env_svc.set_grant(holder.project, name, body.resource, body.grant)

    @app.patch(f"{api}/environment/apps/{{app_id}}")
    def patch_app(app_id: str, body: SetVisibility) -> changes_svc.Change:  # pyright: ignore[reportUnusedFunction]
        return env_svc.set_visibility(holder.project, app_id, body.visibility)

    @app.get(f"{api}/changes")
    def get_changes() -> list[changes_svc.Change]:  # pyright: ignore[reportUnusedFunction]
        return env_svc.pending_changes(holder.project)

    job = BuildJob()

    @app.post(f"{api}/build")
    def post_build() -> BuildJob:  # pyright: ignore[reportUnusedFunction]
        return _start(
            job,
            "Applying the changes",
            lambda: env_svc.apply_changes(holder.project, on_step=job.steps.append),
        )

    @app.get(f"{api}/build")
    def get_build() -> BuildJob:  # pyright: ignore[reportUnusedFunction]
        return job

    @app.get(f"{api}/build/stream")
    async def stream_build(request: Request) -> StreamingResponse:  # pyright: ignore[reportUnusedFunction]
        return StreamingResponse(
            _job_events(request, job),
            media_type="text/event-stream",
            headers={"x-accel-buffering": "no"},
        )

    # -- worlds: the list, switching, and the world wizard (decision 0022) --------------

    creating = BuildJob()

    def _quiet_engine() -> None:
        if job.running or creating.running or runlog.running(holder.project):
            raise MirrorError(
                "Something is running in this world.",
                "Wait for the run, or for changes being applied, to finish.",
                "",
            )

    @app.get(f"{api}/worlds")
    def get_worlds() -> list[worlds_svc.WorldEntry]:  # pyright: ignore[reportUnusedFunction]
        return worlds_svc.list_worlds(holder.project)

    @app.post(f"{api}/worlds/switch")
    def post_switch(body: Folder) -> worlds_svc.WorldEntry:  # pyright: ignore[reportUnusedFunction]
        _quiet_engine()
        root = worlds_svc.resolve_folder(holder.project, body.folder)
        if not (root / MANIFEST).is_file():
            raise MirrorError(f"There is no world in {root}.", "", "Choose one from the list.")
        holder.switch(load_project(root))
        return next(w for w in worlds_svc.list_worlds(holder.project) if w.current)

    @app.post(f"{api}/worlds/draft")
    def post_world_draft(body: Folder) -> worlds_svc.WorldDraftView:  # pyright: ignore[reportUnusedFunction]
        return worlds_svc.open_draft(holder.project, body.folder)

    @app.patch(f"{api}/worlds/draft")
    def patch_world_draft(body: WorldDraftUpdate) -> worlds_svc.WorldDraftView:  # pyright: ignore[reportUnusedFunction]
        return worlds_svc.update_draft(holder.project, body.folder, body.fields)

    @app.post(f"{api}/worlds/create")
    def post_world_create(body: Folder) -> BuildJob:  # pyright: ignore[reportUnusedFunction]
        _quiet_engine()
        origin = holder.project

        def work() -> dict[str, Any]:
            root = worlds_svc.finish(origin, body.folder)
            creating.steps.append(f"Defined in {root}")
            made = load_project(root)
            last = world_svc.create_world(made, on_stage=creating.steps.append)
            holder.switch(made)  # the portal now serves the new world
            return {"folder": str(root), "last_stage": last}

        return _start(creating, "Creating the world", work)

    @app.get(f"{api}/worlds/create")
    def get_world_create() -> BuildJob:  # pyright: ignore[reportUnusedFunction]
        return creating

    @app.get(f"{api}/worlds/create/stream")
    async def stream_world_create(request: Request) -> StreamingResponse:  # pyright: ignore[reportUnusedFunction]
        return StreamingResponse(
            _job_events(request, creating),
            media_type="text/event-stream",
            headers={"x-accel-buffering": "no"},
        )

    # -- onboarding an agent: the six steps of `mirror agent new` ------------------------

    @app.post(f"{api}/agents/drafts")
    def post_agent_draft(body: NewAgent) -> onboard_svc.AgentDraft:  # pyright: ignore[reportUnusedFunction]
        return onboard_svc.draft_agent(holder.project, body.name)

    @app.get(f"{api}/agents/drafts/{{name}}")
    def get_agent_draft(name: str) -> onboard_svc.AgentDraft:  # pyright: ignore[reportUnusedFunction]
        found = onboard_svc.load_draft(holder.project, name)
        if found is None:
            raise MirrorError(f"There is no agent called {name!r}.", "", "Start onboarding it.")
        return found

    @app.patch(f"{api}/agents/drafts/{{name}}")
    def patch_agent_draft(name: str, body: AgentStep) -> onboard_svc.AgentDraft:  # pyright: ignore[reportUnusedFunction]
        fields = dict(body.fields)
        if body.model is not None:
            m = body.model
            fields["model"] = (
                None
                if m.where == "none"
                else onboard_svc.add_model_route(
                    holder.project,
                    m.where,
                    provider=m.provider,
                    host=m.host,
                    upstream=m.upstream,
                    credential_env=m.credential_env,
                    hosted_tools=m.hosted_tools,
                )
            )
        return onboard_svc.update_draft(holder.project, name, body.step, fields)

    @app.get(f"{api}/roles/{{role}}/defaults")
    def get_role_defaults(  # pyright: ignore[reportUnusedFunction]
        role: str, person: str | None = None, mode: str | None = None
    ) -> RoleDefaults:
        who = onboard_svc.person_for(holder.project, role, person)
        grants = onboard_svc.role_defaults(holder.project, role, person, mode=mode)
        return RoleDefaults(
            role=role,
            person={"username": who.username, "name": who.name, "title": who.title},
            grants=grants,
            lines=onboard_svc.describe_grants(grants),
            options=_grant_choices(holder.project),
        )

    @app.get(f"{api}/onboarding/remote-notice")
    def get_remote_notice() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"notice": onboard_svc.REMOTE_NOTICE}

    @app.post(f"{api}/agents/{{name}}/check")
    def post_agent_check(name: str) -> list[agents_svc.PreflightCheck]:  # pyright: ignore[reportUnusedFunction]
        return agents_svc.check_agent(holder.project, name)

    @app.get(f"{api}/systems")
    def get_systems() -> list[systems_svc.SystemSummary]:  # pyright: ignore[reportUnusedFunction]
        return systems_svc.list_systems(holder.project)

    @app.get(f"{api}/systems/{{app_id}}")
    def get_system(app_id: str) -> systems_svc.SystemDetail:  # pyright: ignore[reportUnusedFunction]
        return systems_svc.show_system(holder.project, app_id)

    @app.put(f"{api}/systems/{{app_id}}/rules/{{name}}")
    def put_rule(app_id: str, name: str, rule: dict[str, Any]) -> changes_svc.Change:  # pyright: ignore[reportUnusedFunction]
        if rule.get("name", name) != name:
            raise MirrorError(
                "The rule's name does not match its address.",
                f"The address names {name!r}; the rule says {rule.get('name')!r}.",
                "",
            )
        return systems_svc.set_rule(holder.project, app_id, {**rule, "name": name})

    @app.delete(f"{api}/systems/{{app_id}}/rules/{{name}}")
    def delete_rule(app_id: str, name: str) -> changes_svc.Change:  # pyright: ignore[reportUnusedFunction]
        return systems_svc.remove_rule(holder.project, app_id, name)

    @app.post(f"{api}/systems/{{app_id}}/try")
    def post_try(app_id: str, body: TryRequest) -> systems_svc.TryResult:  # pyright: ignore[reportUnusedFunction]
        fetch = None
        try:
            fetch = sandbox_svc.admin_fetcher(holder.project, app_id)
        except MirrorError:
            fetch = None  # the sandbox is down: a rule's own answer can still be shown
        return systems_svc.try_request(
            holder.project, app_id, body.method, body.path, body.body.encode(), fetch
        )

    # -- world import (decision 0025): the same draft as `mirror world import` ----------
    # Registered before /world/{part}, which would otherwise take "import" as a part.

    def _importing(folder: str | None, prepare: bool = True) -> Project:
        return worlds_svc.import_project(holder.project, folder, prepare=prepare)

    @app.get(f"{api}/world/import")
    def get_import(folder: str | None = None) -> imports_svc.ImportReview | None:  # pyright: ignore[reportUnusedFunction]
        return imports_svc.peek_import(_importing(folder, prepare=False))

    @app.get(f"{api}/world/import/kinds")
    def get_import_kinds() -> list[imports_svc.ImportKind]:  # pyright: ignore[reportUnusedFunction]
        return imports_svc.kinds()

    @app.post(f"{api}/world/import")
    def post_import(body: ImportRead) -> imports_svc.ImportReview:  # pyright: ignore[reportUnusedFunction]
        paths = [Path(p.strip()).expanduser() for p in body.paths if p.strip()]
        if not paths:
            raise MirrorError("Name at least one file to read.", "", "Type a full path.")
        return worlds_svc.read_import(holder.project, body.folder, paths, body.kind or None)

    @app.patch(f"{api}/world/import/findings/{{subject}}")
    def patch_import(subject: str, body: ImportDecision) -> imports_svc.ImportReview:  # pyright: ignore[reportUnusedFunction]
        return imports_svc.decide(_importing(body.folder, prepare=False), subject, body.decision)

    @app.post(f"{api}/world/import/apply")
    def post_import_apply(body: ImportTarget) -> ImportApplied:  # pyright: ignore[reportUnusedFunction]
        project = _importing(body.folder, prepare=False)
        changes = worlds_svc.apply_import(project)
        return ImportApplied(changes=changes, wizard=worlds_svc.defining(project))

    @app.delete(f"{api}/world/import")
    def delete_import(folder: str | None = None) -> Response:  # pyright: ignore[reportUnusedFunction]
        imports_svc.discard_import(_importing(folder, prepare=False))
        return Response(status_code=204)

    @app.get(f"{api}/world")
    def get_world() -> company_svc.Company:  # pyright: ignore[reportUnusedFunction]
        return company_svc.company(holder.project)

    @app.get(f"{api}/world/{{part}}")
    def get_world_part(part: str) -> company_svc.Company:  # pyright: ignore[reportUnusedFunction]
        if part not in ("people", "projects", "canaries"):
            raise MirrorError(
                f"There is no part {part!r}.", "Parts: people, projects, canaries.", ""
            )
        return company_svc.company(holder.project, (part,))  # pyright: ignore[reportArgumentType]

    @app.get(f"{api}/scenarios")
    def get_scenarios() -> list[scen_svc.ScenarioSummary]:  # pyright: ignore[reportUnusedFunction]
        return scen_svc.list_scenarios(holder.project)

    @app.get(f"{api}/runs")
    def get_runs() -> list[runlog.RunSummary]:  # pyright: ignore[reportUnusedFunction]
        return runlog.list_runs(holder.project)

    @app.post(f"{api}/runs")
    def post_run(body: StartRun) -> runs_svc.RunHandle:  # pyright: ignore[reportUnusedFunction]
        return runs_svc.start_run(holder.project, body.scenario, body.agent)

    @app.get(f"{api}/runs/{{run_id}}")
    def get_run(run_id: str) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        return runlog.get_result(holder.project, run_id)

    @app.post(f"{api}/runs/{{run_id}}/stop")
    def post_stop(run_id: str) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        runs_svc.stop_run(holder.project, run_id)
        return {"stopping": run_id}

    @app.get(f"{api}/runs/{{run_id}}/events")
    def get_events(  # pyright: ignore[reportUnusedFunction]
        run_id: str,
        source: str = "",
        type: str = "",
        q: str = "",
        offset: int = 0,
        limit: int = runlog.PAGE,
        around: int | None = None,
    ) -> runlog.EventPage:
        return runlog.read_events(
            holder.project, run_id, _filter(source, type, q), offset, limit, around
        )

    @app.get(f"{api}/runs/{{run_id}}/events/stream")
    async def stream_events(  # pyright: ignore[reportUnusedFunction]
        request: Request,
        run_id: str,
        source: str = "",
        type: str = "",
        q: str = "",
    ) -> StreamingResponse:
        folder = runs_svc.run_dir(holder.project, run_id)
        keep = _filter(source, type, q)
        return StreamingResponse(
            _sse(request, folder / "events.jsonl", keep),
            media_type="text/event-stream",
            headers={"x-accel-buffering": "no"},
        )

    @app.get(f"{api}/runs/{{run_id}}/steps")
    def get_steps(run_id: str) -> runlog.StepsView:  # pyright: ignore[reportUnusedFunction]
        return runlog.read_steps(holder.project, run_id)

    @app.get(f"{api}/runs/{{run_id}}/steps/stream")
    async def stream_steps(  # pyright: ignore[reportUnusedFunction]
        request: Request, run_id: str
    ) -> StreamingResponse:
        folder = runs_svc.run_dir(holder.project, run_id)
        ctx, _ = runlog.step_context(holder.project, run_id)
        return StreamingResponse(
            _sse_steps(request, folder / "events.jsonl", ctx),
            media_type="text/event-stream",
            headers={"x-accel-buffering": "no"},
        )

    @app.get(f"{api}/runs/{{run_id}}/bodies/{{kind}}/{{name}}")
    def get_body(run_id: str, kind: str, name: str) -> Response:  # pyright: ignore[reportUnusedFunction]
        data, media = runlog.read_body(holder.project, run_id, f"{kind}/{name}")
        # Shown as text, never rendered: an agent wrote much of it.
        return Response(
            data,
            media_type=f"{media}; charset=utf-8",
            headers={
                "content-disposition": "inline",
                "content-security-policy": "default-src 'none'",
            },
        )

    @app.get(f"{api}/runs/{{run_id}}/report")
    def get_report(run_id: str) -> Response:  # pyright: ignore[reportUnusedFunction]
        path = runs_svc.write_report(holder.project, run_id)
        return FileResponse(path, media_type="text/html")

    @app.get(f"{api}/health")
    def get_health() -> health_svc.Health:  # pyright: ignore[reportUnusedFunction]
        return health_svc.health(holder.project)

    @app.post(f"{api}/health/doctor")
    def post_doctor() -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        return health_svc.run_doctor(holder.project)

    @app.post(f"{api}/snapshots/{{name}}/restore")
    def post_restore(name: str) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        return world_svc.reset(holder.project, name).model_dump(mode="json")

    @app.get("/{path:path}")
    def front_end(path: str) -> Response:  # pyright: ignore[reportUnusedFunction]
        if path == "api" or path.startswith("api/"):
            return JSONResponse(
                {"what": "No such API path.", "why": f"/{path}", "fix": "See /api/v1/openapi.json"},
                status_code=404,
            )
        index = static / "index.html"
        if not index.is_file():
            return HTMLResponse(_NOT_BUILT, status_code=503)
        candidate = (static / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(static.resolve()):
            return FileResponse(candidate)
        return FileResponse(index, media_type="text/html")  # the app routes on the client

    return app


def _filter(source: str, kind: str, text: str) -> timeline.Filter | None:
    sources = frozenset(s for s in source.split(",") if s)
    types = frozenset(t for t in kind.split(",") if t)
    if not (sources or types or text):
        return None
    bad = timeline.unknown(sources, timeline.SOURCES) + timeline.unknown(
        types, timeline.all_types()
    )
    if bad:
        raise MirrorError(
            f"Unknown source or event type: {', '.join(sorted(bad))}.",
            f"Sources are: {', '.join(timeline.SOURCES)}.",
            "",
        )
    return timeline.Filter(sources, types, text)


async def _lines(request: Request, path: Path) -> AsyncIterator[dict[str, Any] | None]:
    """Each event written to the run's file, from the first, until the run ends or the page
    goes away; None every few quiet seconds, so the caller can keep the connection open."""
    offset, pending, quiet = 0, "", 0.0
    while not await request.is_disconnected():
        chunk = ""
        if path.is_file():
            with path.open("r", encoding="utf-8", newline="\n") as handle:
                handle.seek(offset)
                chunk = handle.read()
                offset = handle.tell()
        pending += chunk
        *lines, pending = pending.split("\n")
        for line in lines:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            item: dict[str, Any] = event  # pyright: ignore[reportUnknownVariableType]
            yield item
            if item.get("type") == "run.end":
                return
        quiet = 0.0 if lines else quiet + POLL_S
        if quiet >= 10:
            quiet = 0.0
            yield None
        await asyncio.sleep(POLL_S)


END = b"event: end\ndata: {}\n\n"
KEEPALIVE = b": still here\n\n"


async def _sse(request: Request, path: Path, keep: timeline.Filter | None) -> AsyncIterator[bytes]:
    """Each event as one server-sent event, until the run ends."""
    start = None
    async for item in _lines(request, path):
        if item is None:
            yield KEEPALIVE
            continue
        if start is None and item.get("type") == "run.start":
            start = timeline.parse_ts(item)
        if keep is None or keep(item):
            shown = runlog.shown(item, start or timeline.parse_ts(item))
            yield f"id: {item.get('seq')}\nevent: event\ndata: {json.dumps(shown)}\n\n".encode()
        if item.get("type") == "run.end":
            yield END


async def _sse_steps(request: Request, path: Path, ctx: steps_mod.Context) -> AsyncIterator[bytes]:
    """Each step as it opens and again each time it changes (the same index), until the run
    ends: a step reaches the page as soon as the event that caused it is written."""
    stepper = steps_mod.Stepper(ctx)
    async for item in _lines(request, path):
        if item is None:
            yield KEEPALIVE
            continue
        for step in stepper.feed(item):
            yield f"event: step\ndata: {step.model_dump_json()}\n\n".encode()
        if item.get("type") == "run.end":
            yield END


def serve(
    project: Project,
    *,
    port: int = 7420,
    open_browser: bool = True,
    say: Callable[[str], None] = print,
    token: str | None = None,
) -> None:
    """Run the portal until interrupted."""
    token = token or secrets.token_urlsafe(24)
    app = create_app(project, token, port)
    address = f"http://{HOST}:{port}/?token={token}"
    config = uvicorn.Config(app, host=HOST, port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    say(f"Portal for {project.root.name} at {address}")
    say("Only this computer can reach it. Ctrl-C stops it.")
    if open_browser:
        webbrowser.open(address)
    marker = project.state_dir / sandbox_svc.PORTAL_FILE
    write_text(marker, json.dumps({"port": port, "pid": os.getpid()}) + "\n", owner_only=True)
    try:
        server.run()
    except OSError as exc:
        raise MirrorError(
            f"The portal could not listen on {HOST}:{port}.",
            str(exc),
            "Another program may use that port. Try: mirror portal --port <another>",
        ) from exc
    finally:
        current: PortalState = app.state.portal
        (current.project.state_dir / sandbox_svc.PORTAL_FILE).unlink(missing_ok=True)
