# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Commands available in M0: init, validate, schema, status.

Exit codes: 0 success, 1 a failed check, 2 a usage or configuration error.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from mirrordimensions import __version__, service
from mirrordimensions.cli.output import Output
from mirrordimensions.config import SCHEMAS
from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.console import use_utf8_streams

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
    status = svc.setup_engine(resources, driver, on_step=st.out.line, experimental=experimental)  # type: ignore[arg-type]
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
