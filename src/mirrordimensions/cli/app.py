# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Commands available in M0: init, validate, schema, status.

Exit codes: 0 success, 1 a failed check, 2 a usage or configuration error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any, cast

import typer

from mirrordimensions import __version__, service
from mirrordimensions.cli.output import Output
from mirrordimensions.config import SCHEMAS
from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.console import use_utf8_streams
from mirrordimensions.project import Project

app = typer.Typer(
    name="mirror",
    help="MirrorDimensions: a sealed test range for AI agents.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)


class State:
    def __init__(self, out: Output, project: Path | None) -> None:
        self.out = out
        self.project = project

    def start(self) -> Path:
        return self.project or Path.cwd()


def _state(ctx: typer.Context) -> State:
    obj = ctx.obj
    if not isinstance(obj, State):  # only if a command is invoked without the root callback
        raise RuntimeError("command invoked without the mirror root callback")
    return obj


def _version(value: bool) -> None:
    if value:
        print(f"mirror {__version__}")
        raise typer.Exit()


@app.callback()
def root(
    ctx: typer.Context,
    project: Annotated[
        Path | None,
        typer.Option("--project", help="Project folder (default: search upward from here)."),
    ] = None,
    json_mode: Annotated[
        bool, typer.Option("--json", help="Print one JSON document on stdout.")
    ] = False,
    no_color: Annotated[bool, typer.Option("--no-color", help="Never use color.")] = False,
    quiet: Annotated[
        bool, typer.Option("--quiet", help="Print only errors and the final line.")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Show underlying calls.")] = False,
    version: Annotated[
        bool, typer.Option("--version", callback=_version, is_eager=True, help="Print the version.")
    ] = False,
) -> None:
    ctx.obj = State(
        Output.create(json_mode=json_mode, no_color=no_color, quiet=quiet, verbose=verbose), project
    )


@app.command()
def init(
    ctx: typer.Context,
    directory: Annotated[Path, typer.Argument(help="Folder to create the project in.")] = Path(),
    seed: Annotated[
        int | None, typer.Option(help="Seed for the company (default: random).")
    ] = None,
    industry: Annotated[
        str | None, typer.Option(help="Industry, e.g. logistics or finance.")
    ] = None,
) -> None:
    """Create a project: a starter mirror.yaml with a generated company, and its root CA."""
    st = _state(ctx)
    result = service.init_project(directory, seed=seed, industry=industry)
    if st.out.json_mode:
        st.out.document(result)
        return
    shown = directory.as_posix().rstrip("/") or "."
    st.out.line(f"Created {shown}/")
    st.out.line(f"  {'mirror.yaml':<16} environment manifest")
    st.out.line(f"  {'agents/':<16} agent files")
    st.out.line(f"  {'.mirror/ca/':<16} root certificate (never commit)")
    c = result.company
    st.out.line(f"{'Company':<10}{c.name} · {c.domain} · seed {result.seed}")
    st.out.next_step(f"{'Next':<10}edit mirror.yaml, then: mirror validate")


@app.command()
def validate(ctx: typer.Context) -> None:
    """Check the manifest, agent files and scenarios; report every problem with file and line."""
    st = _state(ctx)
    project = service.load_project(st.start())
    problems = service.validate(project)
    if st.out.json_mode:
        st.out.document([p.model_dump() for p in problems])
    else:
        for problem in problems:
            st.out.fail(problem.render())
        if not problems:
            st.out.ok("mirror.yaml, agents and scenarios are valid")
            st.out.next_step("Next: mirror status")
    if problems:
        raise typer.Exit(1)


@app.command()
def schema(
    ctx: typer.Context,
    kind: Annotated[
        str | None, typer.Argument(help=f"One of: {', '.join(SCHEMAS)}. Omit for all.")
    ] = None,
) -> None:
    """Print JSON Schema for the file formats."""
    print(json.dumps(service.json_schema(kind), indent=2))


@app.command()
def status(ctx: typer.Context) -> None:
    """Project state, host platform and loaded plug-ins."""
    st = _state(ctx)
    result = service.status(st.start())
    if st.out.json_mode:
        st.out.document(result)
        return
    h = result.host
    if result.project is None:
        st.out.line("No project here.")
    else:
        st.out.line(f"{'Project':<10}{result.name or '?'} at {result.project}")
        validity = (
            "valid" if result.valid else f"{result.problems} problem(s); run: mirror validate"
        )
        st.out.line(f"{'State':<10}{result.state} · {validity}")
    st.out.line(f"{'Host':<10}{h.os} {h.os_version} · {h.arch} · Python {h.python}")
    if result.plugins:
        st.out.line("Plug-ins")
        for p in result.plugins:
            origin = f"{p.distribution} {p.version}" if p.distribution else "unknown package"
            st.out.line(f"  {p.group:<14}{p.name:<16}{origin}")
    else:
        st.out.line(f"{'Plug-ins':<10}none")
    if result.project is None:
        st.out.next_step("Next: mirror init <dir>")


@app.command()
def up(ctx: typer.Context) -> None:
    """Start the sealed network for this project (M1: stub servers stand in for twins)."""
    from mirrordimensions.service import sandbox as svc

    st = _state(ctx)
    project = service.load_project(st.start())
    names = svc.up(project, on_step=st.out.ok)
    if st.out.json_mode:
        st.out.document({"containers": names})
        return
    st.out.ok(f"sandbox up: {', '.join(names)}")
    st.out.next_step("Next: mirror doctor")


@app.command()
def down(ctx: typer.Context) -> None:
    """Stop and remove the sealed network for this project."""
    from mirrordimensions.service import sandbox as svc

    st = _state(ctx)
    svc.down(service.load_project(st.start()))
    st.out.ok("sandbox down")


@app.command()
def doctor(ctx: typer.Context) -> None:
    """Run the egress, separation, inside-out, naming, transparency and capture checks."""
    from mirrordimensions.service import sandbox as svc

    st = _state(ctx)
    report = svc.doctor(service.load_project(st.start()))
    if st.out.json_mode:
        st.out.document(report)
    else:
        suite = ""
        for c in report.checks:
            if c.suite != suite:
                suite = c.suite
                st.out.line(suite.capitalize())
            timing = f" [{c.latency_s:.2f}s]" if c.latency_s is not None else ""
            text = f"{c.name}{timing}" + (f"  ({c.detail})" if c.detail else "")
            if c.outcome == "fail":
                st.out.fail(text)
            elif c.outcome == "n/a":
                st.out.line(f"{'n/a':<6}{text}")
            else:
                st.out.ok(text)
        st.out.line(f"Isolation: {report.isolation} ({report.boundary})")
    if report.isolation == "failed":
        raise typer.Exit(1)


@app.command()
def build(
    ctx: typer.Context,
    force: Annotated[bool, typer.Option("--force", help="Rebuild from scratch.")] = False,
) -> None:
    """Generate the world, seed every twin, and save and verify the base snapshot."""
    from mirrordimensions.service import world as world_svc

    st = _state(ctx)
    result = world_svc.build(service.load_project(st.start()), force=force, on_step=st.out.ok)
    if st.out.json_mode:
        st.out.document(result)
        return
    st.out.next_step("Built. Reset it at any time with: mirror reset")


@app.command()
def reset(
    ctx: typer.Context,
    snapshot: Annotated[str, typer.Argument(help="Snapshot to restore.")] = "base",
) -> None:
    """Restore a snapshot, and prove the state matches the moment it was saved."""
    from mirrordimensions.service import world as world_svc

    st = _state(ctx)
    result = world_svc.reset(service.load_project(st.start()), snapshot, on_step=st.out.ok)
    if st.out.json_mode:
        st.out.document(result)
    elif result.identical:
        st.out.ok("State matches the snapshot exactly")
    else:
        st.out.fail("State differs from the snapshot: " + ", ".join(result.differences[:5]))
    if not result.identical:
        raise typer.Exit(1)


snapshot_app = typer.Typer(help="Named snapshots of the world.", no_args_is_help=True)
app.add_typer(snapshot_app, name="snapshot")


@snapshot_app.command("save")
def snapshot_save(ctx: typer.Context, name: Annotated[str, typer.Argument()]) -> None:
    """Save the current state of every twin as a named snapshot."""
    from mirrordimensions.service import world as world_svc

    st = _state(ctx)
    info = world_svc.save_snapshot(service.load_project(st.start()), name)
    st.out.ok(f'Snapshot "{info.name}" saved ({info.seconds}s)')


@snapshot_app.command("list")
def snapshot_list(ctx: typer.Context) -> None:
    """Snapshots of this world."""
    import json as _json

    st = _state(ctx)
    project = service.load_project(st.start())
    path = project.state_dir / "snapshots" / "index.json"
    data: dict[str, dict[str, Any]] = (
        _json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    )
    if st.out.json_mode:
        st.out.document(data)
        return
    for name, info in sorted(data.items()):
        st.out.line(f"  {name:<12}{info['created']}  {len(info['volumes'])} volumes")
    if not data:
        st.out.line("No snapshots. Run: mirror build")


catalog_app = typer.Typer(help="The app catalog.", no_args_is_help=True)
app.add_typer(catalog_app, name="catalog")


@catalog_app.command("search")
def catalog_search(ctx: typer.Context, text: Annotated[str, typer.Argument()]) -> None:
    """Find apps by name, alias or kind."""
    from mirrordimensions.catalog import index

    st = _state(ctx)
    hits = index.search(text)
    if st.out.json_mode:
        st.out.document([h.model_dump() for h in hits])
        return
    for h in hits:
        st.out.line(f"  {h.slug:<28}{h.name:<32}{h.kind:<16}tier {h.tier}  {h.twin_status}")
    if not hits:
        st.out.line(f"No app matches {text!r}.")


@catalog_app.command("show")
def catalog_show(ctx: typer.Context, slug: Annotated[str, typer.Argument()]) -> None:
    """One catalog entry."""
    from mirrordimensions.catalog import index

    st = _state(ctx)
    entry = index.resolve(slug)
    if entry is None:
        raise MirrorError(
            f"No catalog entry for {slug!r}.",
            "Names match slugs and aliases.",
            "Run: mirror catalog search <text>",
        )
    st.out.document(entry) if st.out.json_mode else st.out.line(entry.model_dump_json(indent=2))


@catalog_app.command("list")
def catalog_list(
    ctx: typer.Context,
    category: Annotated[str | None, typer.Option(help="Filter by category.")] = None,
    tier: Annotated[int | None, typer.Option(help="Filter by tier.")] = None,
    status: Annotated[
        str | None, typer.Option(help="candidate, specified, buildable or verified.")
    ] = None,
) -> None:
    """List catalog entries."""
    from mirrordimensions.catalog import index

    st = _state(ctx)
    entries = [
        e
        for e in index.load()
        if (category is None or e.category == category)
        and (tier is None or e.tier == tier)
        and (status is None or e.twin_status == status)
    ]
    if st.out.json_mode:
        st.out.document([e.model_dump() for e in entries])
        return
    for e in entries:
        st.out.line(f"  {e.slug:<28}{e.name:<32}{e.category:<40}{e.twin_status}")


@catalog_app.command("stats")
def catalog_stats(ctx: typer.Context) -> None:
    """Counts by status and tier."""
    from mirrordimensions.catalog import index

    st = _state(ctx)
    data = index.stats()
    st.out.document(data) if st.out.json_mode else st.out.line(
        f"{data['entries']} entries in {data['categories']} categories · by status {data['by_status']} · by tier {data['by_tier']}"
    )


world_app = typer.Typer(help="Define and create a world.", no_args_is_help=True)
app.add_typer(world_app, name="world")


@world_app.command("new")
def world_new(
    ctx: typer.Context,
    directory: Annotated[Path, typer.Argument()] = Path(),
    template: Annotated[str | None, typer.Option(help="software-team")] = None,
    systems: Annotated[
        str | None, typer.Option(help="Comma-separated system names, matched against the catalog.")
    ] = None,
    people: Annotated[int, typer.Option(help="Number of people.")] = 25,
    history: Annotated[int, typer.Option(help="Days of history.")] = 180,
    seed: Annotated[int | None, typer.Option(help="Seed (default: random).")] = None,
) -> None:
    """Define a world from a template or from named systems."""
    from mirrordimensions.service import worlddef

    st = _state(ctx)
    names = [n.strip() for n in systems.split(",")] if systems else None
    if template is None and names is None and sys.stdin.isatty() and not st.out.json_mode:
        root = _world_new_interactive(st, directory)
    else:
        root = worlddef.new_world(directory, template, names, people, history, seed)
    shown = worlddef.show_world(Project(root=root))
    st.out.ok(f"World defined in {root}")
    st.out.line(f"{'Company':<10}{shown['company']}")
    for line in shown["systems"]:
        st.out.line(f"  {line}")
    st.out.next_step("Next: mirror world create")


def _world_new_interactive(st: State, directory: Path) -> Path:
    """Ask each question in turn; every answer is saved, so an interrupted session resumes."""
    from mirrordimensions.service import worlddef
    from mirrordimensions.world.names import suggest_company

    draft = worlddef.load_draft(directory)
    if draft.company is not None or draft.template or draft.systems:
        st.out.line("Continuing the draft from where it was left.")
    while (question := worlddef.next_question(draft)) is not None:
        if question == "company":
            offer = suggest_company(draft.seed, attempt=draft.attempt)
            answer = typer.prompt(
                f"Company: {offer.name} ({offer.domain}, {offer.industry}). Use it? "
                "yes, another, or type a name",
                default="yes",
            ).strip()
            if answer.lower() in ("y", "yes"):
                draft.company = offer
            elif answer.lower() in ("a", "another", "n", "no"):
                draft.attempt += 1
            else:
                from mirrordimensions.world.names import CompanySuggestion, slug

                draft.company = CompanySuggestion(
                    name=answer, domain=f"{slug(answer)}.com", industry=offer.industry
                )
        elif question == "shape":
            names = ", ".join(t.name for t in worlddef.list_templates())
            answer = typer.prompt(
                f"Start from a template ({names}) or list systems, comma-separated",
                default="software-team",
            ).strip()
            if answer in worlddef.TEMPLATES:
                draft.template = answer
            else:
                draft.systems = [n.strip() for n in answer.split(",") if n.strip()]
        elif question == "people":
            draft.people = typer.prompt("How many people", default=25, type=int)
        else:
            draft.history = typer.prompt("Days of history", default=180, type=int)
        worlddef.save_draft(directory, draft)
    return worlddef.finish_draft(directory, draft)


@world_app.command("show")
def world_show(ctx: typer.Context) -> None:
    """The definition in plain terms."""
    from mirrordimensions.service import worlddef

    st = _state(ctx)
    shown = worlddef.show_world(service.load_project(st.start()))
    if st.out.json_mode:
        st.out.document(shown)
        return
    st.out.line(f"{'Company':<10}{shown['company']}")
    st.out.line("Systems")
    for line in shown["systems"]:
        st.out.line(f"  {line}")
    st.out.line(f"{'Links':<10}" + ("; ".join(shown["links"]) or "none"))
    st.out.line(
        f"{'Data':<10}" + (", ".join(f"{k} {v}" for k, v in shown["data"].items()) or "defaults")
    )


@world_app.command("status")
def world_status_cmd(ctx: typer.Context) -> None:
    """State, last finished stage, and whether the definition changed."""
    from mirrordimensions.service import worlddef

    st = _state(ctx)
    status = worlddef.world_status(service.load_project(st.start()))
    if st.out.json_mode:
        st.out.document(status)
        return
    st.out.line(f"{'State':<10}{status.state}")
    st.out.line(
        f"{'Stage':<10}{status.last_stage} of 8"
        + (f" ({status.stages[status.last_stage - 1]})" if status.last_stage else "")
    )
    if status.definition_changed:
        st.out.line("The definition changed since creation; run: mirror world create --resume")


@world_app.command("create")
def world_create(
    ctx: typer.Context,
    resume: Annotated[
        bool, typer.Option("--resume", help="Continue from the first unfinished stage.")
    ] = False,
    from_stage: Annotated[
        int | None, typer.Option("--from-stage", help="Start at this stage (1 to 8).")
    ] = None,
) -> None:
    """Create the world in eight stages, one line per stage."""
    from mirrordimensions.service import world as world_svc

    st = _state(ctx)
    world_svc.create_world(
        service.load_project(st.start()), resume=resume, from_stage=from_stage, on_stage=st.out.ok
    )
    st.out.next_step("Ready. Agents can be onboarded into this world.")


@world_app.command("clone")
def world_clone(
    ctx: typer.Context,
    src: Annotated[Path, typer.Argument()],
    dst: Annotated[Path, typer.Argument()],
    new_seed: Annotated[
        bool, typer.Option("--new-seed", help="Same shape, a different company.")
    ] = False,
) -> None:
    """Copy a definition, optionally with a new seed."""
    from mirrordimensions.service import worlddef

    root = worlddef.clone_world(src, dst, new_seed)
    _state(ctx).out.ok(f"Cloned into {root}")


@world_app.command("destroy")
def world_destroy(
    ctx: typer.Context,
    yes: Annotated[bool, typer.Option("--yes", help="Do not ask for confirmation.")] = False,
) -> None:
    """Remove containers, volumes and generated files; keep mirror.yaml."""
    import shutil as _shutil

    from mirrordimensions.service import sandbox as sandbox_svc

    st = _state(ctx)
    project = service.load_project(st.start())
    if not yes and not typer.confirm(
        "Remove this world's containers, volumes and generated files?"
    ):
        raise typer.Exit(1)
    sandbox_svc.down(project, purge=True)
    for name in ("world.json", "create.json", "build.json", "snapshots", "sandbox"):
        target = project.state_dir / name
        if target.is_dir():
            _shutil.rmtree(target)
        else:
            target.unlink(missing_ok=True)
    st.out.ok("World destroyed; mirror.yaml, agents and the root CA are kept")


agent_app = typer.Typer(
    help="Agents under test: register, inspect and check them.", no_args_is_help=True
)
app.add_typer(agent_app, name="agent")


@agent_app.command("add")
def agent_add(ctx: typer.Context, file: Annotated[Path, typer.Argument()]) -> None:
    """Register an agent file with the project and validate it against the world."""
    from mirrordimensions.service import agents as agents_svc

    st = _state(ctx)
    added = agents_svc.add_agent(service.load_project(st.start()), file)
    st.out.ok(f"Agent {added.name} added ({added.mode})")
    st.out.next_step(f"Next: mirror agent check {added.name}")


def _parse_grants(values: list[str]) -> dict[str, Any]:
    """`--grant code.repos.billing-service=write`, `--grant chat.channels=a,b`, `--grant tools`."""
    grants: dict[str, Any] = {}
    for value in values:
        key, _, setting = value.partition("=")
        app_id, _, rest = key.partition(".")
        grant = grants.setdefault(app_id, {})
        if not rest:
            continue
        field, _, item = rest.partition(".")
        if item:
            grant.setdefault(field, {})[item] = setting
        else:
            grant[field] = [x.strip() for x in setting.split(",") if x.strip()]
    return grants


@agent_app.command("new")
def agent_new(
    ctx: typer.Context,
    name: Annotated[str | None, typer.Argument(help="The agent's name.")] = None,
    file: Annotated[
        Path | None, typer.Option("--file", help="A complete agent file: register and check it.")
    ] = None,
    resume: Annotated[str | None, typer.Option(help="Resume the draft with this name.")] = None,
    mode: Annotated[str | None, typer.Option(help="hosted or browser (remote: M7.5).")] = None,
    image: Annotated[str | None, typer.Option(help="The agent's container image.")] = None,
    build: Annotated[
        Path | None, typer.Option(help="Folder with a Dockerfile that builds the image.")
    ] = None,
    model: Annotated[
        str | None, typer.Option(help="Where its model runs: cloud, self-hosted or none.")
    ] = None,
    provider: Annotated[str | None, typer.Option(help="Cloud provider: anthropic, openai.")] = None,
    model_host: Annotated[str | None, typer.Option(help="The model's host name.")] = None,
    upstream: Annotated[
        str | None, typer.Option(help="Self-hosted: the one address:port it may reach.")
    ] = None,
    credential_env: Annotated[
        str | None, typer.Option(help="Host variable holding the real model credential.")
    ] = None,
    hosted_tools: Annotated[str, typer.Option(help="block, flag or allow.")] = "block",
    role: Annotated[str | None, typer.Option(help="The role it acts in.")] = None,
    person: Annotated[str | None, typer.Option(help="A specific person instead of a role.")] = None,
    grant: Annotated[
        list[str] | None,
        typer.Option(help="Access, repeatable: code.repos.NAME=write, chat.channels=a,b, tools."),
    ] = None,
    wake: Annotated[str | None, typer.Option(help="command or poll.")] = None,
    command: Annotated[str | None, typer.Option(help="The command run when work arrives.")] = None,
    no_check: Annotated[bool, typer.Option("--no-check", help="Skip the preflight.")] = False,
) -> None:
    """Onboard an agent in six steps, by prompts or by flags; a draft resumes where it stopped."""
    import shlex

    from mirrordimensions.service import onboard

    st = _state(ctx)
    project = service.load_project(st.start())
    if file is not None:
        added = onboard.complete_file(project, file)
        st.out.ok(f"Wrote agents/{added.name}.yaml")
        if not no_check:
            agent_check(ctx, added.name, False)
        return
    interactive = sys.stdin.isatty() and not st.out.json_mode
    name = name or resume
    if name is None:
        if not interactive:
            raise MirrorError("The agent needs a name.", "", "Pass it: mirror agent new <name>")
        name = str(typer.prompt("? Name")).strip()
    agent_name: str = name
    draft = onboard.draft_agent(project, agent_name)
    if draft.step > 1 and not draft.done:
        st.out.line(f"Continuing {name} from step {draft.step} of 6.")

    def ask(label: str, given: str | None, default: str | None = None) -> str | None:
        if given is not None:
            return given
        if interactive:
            answer = typer.prompt(f"? {label}", default=default or "", show_default=bool(default))
            return answer.strip() or None
        return default

    while not draft.done and draft.step <= 5:
        step = draft.step
        fields: dict[str, Any] = {}
        if step == 1:
            fields["mode"] = ask("How does it connect (hosted, browser, remote)", mode, "hosted")
            fields["image"] = ask("Container image", image)
            built = ask("Build it from a folder (blank for none)", str(build) if build else None)
            if built:
                fields["build"] = built
        elif step == 2:
            where = ask(
                "Where does its model run (cloud, self-hosted, in-sandbox, none)", model, "none"
            )
            if where in (None, "none"):
                fields["model"] = "none"
            else:
                chosen_provider = provider
                if where == "cloud":
                    chosen_provider = ask("Provider (anthropic, openai)", provider, "anthropic")
                host = ask("Model host (blank for the provider's own)", model_host)
                up = ask("Upstream address:port", upstream) if where == "self-hosted" else None
                env_name = ask(
                    "Credential (host variable, blank for the provider's usual)", credential_env
                )
                tools_rule = ask(
                    "Provider-hosted tools (block, flag, allow)", hosted_tools, "block"
                )
                fields["model"] = onboard.add_model_route(
                    project,
                    where,
                    provider=chosen_provider,
                    host=host,
                    upstream=up,
                    credential_env=env_name,
                    hosted_tools=tools_rule or "block",
                )
        elif step == 3:
            if person:
                fields["acts_as"] = {"person": person}
            else:
                chosen = ask("Acts as (role)", role, "engineer") or "engineer"
                fields["acts_as"] = {"role": chosen}
            who = onboard.person_for(project, **fields["acts_as"])
            st.out.line(
                f"      {fields['acts_as'].get('role') or 'person'} -> {who.name}, {who.title}"
            )
        elif step == 4:
            acts = cast(dict[str, str], draft.fields.get("acts_as") or {})
            if grant:
                fields["grants"] = _parse_grants(grant)
            else:
                defaults = onboard.role_defaults(
                    project, acts.get("role") or "", acts.get("person")
                )
                for line in onboard.describe_grants(defaults) or ["nothing"]:
                    st.out.line(f"      role default: {line}")
                edits: list[str] = []
                while interactive:
                    answer = typer.prompt(
                        "? Access: keep it, or add an edit (code.repos.NAME=read, chat.channels=a,b, tools)",
                        default="keep",
                    ).strip()
                    if answer in ("keep", "yes", "y", ""):
                        break
                    edits.append(answer)
                merged = defaults
                for app_id, extra in _parse_grants(edits).items():
                    merged.setdefault(app_id, {}).update(extra)
                fields["grants"] = merged
        elif step == 5:
            if draft.fields.get("mode") == "browser":
                fields["wake"] = {"type": "poll"}
                st.out.line(
                    "      The agent watches its inbox in the browser, signing in as a person would."
                )
            else:
                how = ask("How it notices work (command, poll)", wake, "command")
                if how == "command":
                    run = ask("Command run when work arrives", command)
                    fields["wake"] = {
                        "type": "command",
                        "command": shlex.split(run) if run else None,
                    }
                else:
                    fields["wake"] = {"type": how}
        draft = onboard.update_draft(project, agent_name, step, fields)
        st.out.ok(f"Step {step} of 6: {onboard.STEPS[step - 1]}")
    st.out.ok(f"Wrote agents/{agent_name}.yaml")
    if no_check:
        st.out.next_step(f"Check it with: mirror agent check {agent_name}")
        return
    agent_check(ctx, agent_name, False)


@agent_app.command("list")
def agent_list(ctx: typer.Context) -> None:
    """The project's agents."""
    from mirrordimensions.config.loader import load_model as _load
    from mirrordimensions.service import agents as agents_svc

    st = _state(ctx)
    project = service.load_project(st.start())
    rows: list[dict[str, str]] = []
    for name, path in agents_svc.agent_files(project).items():
        agent, _ = _load(path, agents_svc.Agent)
        if agent is not None:
            who = str(agent.acts_as.person or agent.acts_as.role) if agent.acts_as else "nobody yet"
            state = f"draft, step {agent.step} of 6" if agent.status == "draft" else "defined"
            rows.append({"name": name, "mode": agent.mode, "acts_as": who, "state": state})
    if st.out.json_mode:
        st.out.document(rows)
        return
    for r in rows:
        st.out.line(f"  {r['name']:<20}{r['mode']:<9}{r['acts_as']:<16}{r['state']}")
    if not rows:
        st.out.line("No agents yet. Run: mirror agent add <file>")


@agent_app.command("rm")
def agent_rm(ctx: typer.Context, name: Annotated[str, typer.Argument()]) -> None:
    """Remove an agent file from the project."""
    from mirrordimensions.service import agents as agents_svc

    st = _state(ctx)
    agents_svc.remove_agent(service.load_project(st.start()), name)
    st.out.ok(f"Agent {name} removed")


@agent_app.command("creds")
def agent_creds(ctx: typer.Context, name: Annotated[str, typer.Argument()]) -> None:
    """The identity and credentials the agent would be issued, for debugging."""
    from mirrordimensions.service import agents as agents_svc

    st = _state(ctx)
    shown = agents_svc.creds(service.load_project(st.start()), name)
    if st.out.json_mode:
        st.out.document(shown)
        return
    st.out.line(f"{'Acts as':<10}{shown['person']}")
    for app_id, info in shown["systems"].items():
        st.out.line(
            f"  {app_id:<8}{info['username']:<20}token {info['token']}  variables {', '.join(info['env'])}"
        )


@agent_app.command("check")
def agent_check(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument()],
    allow_emulated: Annotated[
        bool,
        typer.Option(
            "--allow-emulated",
            help="Run an image built for another architecture, at reduced isolation.",
        ),
    ] = False,
) -> None:
    """Every preflight check; each failure names its fix."""
    from mirrordimensions.service import agents as agents_svc

    st = _state(ctx)
    checks = agents_svc.check_agent(service.load_project(st.start()), name, allow_emulated)
    if st.out.json_mode:
        st.out.document([c.model_dump() for c in checks])
    else:
        for c in checks:
            text = c.name + (f"  ({c.detail})" if c.detail else "")
            if c.outcome == "pass":
                st.out.ok(text)
            elif c.outcome == "fail":
                st.out.fail(text)
                st.out.line(f"      Fix: {c.fix}")
            else:
                st.out.line(f"n/a   {text}")
    if any(c.outcome == "fail" for c in checks):
        raise typer.Exit(1)
    if not st.out.json_mode:
        st.out.next_step(f"{name} is ready.")


system_app = typer.Typer(help="Systems: surfaces, settings, data and rules.", no_args_is_help=True)
app.add_typer(system_app, name="system")
set_app = typer.Typer(help="Edit mirror.yaml.", no_args_is_help=True)
app.add_typer(set_app, name="set")
unset_app = typer.Typer(help="Remove from mirror.yaml.", no_args_is_help=True)
app.add_typer(unset_app, name="unset")


@system_app.command("list")
def system_list(ctx: typer.Context) -> None:
    """Systems with product, hostname, and counts of surfaces and rules."""
    from mirrordimensions.service import systems

    st = _state(ctx)
    result = systems.list_systems(service.load_project(st.start()))
    if st.out.json_mode:
        st.out.document([r.model_dump() for r in result])
        return
    for r in result:
        product = r.product or r.kind or "?"
        kind = "" if r.twin else "  (no twin yet: a stand-in page)"
        st.out.line(
            f"  {r.id:<8}{product:<12}{r.hostname:<34}{r.visibility:<9}{r.surfaces:>3} surfaces"
            f"{r.rules:>3} rules{kind}"
        )


@system_app.command("show")
def system_show(
    ctx: typer.Context,
    app_id: Annotated[str, typer.Argument(help="The system's id in mirror.yaml.")],
    surfaces: Annotated[
        bool, typer.Option("--surfaces", help="List every portal and endpoint.")
    ] = False,
) -> None:
    """Settings, data shape, and each portal and endpoint with whether it is customized."""
    from mirrordimensions.service import systems

    st = _state(ctx)
    detail = systems.show_system(service.load_project(st.start()), app_id)
    if st.out.json_mode:
        st.out.document(detail)
        return
    s = detail.summary
    st.out.line(f"{s.id} · {s.product or s.kind} · {s.hostname} · {s.visibility}")
    st.out.line(
        f"{'Settings':<10}"
        + (", ".join(f"{k}={v}" for k, v in detail.settings.items()) or "defaults")
    )
    st.out.line(
        f"{'Data':<10}" + (", ".join(f"{k}={v}" for k, v in detail.data.items()) or "defaults")
    )
    st.out.line(f"{'Rules':<10}" + (", ".join(r["name"] for r in detail.rules) or "none"))
    if surfaces:
        for sf in detail.surfaces:
            custom = f"  [{', '.join(sf.customized_by)}]" if sf.customized_by else ""
            st.out.line(f"  {sf.kind:<9}{sf.method:<7}{sf.path:<58}{sf.sentence}{custom}")
    else:
        customized = sum(1 for sf in detail.surfaces if sf.customized_by)
        st.out.line(
            f"{'Surfaces':<10}{len(detail.surfaces)} ({customized} customized); "
            "list them with --surfaces"
        )


@system_app.command("rules")
def system_rules(ctx: typer.Context, app_id: Annotated[str, typer.Argument()]) -> None:
    """Active rules, in the order they apply."""
    from mirrordimensions.service import systems

    st = _state(ctx)
    rules = systems.list_rules(service.load_project(st.start()), app_id)
    if st.out.json_mode:
        st.out.document(rules)
        return
    for i, r in enumerate(rules, 1):
        st.out.line(
            f"  {i}. {r['name']}: match {r.get('match')}"
            + (f", input {r['input']}" if r.get("input") else "")
            + (f", output {r['output']}" if r.get("output") else "")
        )
    if not rules:
        st.out.line("No rules.")


@system_app.command("try")
def system_try(
    ctx: typer.Context,
    app_id: Annotated[str, typer.Argument()],
    method: Annotated[str, typer.Argument()],
    path: Annotated[str, typer.Argument()],
    body: Annotated[
        Path | None, typer.Option("--body", help="A file with the request body.")
    ] = None,
) -> None:
    """Dry run: the matching surface, the rules that fire, and the answer the agent would get."""
    from mirrordimensions.service import sandbox as sandbox_svc
    from mirrordimensions.service import systems

    st = _state(ctx)
    project = service.load_project(st.start())
    data = body.read_bytes() if body else b""
    try:
        fetch = sandbox_svc.admin_fetcher(project, app_id)
    except MirrorError:
        fetch = None
    result = systems.try_request(project, app_id, method, path, data, fetch)
    if st.out.json_mode:
        st.out.document(result)
        return
    st.out.line(
        f"{'Surface':<10}{result.surface}" + (f" · {result.resource}" if result.resource else "")
    )
    st.out.line(f"{'Sentence':<10}{result.sentence}")
    fired = (
        ", ".join(f"{r['rule']} ({', '.join(r['changed'])})" for r in result.rules_fired) or "none"
    )
    st.out.line(f"{'Rules':<10}{fired}")
    source = (
        "from a rule"
        if result.from_rule
        else "from the product (asked as its administrator until M4)"
    )
    st.out.line(f"{'Answer':<10}{result.status}, {source}")
    st.out.line(result.body[:1500])


@set_app.command("rule")
def set_rule_cmd(
    ctx: typer.Context,
    app_id: Annotated[str, typer.Argument()],
    file: Annotated[Path, typer.Option("--file", help="A YAML file with one rule.")],
) -> None:
    """Add or replace a rule in mirror.yaml. Takes effect on the next run; no rebuild."""
    from ruamel.yaml import YAML as _YAML

    from mirrordimensions.service import systems

    st = _state(ctx)
    rule = _YAML(typ="safe").load(file.read_text(encoding="utf-8"))  # pyright: ignore[reportUnknownMemberType]
    systems.set_rule(service.load_project(st.start()), app_id, rule)
    st.out.ok(f"rule {rule['name']} set on {app_id}; it applies from the next mirror up or run")


@unset_app.command("rule")
def unset_rule_cmd(
    ctx: typer.Context,
    app_id: Annotated[str, typer.Argument()],
    name: Annotated[str, typer.Argument()],
) -> None:
    """Remove a rule from mirror.yaml."""
    from mirrordimensions.service import systems

    st = _state(ctx)
    systems.remove_rule(service.load_project(st.start()), app_id, name)
    st.out.ok(f"rule {name} removed from {app_id}")


@app.command("run")
def run_command(
    ctx: typer.Context,
    scenario: Annotated[str, typer.Argument(help="A scenario id, or a suite: core.")],
    agent: Annotated[str, typer.Option("--agent", help="The agent to run.")],
    allow_emulated: Annotated[
        bool, typer.Option("--allow-emulated", help="Run an image built for another architecture.")
    ] = False,
    max_minutes: Annotated[
        int | None, typer.Option(help="Stop the agent after this many minutes.")
    ] = None,
) -> None:
    """Run scenarios with an agent: restore, deliver, watch, score. Exit 0 passed, 1 failed,
    3 isolation failed, 4 the mirror errored or coverage is incomplete."""
    from mirrordimensions.service import runs as runs_svc

    st = _state(ctx)
    project = service.load_project(st.start())
    outcomes = runs_svc.run(
        project,
        scenario,
        agent,
        allow_emulated=allow_emulated,
        max_minutes=max_minutes,
        on_step=None if st.out.json_mode else (lambda text: st.out.line(f"      {text}")),
    )
    if st.out.json_mode:
        st.out.document([o.model_dump() for o in outcomes])
    else:
        for o in outcomes:
            text = f"{o.scenario:<26}{o.status:<9}{o.run_id}"
            if o.status == "passed":
                st.out.ok(text)
            else:
                st.out.fail(text)
        st.out.next_step("Details: .mirror/runs/<run-id>/result.json")
    code = runs_svc.exit_code(outcomes)
    if code:
        raise typer.Exit(code)


@app.command("runs")
def runs_command(ctx: typer.Context) -> None:
    """Past runs, oldest first."""
    from mirrordimensions.service import runs as runs_svc

    st = _state(ctx)
    rows = runs_svc.list_runs(service.load_project(st.start()))
    if st.out.json_mode:
        st.out.document(rows)
        return
    for r in rows:
        st.out.line(f"  {r['run_id']:<14}{r['scenario']:<26}{r['agent']:<16}{r['status']}")
    if not rows:
        st.out.line("No runs yet. Run: mirror run <scenario> --agent <name>")


engine_app = typer.Typer(help="The engine: the Linux VM every world runs in.", no_args_is_help=True)
app.add_typer(engine_app, name="engine")


@engine_app.command("setup")
def engine_setup(
    ctx: typer.Context,
    cpus: Annotated[int | None, typer.Option(help="CPUs for the engine VM.")] = None,
    memory: Annotated[int | None, typer.Option(help="Memory in GB.")] = None,
    disk: Annotated[int | None, typer.Option(help="Disk in GB.")] = None,
    driver: Annotated[str | None, typer.Option(help="lima, wsl or host (Linux only).")] = None,
    experimental: Annotated[
        bool, typer.Option(help="Allow the experimental Windows driver.")
    ] = False,
    microvm: Annotated[
        bool,
        typer.Option(
            help="Also install the Firecracker microVM runtime (Apple M3+ or nested KVM)."
        ),
    ] = False,
) -> None:
    """Create or update the engine. Safe to run again."""
    from mirrordimensions.engine.base import Resources
    from mirrordimensions.engine.lima import default_resources
    from mirrordimensions.service import engine as svc

    st = _state(ctx)
    base = default_resources()
    resources = Resources(
        cpus=cpus or base.cpus, memory_gb=memory or base.memory_gb, disk_gb=disk or base.disk_gb
    )
    if driver not in (None, "lima", "wsl", "host"):
        raise MirrorError(
            f"Unknown driver {driver!r}.", "Drivers: lima, wsl, host.", "Omit --driver."
        )
    status = svc.setup_engine(  # type: ignore[arg-type]
        resources, driver, on_step=st.out.line, experimental=experimental, microvm=microvm
    )
    _show_engine(st, status)
    if not st.out.json_mode:
        st.out.next_step("Next: mirror engine check")


@engine_app.command("status")
def engine_status_cmd(ctx: typer.Context) -> None:
    """Driver, state, architecture, boundary, versions, resources and clock offset."""
    from mirrordimensions.service import engine as svc

    _show_engine(_state(ctx), svc.engine_status())


@engine_app.command("start")
def engine_start(ctx: typer.Context) -> None:
    """Start the engine."""
    from mirrordimensions.service import engine as svc

    st = _state(ctx)
    _show_engine(st, svc.start_engine(on_step=st.out.line))


@engine_app.command("stop")
def engine_stop(ctx: typer.Context) -> None:
    """Stop the engine."""
    from mirrordimensions.service import engine as svc

    svc.stop_engine()
    _state(ctx).out.ok("engine stopped")


@engine_app.command("destroy")
def engine_destroy(
    ctx: typer.Context,
    yes: Annotated[bool, typer.Option("--yes", help="Do not ask for confirmation.")] = False,
) -> None:
    """Remove the engine and every world's containers, volumes and snapshots."""
    from mirrordimensions.service import engine as svc

    st = _state(ctx)
    if not yes and not typer.confirm("Destroy the engine and everything in it?"):
        raise typer.Exit(1)
    svc.destroy_engine()
    st.out.ok("engine destroyed; world definitions on this machine are kept")


@engine_app.command("check")
def engine_check(ctx: typer.Context) -> None:
    """Prove the engine's guarantees: gVisor, Rosetta, private endpoint, no host access, egress."""
    from mirrordimensions.service import engine as svc

    st = _state(ctx)
    results = svc.check_engine()
    if st.out.json_mode:
        st.out.document([r.model_dump() for r in results])
    else:
        for r in results:
            line = f"{r.name}" + (f"  ({r.detail})" if r.detail else "")
            if r.outcome == "fail":
                st.out.fail(line)
            elif r.outcome == "skip":
                st.out.line(f"{'skip':<6}{line}")
            else:
                st.out.ok(line)
    if any(r.outcome == "fail" for r in results):
        raise typer.Exit(1)


@engine_app.command(
    "shell", context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def engine_shell(ctx: typer.Context) -> None:
    """Open a shell in the engine, for debugging the mirror itself."""
    import os

    from mirrordimensions.engine.lima import INSTANCE, LimaEngine
    from mirrordimensions.engine.registry import get_engine

    engine = get_engine()
    if not isinstance(engine, LimaEngine):
        raise MirrorError(
            "engine shell needs the lima driver.",
            f"This engine uses {engine.name}.",
            "Use the driver's own tools.",
        )
    env = {**os.environ, "LIMA_HOME": str(engine.lima_home)}
    os.execve(str(engine.limactl), [str(engine.limactl), "shell", INSTANCE, *ctx.args], env)  # noqa: S606


def _show_engine(st: State, status: object) -> None:
    from mirrordimensions.engine.base import EngineStatus

    assert isinstance(status, EngineStatus)  # noqa: S101
    if st.out.json_mode:
        st.out.document(status)
        return
    s = status
    st.out.line(
        f"{'Engine':<10}{s.driver} · {s.state}"
        + (f" · {s.arch}" if s.arch else "")
        + (f" · {s.boundary}" if s.boundary else "")
    )
    if s.resources:
        r = s.resources
        st.out.line(f"{'Size':<10}{r.cpus} CPUs · {r.memory_gb} GB memory · {r.disk_gb} GB disk")
    if s.versions:
        st.out.line(
            f"{'Versions':<10}" + " · ".join(f"{k} {v}" for k, v in sorted(s.versions.items()))
        )
    if s.clock_offset_s is not None:
        st.out.line(f"{'Clock':<10}{s.clock_offset_s:+.3f} s from the host")


def main() -> None:
    use_utf8_streams()
    try:
        app()
    except MirrorError as exc:
        Output().error(exc.what, exc.why, exc.fix)
        raise SystemExit(exc.exit_code) from None
    except KeyboardInterrupt:
        raise SystemExit(130) from None
