# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Commands available in M0: init, validate, schema, status.

Exit codes: 0 success, 1 a failed check, 2 a usage or configuration error.
"""

from __future__ import annotations

import json
import sys
import textwrap
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
    """Start the sealed network for this project: the resolver, the gateway and every system
    (a stand-in page for systems without a twin)."""
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
def doctor(
    ctx: typer.Context,
    latency_budget_ms: Annotated[
        float,
        typer.Option(
            "--latency-budget-ms",
            min=1.0,
            help="The most the gateway may add to a request (median), in milliseconds. "
            "The default, 10, is the limit on a workstation; raise it only for a slower "
            "machine such as a nested CI virtual machine. The result names the limit used.",
        ),
    ] = 10.0,
) -> None:
    """Run the egress, separation, inside-out, naming, transparency and capture checks."""
    from mirrordimensions.service import sandbox as svc

    st = _state(ctx)
    report = svc.doctor(service.load_project(st.start()), latency_budget_ms)
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
        from mirrordimensions.network.egress_check import (
            COVERAGE_SUITES,
            ISOLATION_SUITES,
            UNDETECTABILITY_SUITES,
        )

        def why(suites: frozenset[str]) -> str:
            failed = report.failed_in(suites)
            first = failed[0].name
            return f": {first[0].lower()}{first[1:]}" + (
                f", and {len(failed) - 1} more" if len(failed) > 1 else ""
            )

        st.out.line(
            f"Isolation: {report.isolation} ({report.boundary})"
            + (why(ISOLATION_SUITES) if report.isolation == "failed" else "")
        )
        st.out.line(
            f"Coverage: {report.coverage}"
            + (why(COVERAGE_SUITES) if report.coverage != "complete" else "")
        )
        st.out.line(
            f"Undetectability: {report.undetectability}"
            + (why(UNDETECTABILITY_SUITES) if report.undetectability != "full" else "")
        )
        if report.isolation != "failed" and not report.all_held:
            st.out.line(f"{'note':<6}Nothing leaves the sandbox; what failed is named above.")
        if any(c.suite == "transparency" and "Latency" in c.name for c in report.failed):
            st.out.line(
                f"{'note':<6}The gateway's added latency is a timing measure: a busy computer "
                "(builds, other VMs) raises it. Run mirror doctor again when it is quieter."
            )
        for note in report.notes:
            st.out.line(f"{'note':<6}{note}")
    if not report.all_held:
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
    add_systems: Annotated[
        str | None,
        typer.Option(
            "--add-systems",
            help="Systems to add to the template, the --systems list or the industry's proposal.",
        ),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes", help="With --industry: use the systems its profile proposes, without asking."
        ),
    ] = False,
    people: Annotated[int, typer.Option(help="Number of people.")] = 25,
    history: Annotated[int, typer.Option(help="Days of history.")] = 180,
    seed: Annotated[int | None, typer.Option(help="Seed (default: random).")] = None,
    company: Annotated[
        str | None, typer.Option(help="The company's name (default: suggested from the seed).")
    ] = None,
    domain: Annotated[str | None, typer.Option(help="Its domain, for hostnames and email.")] = None,
    industry: Annotated[str | None, typer.Option(help="Its industry.")] = None,
    tidiness: Annotated[
        str, typer.Option(help="How tidy its data is: tidy, realistic or messy.")
    ] = "realistic",
    repositories: Annotated[int, typer.Option(help="Repositories.")] = 6,
    issues: Annotated[int, typer.Option(help="Issues.")] = 150,
    messages: Annotated[int, typer.Option(help="Chat messages.")] = 2000,
    canaries: Annotated[int, typer.Option(help="Planted secrets, to trace leaks.")] = 3,
    announce: Annotated[
        bool, typer.Option("--announce/--no-announce", help="New issues and merges posted in chat.")
    ] = True,
    incidents: Annotated[
        bool, typer.Option("--incidents/--no-incidents", help="Incidents in chat and as issues.")
    ] = True,
    substitute: Annotated[
        bool,
        typer.Option(
            "--substitute/--no-substitute",
            help="With --systems: run Gitea or Mattermost in place of a product of the same "
            "kind that has no twin yet (GitHub, Slack), at its hostname.",
        ),
    ] = True,
    import_: Annotated[
        list[Path] | None,
        typer.Option(
            "--import", help="Start from files describing the company (repeat for each file)."
        ),
    ] = None,
    as_: Annotated[
        str | None, typer.Option("--as", help="With --import: the kind of file, if not recognized.")
    ] = None,
    decide: Annotated[
        list[str] | None,
        typer.Option(
            help="With --import: settle a disagreement or change a decision, as subject=value."
        ),
    ] = None,
) -> None:
    """Define a world from a template, from named systems, or from imported files. The
    portal's world wizard asks the same things and writes the same mirror.yaml."""
    from mirrordimensions.service import worlddef
    from mirrordimensions.service import worlds as worlds_svc
    from mirrordimensions.world.names import CompanySuggestion, slug, suggest_company

    st = _state(ctx)
    names = [n.strip() for n in systems.split(",")] if systems else None
    if tidiness not in ("tidy", "realistic", "messy"):
        raise MirrorError(f"{tidiness!r} is not a tidiness.", "", "Use tidy, realistic or messy.")
    decisions: dict[str, str] = {}
    for item in decide or []:
        subject, sep, value = item.partition("=")
        if not sep or not subject or not value:
            raise MirrorError(
                f"{item!r} is not subject=value.",
                "",
                "Such as: --decide gitea.hostname=git.acme.com",
            )
        decisions[subject.strip()] = value.strip()
    offer: CompanySuggestion | None = None
    if company or domain or industry:
        base = suggest_company(seed or 0, industry)
        name = company or base.name
        offer = CompanySuggestion(
            name=name, domain=domain or f"{slug(name)}.com", industry=industry or base.industry
        )
    resuming = (
        template is None
        and names is None
        and worlddef.draft_path(directory).is_file()
        and worlddef.load_draft(directory).imported
    )
    if (decisions or as_) and not import_ and not resuming:
        raise MirrorError("--decide and --as go with --import.", "", "Add --import <file>.")
    if import_ is not None:
        if template or names:
            raise MirrorError(
                "Start from --import, --template or --systems, not more than one.", "", ""
            )
        root = worlds_svc.new_from_import(
            directory,
            import_,
            as_=as_,
            decisions=decisions,
            company=offer,
            seed=seed,
            people=people,
            history=history,
            tidiness=tidiness,  # pyright: ignore[reportArgumentType]
            data={
                "repositories": repositories,
                "issues": issues,
                "messages": messages,
                "canaries": canaries,
            },
            links={"announce": announce, "incidents": incidents},
        )
    elif resuming:  # a world started from an import, once its disagreements are settled
        root = worlds_svc.finish_from_import(directory, decisions)
    elif (
        template is None
        and names is None
        and offer is None
        and add_systems is None
        and _interactive()
        and not st.out.json_mode
    ):
        root = _world_new_interactive(st, directory)
    else:
        names = _systems_for(st, template, names, add_systems, industry, yes, substitute)
        root = worlddef.new_world(
            directory,
            template,
            names,
            people,
            history,
            seed,
            industry,
            company=offer,
            tidiness=tidiness,  # pyright: ignore[reportArgumentType]
            data={
                "repositories": repositories,
                "issues": issues,
                "messages": messages,
                "canaries": canaries,
            },
            links={"announce": announce, "incidents": incidents},
            substitute=substitute,
        )
    shown = worlddef.show_world(Project(root=root))
    st.out.ok(f"World defined in {root}")
    st.out.line(f"{'Company':<10}{shown['company']}")
    for line in shown["systems"]:
        st.out.line(f"  {line}")
    for note in shown["notes"]:
        st.out.note(note)
    st.out.next_step("Next: mirror world create")


def _interactive() -> bool:
    """Whether a person is at a terminal to answer. Both ends must be terminals: on Windows
    the NUL device counts as one, so input alone would wrongly say yes under a script."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def _systems_for(
    st: State,
    template: str | None,
    names: list[str] | None,
    add: str | None,
    industry: str | None,
    yes: bool,
    substitute: bool,
) -> list[str] | None:
    """The systems a world starts with: those named, else the industry's proposal once
    confirmed (decision 0028, point 3), else the template's; then any added."""
    from mirrordimensions.service import worlddef

    added = [n.strip() for n in add.split(",") if n.strip()] if add else []
    if names is None and template is None:
        proposal = worlddef.propose(industry, substitute)
        if proposal is not None:
            if not st.out.json_mode:
                st.out.line(f"A {proposal.profile} company usually runs:")
                for line in proposal.lines:
                    st.out.line(f"  {line}")
            if yes:
                names = proposal.systems
            elif _interactive() and not st.out.json_mode:
                answer = typer.prompt(
                    "Use these systems? yes, no for the template, or type your own list",
                    default="yes",
                ).strip()
                if answer.lower() in ("y", "yes"):
                    names = proposal.systems
                elif answer.lower() not in ("n", "no"):
                    names = [n.strip() for n in answer.split(",") if n.strip()]
            else:
                st.out.note(
                    "Using the template's systems. Add --yes to use these, or name your own "
                    "with --systems."
                )
    if added:
        base = names or worlddef.TEMPLATE_SYSTEMS.get(template or "software-team", [])
        names = [*base, *(a for a in added if a not in base)]
    return names


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


@world_app.command("add")
def world_add(
    ctx: typer.Context,
    systems: Annotated[list[str], typer.Argument(help="Systems to add, by catalog name.")],
    substitute: Annotated[
        bool,
        typer.Option(
            "--substitute/--no-substitute",
            help="Run Gitea or Mattermost in place of a product of the same kind with no twin.",
        ),
    ] = True,
) -> None:
    """Add systems to this world's mirror.yaml, keeping the rest of the file as it is. Run
    mirror world create afterwards to build them."""
    from mirrordimensions.service import worlddef

    st = _state(ctx)
    project = service.load_project(st.start())
    names = [n.strip() for item in systems for n in item.split(",") if n.strip()]
    added = worlddef.add_systems(project, names, substitute)
    shown = worlddef.show_world(project)
    if st.out.json_mode:
        st.out.document({"added": added, **shown})
        return
    st.out.ok(f"Added {', '.join(added)} to {project.manifest_path.name}")
    for line in shown["systems"]:
        st.out.line(f"  {line}")
    for note in shown["notes"]:
        st.out.note(note)
    st.out.next_step("Next: mirror world create, which builds what is new")


@world_app.command("expose")
def world_expose(
    ctx: typer.Context,
    app_id: Annotated[str, typer.Argument(help="The world MCP server to expose.")],
    hostname: Annotated[
        str, typer.Option("--hostname", help="The public name your reverse proxy serves.")
    ],
    agent: Annotated[str, typer.Option("--agent", help="The remote agent it is exposed for.")],
    port: Annotated[
        int, typer.Option("--port", min=1024, max=65535, help="The relay's port on 127.0.0.1.")
    ] = 7480,
) -> None:
    """Expose a world MCP server to a remote agent: bring up the ingress, issue the agent's
    sign-in, print the reverse-proxy settings, and relay connections until Ctrl-C."""
    from mirrordimensions.service import expose as svc

    st = _state(ctx)
    project = service.load_project(st.start())
    done = svc.expose(project, app_id, hostname, agent, port=port, on_step=st.out.line)
    if st.out.json_mode:
        st.out.document(done)
    else:
        st.out.ok(f"{app_id} is exposed for {agent}")
        st.out.line(f"{'Connector':<11}{done.public_url}")
        st.out.line(f"{'Sign in as':<11}{done.username}  (password: {done.password})")
        st.out.line(f"{'Relay':<11}{done.local}: point your reverse proxy here")
        st.out.line("")
        st.out.line("Caddy:")
        st.out.line(done.caddy)
        st.out.line("nginx (with your certificate's paths):")
        st.out.line(done.nginx)
        st.out.line(
            "Relaying. Ctrl-C stops it; nothing is reachable from outside while it is stopped."
        )
    svc.relay(project, port)


@world_app.command("unexpose")
def world_unexpose(
    ctx: typer.Context,
    app_id: Annotated[str, typer.Argument(help="The exposed MCP server.")],
) -> None:
    """Stop exposing a world MCP server. The ingress goes at the next sandbox restart."""
    from mirrordimensions.service import expose as svc

    st = _state(ctx)
    _show_change(st, svc.unexpose(service.load_project(st.start()), app_id))


IMPORT_ACTIONS = ("show", "decide", "apply", "discard", "provenance")


@world_app.command("import")
def world_import(
    ctx: typer.Context,
    items: Annotated[
        list[str],
        typer.Argument(
            help="Files to read; or show, decide <subject> <decision>, apply, discard, provenance."
        ),
    ],
    as_: Annotated[
        str | None,
        typer.Option("--as", help="The kind of file, when it is not recognized."),
    ] = None,
    conflicts: Annotated[
        bool, typer.Option("--conflicts", help="show: only the disagreements to settle.")
    ] = False,
) -> None:
    """Import a description of the company: read files into a draft, review it, apply it.

    mirror world import <file>...                read files (in place) into the draft
    mirror world import show [--conflicts]       what was understood, with sources
    mirror world import decide <subject> <value> settle a conflict or change a decision
    mirror world import apply                    write it into mirror.yaml
    mirror world import discard                  delete the draft
    """
    from mirrordimensions.service import imports as svc

    st = _state(ctx)
    project = service.load_project(st.start())
    action = items[0] if items and items[0] in IMPORT_ACTIONS else None
    if action == "decide":
        if len(items) != 3:
            raise MirrorError(
                "decide takes a subject and a decision.",
                "",
                "Run: mirror world import decide <subject> <decision>",
            )
        found = svc.decide(project, items[1], items[2])
        st.out.ok(f"{items[1]}: {items[2]}")
        _show_import(st, found, conflicts_only=False, brief=True)
        return
    if action == "apply":
        from mirrordimensions.service import worlds as worlds_svc

        changes = worlds_svc.apply_import(project)
        if st.out.json_mode:
            st.out.document([c.model_dump() for c in changes])
            return
        for change in changes:
            st.out.ok(change.what)
        st.out.line("Each entry is traced to its facts: mirror world import provenance")
        st.out.next_step("Build it: mirror world create")
        return
    if action == "discard":
        svc.discard_import(project)
        st.out.ok("Import draft deleted")
        return
    if action == "provenance":
        st.out.document(svc.provenance(project))
        return
    if action == "show":
        _show_import(st, svc.get_import(project), conflicts_only=conflicts, brief=False)
        return
    found = svc.import_sources(project, [Path(i) for i in items], as_)
    _show_import(st, found, conflicts_only=False, brief=True)


def _show_import(st: Any, found: Any, *, conflicts_only: bool, brief: bool) -> None:
    from mirrordimensions.service import imports as svc

    review = cast(svc.ImportReview, found)
    if st.out.json_mode:
        st.out.document(review)
        return
    out = st.out
    if not conflicts_only:
        for source in review.sources:
            skipped: list[str] = []
            if source.skipped_secrets:
                skipped.append(f"{source.skipped_secrets} secret value(s) skipped, none stored")
            if source.skipped_people:
                skipped.append(f"{source.skipped_people} person detail(s) not read")
            more = f"; {'; '.join(skipped)}" if skipped else ""
            out.ok(f"{source.label} ({source.file}): {source.summary}{more}")
        out.line(
            f"      {review.found} found · {review.buildable} can be built now · "
            f"{review.open_conflicts} disagreement(s) to settle · "
            f"{review.skipped_secrets} secret value(s) skipped"
        )
    for c in review.conflicts:
        if c.settled:
            if not conflicts_only:
                continue
            out.line(f"settled  {c.id}: {c.settled}")
            continue
        out.fail(f"{c.label}: the sources disagree on its {c.field}  ({c.id})")
        for choice in c.choices:
            out.line(f"      {choice.value:<40} {'; '.join(choice.sources)}")
        out.line(f"      Settle it: mirror world import decide {c.id} <value>")
    if conflicts_only:
        return
    if not brief:
        for f in review.findings:
            mark = " (proposed)" if f.proposed else ""
            out.line("")
            out.line(f"  {f.label}  [{f.kind_label}]  {f.id}")
            out.line(f"      {f.understood}")
            out.line(f"      from {'; '.join(f.sources)}")
            out.line(
                f"      decision: {svc.DECISION_TEXT.get(f.decision, f.decision)}{mark}"
                f"  (options: {', '.join(f.options)})"
            )
            for t in f.tools:
                if not t.mapped:
                    out.line(f"      unavailable tool {t.name}: {t.reason}")
        out.line("")
        out.line("What no file could tell us:")
        for gap in review.gaps:
            out.line(f"      {gap['what']}: {gap['why']}")
    else:
        for f in review.findings:
            out.line(
                f"      {f.label:<34} {f.kind_label:<18} "
                f"{svc.DECISION_TEXT.get(f.decision, f.decision)}"
            )
    if review.open_conflicts:
        out.next_step("Settle the disagreements, then: mirror world import apply")
    else:
        out.next_step("Review it: mirror world import show; then: mirror world import apply")


@world_app.command("show")
def world_show(
    ctx: typer.Context,
    part: Annotated[
        str | None,
        typer.Argument(help="people, projects or canaries: that part of the built company."),
    ] = None,
) -> None:
    """The definition in plain terms, or one part of the built company."""
    from mirrordimensions.service import worlddef

    st = _state(ctx)
    if part is not None:
        from mirrordimensions.service import company as company_svc

        if part not in ("people", "projects", "canaries"):
            raise MirrorError(
                f"{part!r} is not a part of the company.", "", "Use people, projects or canaries."
            )
        found = company_svc.company(service.load_project(st.start()), (part,))  # pyright: ignore[reportArgumentType]
        if st.out.json_mode:
            st.out.document(found)
            return
        if part == "people":
            for p in found.people:
                left = "  (left)" if p.left else ""
                st.out.line(f"  {p.username:<22}{p.name:<26}{p.title}, {p.department}{left}")
        elif part == "projects":
            for pr in found.projects:
                st.out.line(f"  {pr.name:<22}#{pr.channel:<20}{', '.join(pr.repositories)}")
        else:
            for c in found.canaries:
                st.out.line(f"  {c.id:<22}{c.kind:<10}{c.where}")
        return
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
    mode: Annotated[str | None, typer.Option(help="hosted, browser or remote.")] = None,
    accept_reduced_guarantees: Annotated[
        bool,
        typer.Option(
            "--accept-reduced-guarantees",
            help="Remote: accept that leaks are detected, not blocked, and that its model and platform are outside the record.",
        ),
    ] = False,
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
    interactive = _interactive() and not st.out.json_mode
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
        remote = draft.fields.get("mode") == "remote"
        if step == 1:
            fields["mode"] = ask("How does it connect (hosted, browser, remote)", mode, "hosted")
            if fields["mode"] == "remote":
                st.out.line("")
                for line in textwrap.wrap(onboard.REMOTE_NOTICE, 86):
                    st.out.line(f"      {line}")
                st.out.line("")
                accepted = accept_reduced_guarantees or (
                    interactive
                    and typer.confirm("? Accept these reduced guarantees", default=False)
                )
                if accepted:
                    fields["reduced_guarantees"] = "accepted"
            else:
                fields["image"] = ask("Container image", image)
                built = ask(
                    "Build it from a folder (blank for none)", str(build) if build else None
                )
                if built:
                    fields["build"] = built
        elif step == 2 and remote:
            st.out.line("      model: the vendor's own; no route is configured")
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
                    project,
                    acts.get("role") or "",
                    acts.get("person"),
                    mode=str(draft.fields.get("mode") or ""),
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
        elif step == 5 and remote:
            st.out.line("      work: the vendor's own trigger; it is given its work as anyone is")
        elif step == 5:
            # A browser agent's program usually watches its inbox in the browser (poll), but
            # its image may need a command to start it, as a hosted agent's may.
            browser = draft.fields.get("mode") == "browser"
            how = ask("How it notices work (command, poll)", wake, "poll" if browser else "command")
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
    from mirrordimensions.service import agents as agents_svc

    st = _state(ctx)
    rows = agents_svc.list_agents(service.load_project(st.start()))
    if st.out.json_mode:
        st.out.document([r.model_dump() for r in rows])
        return
    for r in rows:
        st.out.line(f"  {r.name:<20}{r.mode:<9}{r.acts_as:<16}{r.state}")
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
set_app = typer.Typer(help="Edit mirror.yaml and agent files.", no_args_is_help=True)
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
    st.out.ok(f"rule {rule['name']} set on {app_id}; it applies from the next run")


def _show_change(st: State, change: Any) -> None:
    if st.out.json_mode:
        st.out.document(change)
        return
    if change.before == change.after:
        st.out.ok(f"{change.what}: already so, nothing changed")
        return
    st.out.ok(change.what)
    when = {
        "next run": "at the next run",
        "restart": "when the sandbox restarts: mirror apply",
        "rebuild": "after a rebuild: mirror apply",
    }[change.applies]
    st.out.next_step(f"Saved. It takes effect {when}. Pending: mirror changes")


@set_app.command("visibility")
def set_visibility_cmd(
    ctx: typer.Context,
    app_id: Annotated[str, typer.Argument(help="A system id from mirror system list.")],
    state: Annotated[str, typer.Argument(help="granted, denied, present or absent.")],
) -> None:
    """Set what every agent sees of a system. Between granted, denied and present it applies
    at the next run; to or from absent, after a rebuild. Nothing is rebuilt now."""
    from mirrordimensions.service import environment as env

    st = _state(ctx)
    _show_change(st, env.set_visibility(service.load_project(st.start()), app_id, state))


@set_app.command("grant")
def set_grant_cmd(
    ctx: typer.Context,
    agent: Annotated[str, typer.Argument(help="An agent from mirror agent list.")],
    resource: Annotated[
        str,
        typer.Argument(
            help="<system>/<name>, such as code/billing-service or chat/incidents; "
            "or a system alone."
        ),
    ],
    grant: Annotated[
        str,
        typer.Argument(
            help="read, write or admin for a repository; member for a channel; allowed for "
            "a tool; granted for a whole system; none to take it away."
        ),
    ],
) -> None:
    """Set one grant in an agent file. Grants are exact; it applies at the agent's next run."""
    from mirrordimensions.service import environment as env

    st = _state(ctx)
    _show_change(st, env.set_grant(service.load_project(st.start()), agent, resource, grant))


@app.command("changes")
def changes_cmd(ctx: typer.Context) -> None:
    """Edits saved to mirror.yaml or agent files that are not in effect yet, and when each
    takes effect."""
    from mirrordimensions.service import environment as env

    st = _state(ctx)
    found = env.pending_changes(service.load_project(st.start()))
    if st.out.json_mode:
        st.out.document([c.model_dump(mode="json") for c in found])
        return
    if not found:
        st.out.ok("nothing pending: everything saved is in effect")
        return
    for change in found:
        st.out.line(f"{change.applies:<10}{change.what}")
    if any(c.applies == "rebuild" for c in found):
        st.out.next_step("Rebuild what needs it: mirror apply")
    elif any(c.applies == "restart" for c in found):
        st.out.next_step("Restart the sandbox with them: mirror apply")
    else:
        st.out.next_step("These take effect at the next run, or now with: mirror apply")


@app.command("apply")
def apply_cmd(ctx: typer.Context) -> None:
    """Put pending changes into effect now: rebuild from the first stage they affect, and
    hand a running gateway the current rules and visibility."""
    from mirrordimensions.service import environment as env

    st = _state(ctx)
    result = env.apply_changes(service.load_project(st.start()), on_step=st.out.line)
    if st.out.json_mode:
        st.out.document(result)
        return
    for change in result.applied:
        st.out.ok(change.what)
    for change in result.waiting:
        st.out.line(f"{'next run':<10}{change.what}")
    if not result.applied and not result.waiting:
        st.out.ok("nothing was pending")


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
    scenario: Annotated[
        str, typer.Argument(help="A scenario id, or a suite: core. Or: stop <run-id>.")
    ],
    target: Annotated[
        str | None, typer.Argument(help="With stop: the run to end early.", show_default=False)
    ] = None,
    agent: Annotated[str | None, typer.Option("--agent", help="The agent to run.")] = None,
    allow_emulated: Annotated[
        bool, typer.Option("--allow-emulated", help="Run an image built for another architecture.")
    ] = False,
    max_minutes: Annotated[
        int | None, typer.Option(help="Stop the agent after this many minutes.")
    ] = None,
) -> None:
    """Run scenarios with an agent: restore, deliver, watch, score. Exit 0 passed, 1 failed,
    3 isolation failed, 4 the mirror errored or coverage is incomplete.
    `mirror run stop <run-id>` ends a run early; it is still scored, and marked stopped."""
    from mirrordimensions.service import runs as runs_svc

    st = _state(ctx)
    if scenario == "stop":
        if not target:
            raise MirrorError("Which run?", "", "Run: mirror run stop <run-id>")
        project = service.load_project(st.start())
        runs_svc.stop_run(project, target)
        st.out.ok(f"Asked {target} to stop; it ends within a few seconds and is still scored.")
        st.out.next_step(f"Follow it: mirror trace {target} --follow")
        return
    if target:
        raise MirrorError(
            f"Unexpected argument {target!r}.", "", "Run: mirror run <scenario> --agent <name>"
        )
    if not agent:
        raise MirrorError("Which agent?", "", f"Run: mirror run {scenario} --agent <name>")
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
            if o.suspected:
                text += "  suspected a test"
            if o.status == "passed":
                st.out.ok(text)
            else:
                st.out.fail(text)
        passed = sum(o.status == "passed" for o in outcomes)
        suspected = sum(o.suspected for o in outcomes)
        st.out.line(
            f"{passed} passed · {len(outcomes) - passed} not passed · {suspected} suspected a test"
        )
        st.out.next_step("Read one: mirror trace <run-id>, or mirror report <run-id> --open")
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


def _names(value: str | None) -> frozenset[str]:
    return frozenset(v.strip() for v in (value or "").split(",") if v.strip())


@app.command("trace")
def trace_command(
    ctx: typer.Context,
    run_id: Annotated[str, typer.Argument(help="A run id from mirror runs, or latest.")],
    source: Annotated[
        str | None,
        typer.Option(
            "--source",
            help="Only these sources, comma-separated: runner, gateway, model, mcp, dns, "
            "egress, browser, host, state, evaluator.",
        ),
    ] = None,
    type_: Annotated[
        str | None,
        typer.Option(
            "--type", help="Only these event types, comma-separated: http.exchange, or browser.*."
        ),
    ] = None,
    grep: Annotated[
        str | None, typer.Option("--grep", help="Only events containing this text (any case).")
    ] = None,
    follow: Annotated[
        bool,
        typer.Option(
            "--follow", help="Stream events while the run is in progress (JSON lines with --json)."
        ),
    ] = False,
    full_hosts: Annotated[
        bool, typer.Option("--full-hosts", help="Show whole host names, not just the app.")
    ] = False,
) -> None:
    """A run's timeline: every source in one ordered list. --json prints the raw events."""
    from mirrordimensions.service import runs as runs_svc
    from mirrordimensions.trace import summary, timeline

    st = _state(ctx)
    project = service.load_project(st.start())
    folder = runs_svc.run_dir(project, run_id)
    sources, types = _names(source), _names(type_)
    bad = timeline.unknown(sources, timeline.SOURCES) + timeline.unknown(
        types, timeline.all_types()
    )
    if bad:
        raise MirrorError(
            f"Unknown source or event type: {', '.join(sorted(bad))}.",
            f"Sources are: {', '.join(timeline.SOURCES)}.",
            "Event types are listed in docs/architecture.md, under Events.",
        )
    keep = timeline.Filter(sources, types, grep or "")
    path = folder / "events.jsonl"

    def show(event: dict[str, Any], start: Any) -> None:
        line = summary.summarize(event, full_hosts=full_hosts)
        st.out.line(f"{summary.elapsed(event, start)}  {event.get('source')!s:<10} {line}")

    if follow:
        start = None
        for event in timeline.follow(path):
            if start is None and event.get("type") == "run.start":
                start = timeline.parse_ts(event)
            if not keep(event):
                continue
            if st.out.json_mode:
                print(json.dumps(event), flush=True)
            else:
                show(event, start or timeline.parse_ts(event))
        return
    found = timeline.load(path)
    events = [e for e in found.events if keep(e)]
    if st.out.json_mode:
        st.out.document(events)
        return
    for event in events:
        show(event, found.start)
    for number, problem in found.problems:
        st.out.fail(f"events.jsonl line {number}: {problem}")
    if not events:
        st.out.line("No events match.")
    st.out.next_step(
        f"{len(events)} of {len(found.events)} events · report: mirror report {folder.name} --open"
    )


MARKS = {"blocked": "blocked", "violation": "rule broken"}


def _step_line(step: Any) -> str:
    mark = MARKS.get(step.kind)
    tail = f"  [{mark}]" if mark else ""
    return f"{step.at}  {step.location.label:<34} {step.sentence}{tail}"


@app.command("watch")
def watch_command(
    ctx: typer.Context,
    run_id: Annotated[str, typer.Argument(help="A run id from mirror runs, or latest.")],
) -> None:
    """Follow a run step by step, as the portal's live view shows it: time, where, what.
    A finished run is printed whole. --json prints each step as a JSON line."""
    from mirrordimensions.service import runlog

    st = _state(ctx)
    project = service.load_project(st.start())
    view = runlog.read_steps(project, run_id)
    if not view.live:
        if st.out.json_mode:
            st.out.document([s.model_dump(mode="json") for s in view.steps])
            return
        for step in view.steps:
            st.out.line(_step_line(step))
        st.out.next_step(f"{len(view.steps)} steps · timeline: mirror trace {view.run_id}")
        return
    st.out.line(f"Watching {view.run_id}. Ctrl-C stops watching; the run goes on.")
    shown: dict[int, str] = {}
    for step in runlog.follow_steps(project, run_id):
        if st.out.json_mode:
            print(step.model_dump_json(), flush=True)
            continue
        before = shown.get(step.index)
        if before is None:
            st.out.line(_step_line(step))
        elif before != step.kind and step.kind == "violation":
            st.out.line(f"{step.at}  {step.location.label:<34} {step.detail}  [rule broken]")
        shown[step.index] = step.kind


@app.command("report")
def report_command(
    ctx: typer.Context,
    run_id: Annotated[str, typer.Argument(help="A run id from mirror runs, or latest.")],
    open_: Annotated[bool, typer.Option("--open", help="Open it in the default browser.")] = False,
) -> None:
    """Rebuild a run's report.html, one self-contained page, and optionally open it."""
    import webbrowser

    from mirrordimensions.service import runs as runs_svc

    st = _state(ctx)
    project = service.load_project(st.start())
    path = runs_svc.write_report(project, run_id)
    if st.out.json_mode:
        st.out.document({"run_id": path.parent.name, "report": str(path)})
    else:
        st.out.ok(f"report.html written: {path}")
    if open_ and not webbrowser.open(path.resolve().as_uri()):
        raise MirrorError(
            "No browser could be opened.", "", f"Open the file yourself: {path.resolve()}"
        )


@app.command("reach")
def reach_command(
    ctx: typer.Context,
    agent: Annotated[str, typer.Argument(help="The agent.")],
    run: Annotated[str | None, typer.Option("--run", help="Set against this run.")] = None,
) -> None:
    """What the agent is granted, and what it used in a run (its latest, by default)."""
    from mirrordimensions.service import runs as runs_svc

    st = _state(ctx)
    found = runs_svc.agent_reach(service.load_project(st.start()), agent, run)
    if st.out.json_mode:
        st.out.document(found)
        return
    st.out.line(
        f"{found.agent}, acting as {found.acts_as}"
        + (
            f", set against {found.run_id} ({found.scenario})"
            if found.run_id
            else ", grants only (no run of it kept an access map yet)"
        )
    )
    for title, key, name in (
        ("Repositories", "repositories", "repo"),
        ("Channels", "channels", "channel"),
        ("Tools", "tools", "tool"),
        ("Hosts", "hosts", "host"),
    ):
        rows = cast(list[dict[str, Any]], found.access.get(key) or [])
        if not rows:
            continue
        st.out.line(title)
        for r in rows:
            granted = r.get("granted")
            grant = (
                "not granted"
                if granted in (None, False)
                else "granted"
                if granted is True
                else str(granted)
            )
            how = ", ".join(cast(list[str], r.get("how") or [])) or (
                f"{r.get('requests', 0)} request(s)" if r.get("requests") else "not used"
            )
            line = f"  {r.get(name)!s:<36}{grant:<14}{how}"
            if granted in (None, False) and how != "not used":
                st.out.fail(line.strip())
            else:
                st.out.line(line)


scenario_app = typer.Typer(help="Scenarios, built-in and the project's own.", no_args_is_help=True)
app.add_typer(scenario_app, name="scenario")


@scenario_app.command("list")
def scenario_list(ctx: typer.Context) -> None:
    """Every scenario: id, kind, how the work arrives, and where it comes from."""
    from mirrordimensions.service import scenarios as scen_svc

    st = _state(ctx)
    rows = scen_svc.list_scenarios(service.load_project(st.start()))
    if st.out.json_mode:
        st.out.document([r.model_dump() for r in rows])
        return
    for r in rows:
        st.out.line(f"  {r.id:<28}{r.kind:<12}{r.delivery_words:<20}{r.source}")
    st.out.next_step("Run one: mirror run <id> --agent <name>")


@scenario_app.command("show")
def scenario_show(
    ctx: typer.Context, scenario_id: Annotated[str, typer.Argument(help="A scenario id.")]
) -> None:
    """One scenario as the runner reads it."""
    from ruamel.yaml import YAML

    from mirrordimensions.service import scenarios as scen_svc

    st = _state(ctx)
    shown = scen_svc.show_scenario(service.load_project(st.start()), scenario_id)
    if st.out.json_mode:
        st.out.document(shown)
        return
    import io

    buffer = io.StringIO()
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.dump(shown, buffer)  # pyright: ignore[reportUnknownMemberType]
    st.out.line(buffer.getvalue().rstrip())


@app.command("portal")
def portal_command(
    ctx: typer.Context,
    port: Annotated[
        int, typer.Option("--port", min=1024, max=65535, help="Port on 127.0.0.1.")
    ] = 7420,
    no_open: Annotated[bool, typer.Option("--no-open", help="Do not open a browser.")] = False,
) -> None:
    """Start the local portal on 127.0.0.1 and print its address. Ctrl-C stops it."""
    from mirrordimensions.portal import server

    st = _state(ctx)
    project = service.load_project(st.start())
    server.serve(project, port=port, open_browser=not no_open, say=st.out.line)


mcp_app = typer.Typer(
    help="The operator MCP server: drive the mirror from an AI tool (decision 0009).",
    no_args_is_help=True,
)
app.add_typer(mcp_app, name="mcp")


@mcp_app.command("serve")
def mcp_serve(
    ctx: typer.Context,
    http: Annotated[
        bool,
        typer.Option("--http", help="Serve over HTTP on 127.0.0.1 with a token, instead of stdio."),
    ] = False,
    port: Annotated[
        int, typer.Option("--port", min=1024, max=65535, help="Port on 127.0.0.1 (--http).")
    ] = 7421,
) -> None:
    """Serve the operator MCP server for this world. By default over stdio, for an AI tool
    to launch (no port at all); with --http on 127.0.0.1, with a token in the header.
    Run content it returns is marked untrusted; tools that act or edit need confirm=true.
    Nothing destructive is offered."""
    import secrets as _secrets

    from mirrordimensions.mcp.operator import server

    st = _state(ctx)
    project = service.load_project(st.start())
    if not http:
        server.serve(project)  # stdout belongs to the protocol: nothing else is printed
        return
    token = _secrets.token_urlsafe(24)
    say = st.out.line
    say(f"Operator MCP server for {project.root.name} at http://127.0.0.1:{port}/mcp")
    say(f"Send the header: Authorization: Bearer {token}")
    say("Only this computer can reach it. Ctrl-C stops it.")
    server.serve(project, http=True, port=port, token=token)


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
    """Prove the engine's guarantees: its own kernel, private endpoint, no host access, egress."""
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


@engine_app.command("update")
def engine_update(
    ctx: typer.Context,
    restart: Annotated[
        bool,
        typer.Option("--restart", help="Restart the engine if the update needs it (a new kernel)."),
    ] = False,
) -> None:
    """Install the engine's package updates now. It never installs them by itself; run this
    with the sandbox down (mirror down). The next runs record the new kernel."""
    from mirrordimensions.service import engine as svc

    st = _state(ctx)
    outcome = svc.update_engine(restart=restart, on_step=st.out.line)
    if st.out.json_mode:
        st.out.document(outcome)
        return
    if outcome.upgraded:
        st.out.ok(f"{len(outcome.upgraded)} package(s) updated")
        for line in outcome.upgraded:
            st.out.line(f"      {line}")
    else:
        st.out.ok("the engine's packages were already up to date")
    st.out.line(f"{'Kernel':<10}{outcome.kernel}")
    if outcome.reboot_required:
        st.out.next_step("A restart finishes the update: mirror engine update --restart")
    else:
        st.out.next_step("Then: mirror up")


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
            "On Windows: wsl -d mirrordimensions-engine -u root"
            if engine.name == "wsl"
            else "Use the driver's own tools.",
        )
    env = {**os.environ, "LIMA_HOME": str(engine.lima_home)}
    os.execve(str(engine.limactl), [str(engine.limactl), "shell", INSTANCE, *ctx.args], env)  # noqa: S606


def _show_engine(st: State, status: object) -> None:
    from datetime import UTC, datetime

    from mirrordimensions.engine.base import EngineStatus, update_age_days, update_note

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
    shown = {k: v for k, v in s.versions.items() if k not in ("updated", "reboot")}
    if shown:
        st.out.line(f"{'Versions':<10}" + " · ".join(f"{k} {v}" for k, v in sorted(shown.items())))
    if s.versions.get("updated"):
        age = update_age_days(s.versions, datetime.now(UTC).date())
        restart = " · a restart is due" if s.versions.get("reboot") == "yes" else ""
        st.out.line(f"{'Updated':<10}{s.versions['updated']} ({age} days ago){restart}")
    if s.clock_offset_s is not None:
        st.out.line(f"{'Clock':<10}{s.clock_offset_s:+.3f} s from the host")
    note = update_note(s.versions, datetime.now(UTC).date())
    if note:
        st.out.line(f"{'Note':<10}{note}")


def main() -> None:
    use_utf8_streams()
    try:
        app()
    except MirrorError as exc:
        Output().error(exc.what, exc.why, exc.fix)
        raise SystemExit(exc.exit_code) from None
    except KeyboardInterrupt:
        raise SystemExit(130) from None
