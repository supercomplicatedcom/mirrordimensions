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


def main() -> None:
    use_utf8_streams()
    try:
        app()
    except MirrorError as exc:
        Output().error(exc.what, exc.why, exc.fix)
        raise SystemExit(exc.exit_code) from None
    except KeyboardInterrupt:
        raise SystemExit(130) from None
