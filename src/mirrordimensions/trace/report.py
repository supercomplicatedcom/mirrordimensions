# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""`report.html`: one self-contained page per run (build spec, "Timeline and report").

Built only from the run's folder (`result.json`, `events.jsonl`, `ledger.json`, the model
exchanges kept in `model/` and the screenshots in `screens/`), so `mirror report` can rebuild
it at any time. The page loads nothing: styles are inline, screenshots are embedded, and there
are no scripts. Every value from the run is escaped, since the agent wrote much of it.
"""

from __future__ import annotations

import base64
import contextlib
import html
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from mirrordimensions.hostos.files import write_text
from mirrordimensions.trace import summary
from mirrordimensions.trace.timeline import Timeline, load

MAX_SCREENSHOTS = 400
MAX_TEXT = 20_000  # characters of one model answer or prompt shown before it is cut

_EVENT_REF = re.compile(r"\bevent (\d+)\b")

STATUS_TEXT = {
    "passed": "Passed",
    "failed": "Failed",
    "errored": "Errored",
    "stopped": "Stopped",
}

CSS = """
:root{--bg:#fbfaf8;--fg:#1d1c1a;--muted:#6b6862;--line:#e4e1db;--panel:#ffffff;
--pass:#1f7a4d;--pass-bg:#e5f3ea;--fail:#a3361f;--fail-bg:#f8e6e1;--warn:#8a5a00;
--warn-bg:#f7eed9;--accent:#2e5aac;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecebe7;--muted:#9c998f;
--line:#2f2e2b;--panel:#1e1e1c;--pass:#6fcf9a;--pass-bg:#1b2e23;--fail:#f08c73;
--fail-bg:#3a201a;--warn:#e7bd62;--warn-bg:#352b16;--accent:#8fb0ee}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1100px;margin:0 auto;padding:32px 24px 64px}
h1{font-size:24px;margin:0 0 4px}
h2{font-size:17px;margin:36px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line)}
h3{font-size:15px;margin:18px 0 6px}
p{margin:6px 0}
a{color:var(--accent)}
.muted{color:var(--muted)}
.mono,code,pre{font-family:var(--mono);font-size:13px}
pre{white-space:pre-wrap;word-break:break-word;background:var(--panel);
border:1px solid var(--line);border-radius:6px;padding:10px;margin:6px 0;max-height:420px;
overflow:auto}
.notice{border-left:3px solid var(--warn);background:var(--warn-bg);padding:8px 12px;
border-radius:4px}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;font-size:13px;font-weight:600}
.pass{color:var(--pass);background:var(--pass-bg)}
.fail{color:var(--fail);background:var(--fail-bg)}
.warn{color:var(--warn);background:var(--warn-bg)}
.facts{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;
margin:18px 0}
.fact{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.fact b{display:block;font-size:12px;font-weight:500;color:var(--muted)}
table{border-collapse:collapse;width:100%;background:var(--panel);
border:1px solid var(--line);border-radius:6px}
th,td{text-align:left;vertical-align:top;padding:6px 10px;border-bottom:1px solid var(--line)}
th{font-size:12px;font-weight:600;color:var(--muted)}
tr:last-child td{border-bottom:0}
tr:target td{background:var(--warn-bg)}
.timeline td{padding:3px 10px;font-family:var(--mono);font-size:12.5px}
.timeline td.what{word-break:break-all}
details{margin:6px 0}
summary{cursor:pointer}
.shots{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}
figure{margin:0;background:var(--panel);border:1px solid var(--line);border-radius:6px;
padding:6px}
figure img{width:100%;display:block;border-radius:3px}
figcaption{font-size:12px;color:var(--muted);margin-top:4px;word-break:break-all}
nav{font-size:13px;margin:8px 0 0}
nav a{margin-right:12px}
"""


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _link_events(text: str) -> str:
    """Escaped text with every "event N" a link to that row of the timeline."""
    return _EVENT_REF.sub(lambda m: f'<a href="#e{m.group(1)}">event {m.group(1)}</a>', esc(text))


def _badge(ok: bool | None, yes: str = "passed", no: str = "failed") -> str:
    if ok is None:
        return '<span class="badge warn">n/a</span>'
    return f'<span class="badge {"pass" if ok else "fail"}">{esc(yes if ok else no)}</span>'


def _table(headers: list[str], rows: list[list[str]], cls: str = "") -> str:
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f'<table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def _clip(text: str, limit: int = MAX_TEXT) -> str:
    return (
        text if len(text) <= limit else text[:limit] + f"\n… ({len(text) - limit} more characters)"
    )


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def render(folder: Path) -> str:
    """The report for the run in `folder`."""
    result = cast(dict[str, Any], _read_json(folder / "result.json") or {})
    found = load(folder / "events.jsonl")
    run_id = str(result.get("run_id") or folder.name)
    parts: list[str] = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        # No network: nothing on this page may load from anywhere, not even by accident.
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "img-src data:; style-src 'unsafe-inline'\">",
        f"<title>{esc(result.get('scenario') or 'Run')} · {esc(run_id)}</title>",
        f"<style>{CSS}</style></head><body><main>",
    ]
    parts += _header(result, run_id, found)
    parts += _checks(result)
    parts += _side_effects(result)
    parts += _canaries(result)
    parts += _behaviour(result)
    parts += _access(result)
    parts += _models(folder, found)
    parts += _screenshots(folder, found)
    parts += _timeline(found)
    parts.append(
        '<p class="muted" style="margin-top:40px">Written by MirrorDimensions from '
        f"<code>{esc(folder.name)}/</code>. Rebuild with <code>mirror report {esc(run_id)}</code>."
        "</p></main></body></html>"
    )
    return "\n".join(parts) + "\n"


def write(folder: Path) -> Path:
    path = folder / "report.html"
    write_text(path, render(folder), owner_only=True)
    return path


def _header(result: dict[str, Any], run_id: str, found: Timeline) -> list[str]:
    status = str(result.get("status") or "unknown")
    cls = "pass" if status == "passed" else "fail" if status in ("failed", "errored") else "warn"
    coverage = cast(dict[str, Any], result.get("coverage") or {})
    world = cast(dict[str, Any], result.get("world") or {})
    platform = cast(dict[str, Any], result.get("platform") or {})
    checks = cast(list[dict[str, Any]], result.get("checks") or [])
    passed = sum(1 for c in checks if c.get("passed"))
    access = cast(dict[str, Any], result.get("access") or {})
    facts = [
        ("Agent", result.get("agent")),
        ("Acting as", result.get("acts_as")),
        ("Checks", f"{passed} of {len(checks)} passed"),
        ("Unexpected changes", len(cast(list[Any], result.get("side_effects") or []))),
        ("Isolation", result.get("isolation")),
        ("Coverage", coverage.get("status", "unknown")),
        ("Suspected a test", "yes" if result.get("suspected") else "no"),
        ("Used outside its grants", access.get("outside_grants", "not recorded")),
        ("World", f"{world.get('name', '?')} (seed {world.get('seed', '?')})"),
        (
            "Engine",
            f"{platform.get('engine_driver', '?')} on {platform.get('host_os', '?')} "
            f"{platform.get('host_arch', '')}, {platform.get('boundary', '?')}",
        ),
        ("Events", len(found.events)),
        ("Started", found.start.strftime("%Y-%m-%d %H:%M:%S UTC") if found.start else "unknown"),
    ]
    out = [
        f"<h1>{esc(result.get('scenario') or 'Run')} "
        f'<span class="badge {cls}">{esc(STATUS_TEXT.get(status, status))}</span></h1>',
        f'<p class="muted mono">{esc(run_id)}</p>',
    ]
    if result.get("reason"):
        out.append(f"<p><b>Why:</b> {esc(result['reason'])}</p>")
    if coverage.get("covers"):
        # A remote agent's run: said before anything else is read (build spec, remote agents).
        out.append(f'<p class="notice"><b>What this covers:</b> {esc(coverage["covers"])}</p>')
    elif coverage.get("warning"):
        out.append(f'<p class="notice"><b>Not evidence:</b> {esc(coverage["warning"])}</p>')
    out.append(
        '<div class="facts">'
        + "".join(f'<div class="fact"><b>{esc(k)}</b>{esc(v)}</div>' for k, v in facts)
        + "</div>"
    )
    delivery = cast(dict[str, Any], result.get("delivery") or {})
    if delivery:
        shown = ", ".join(f"{k}: {v}" for k, v in delivery.items())
        out.append(f"<p><b>Work delivered:</b> {esc(shown)}</p>")
    out.append(
        "<nav>"
        + "".join(
            f'<a href="#{a}">{esc(t)}</a>'
            for a, t in (
                ("checks", "Checks"),
                ("side-effects", "Side effects"),
                ("canaries", "Canaries"),
                ("behaviour", "Egress and suspicion"),
                ("access", "Access map"),
                ("models", "Model exchanges"),
                ("screens", "Screenshots"),
                ("timeline", "Timeline"),
            )
        )
        + "</nav>"
    )
    return out


def _checks(result: dict[str, Any]) -> list[str]:
    checks = cast(list[dict[str, Any]], result.get("checks") or [])
    out = ['<h2 id="checks">Checks</h2>']
    if not checks:
        return [*out, '<p class="muted">No checks ran.</p>']
    rows: list[list[str]] = []
    for c in checks:
        evidence = _link_events(str(c.get("evidence") or ""))
        if c.get("event") is not None:
            evidence += f' (<a href="#e{esc(c["event"])}">event {esc(c["event"])}</a>)'
        args = json.dumps(c.get("args") or {}, sort_keys=True)
        rows.append(
            [
                esc(c.get("kind")),
                f"<code>{esc(c.get('check'))}</code><br>"
                f'<span class="muted mono">{esc(args)}</span>',
                _badge(bool(c.get("passed"))),
                evidence,
            ]
        )
    return [*out, _table(["Kind", "Check", "Result", "Evidence"], rows)]


def _side_effects(result: dict[str, Any]) -> list[str]:
    found = cast(list[dict[str, Any]], result.get("side_effects") or [])
    allowed = result.get("allowed_changes", 0)
    out = [
        '<h2 id="side-effects">Side effects</h2>',
        f'<p class="muted">{esc(allowed)} change(s) allowed by the scenario; '
        f"{len(found)} unexpected.</p>",
    ]
    if found:
        out.append(
            _table(
                ["System", "Object", "Change"],
                [
                    [
                        esc(s.get("system")),
                        f"<code>{esc(s.get('object'))}</code>",
                        esc(s.get("change")),
                    ]
                    for s in found
                ],
            )
        )
    return out


def _canaries(result: dict[str, Any]) -> list[str]:
    travel = cast(list[dict[str, Any]], result.get("canaries") or [])
    out = ['<h2 id="canaries">Canary travel</h2>']
    if not travel:
        return [*out, '<p class="muted">No canary value left the place it was planted.</p>']
    rows = [
        [
            f"<code>{esc(t.get('canary'))}</code>"
            + ("<br><b>left the world</b>" if t.get("left_world") else ""),
            "<br>".join(_link_events(str(p)) for p in cast(list[Any], t.get("seen") or [])),
        ]
        for t in travel
    ]
    return [*out, _table(["Canary", "Seen in"], rows)]


def _behaviour(result: dict[str, Any]) -> list[str]:
    egress = cast(list[dict[str, Any]], result.get("egress") or [])
    flags = cast(list[dict[str, Any]], result.get("suspicion") or [])
    out = [
        '<h2 id="behaviour">Egress and suspicion</h2>',
        "<h3>Attempts to reach outside the world</h3>",
    ]
    if egress:
        out.append(
            _table(
                ["Event", "Kind", "To", "Protocol"],
                [
                    [
                        f'<a href="#e{esc(e.get("event"))}">{esc(e.get("event"))}</a>',
                        esc(e.get("kind")),
                        f"<code>{esc(e.get('to'))}</code>",
                        esc(e.get("proto")),
                    ]
                    for e in egress
                ],
            )
        )
    else:
        out.append('<p class="muted">None.</p>')
    out.append("<h3>Signs the agent suspected a test</h3>")
    if flags:
        out.append(
            "<p>The suspicion scan matched what the agent or its model wrote. "
            "This does not change the result.</p>"
        )
        out.append(
            _table(
                ["Event", "Phrase"],
                [
                    [
                        f'<a href="#e{esc(f.get("event"))}">{esc(f.get("event"))}</a>',
                        f"“{esc(f.get('phrase'))}”",
                    ]
                    for f in flags
                ],
            )
        )
    else:
        out.append('<p class="muted">None found.</p>')
    return out


def _used(row: dict[str, Any]) -> bool:
    return bool(row.get("how") or row.get("requests") or row.get("refused"))


def _access(result: dict[str, Any]) -> list[str]:
    access = cast(dict[str, Any], result.get("access") or {})
    out = ['<h2 id="access">Access map</h2>']
    if not access:
        return [*out, '<p class="muted">Not recorded for this run.</p>']
    out.append(
        '<p class="muted">Everything the agent touched, against what it was granted. '
        "A row marked <b>not granted</b> was used without a grant; a granted row nobody "
        "touched was more access than the work needed.</p>"
    )

    def granted_cell(value: Any) -> str:
        if value in (None, False):
            return '<span class="badge fail">not granted</span>'
        return f'<span class="badge pass">{esc("granted" if value is True else value)}</span>'

    def used_cell(row: dict[str, Any], how: str) -> str:
        if not _used(row):
            return '<span class="muted">untouched</span>'
        first = row.get("first")
        link = f' · first <a href="#e{esc(first)}">event {esc(first)}</a>' if first else ""
        return esc(how) + link

    def host_use(r: dict[str, Any]) -> str:
        refused = f", {r['refused']} refused" if r.get("refused") else ""
        return f"{r.get('requests', 0)} request(s){refused}"

    def kinds(r: dict[str, Any]) -> str:
        return ", ".join(cast(list[str], r.get("how") or []))

    sections: tuple[tuple[str, str, str, Callable[[dict[str, Any]], str]], ...] = (
        ("Hosts", "hosts", "host", host_use),
        ("Repositories", "repositories", "repo", kinds),
        ("Channels", "channels", "channel", kinds),
        ("Tools", "tools", "tool", kinds),
    )
    for title, key, name, how in sections:
        rows = cast(list[dict[str, Any]], access.get(key) or [])
        if not rows:
            continue
        out.append(f"<h3>{esc(title)}</h3>")
        out.append(
            _table(
                [title[:-1] if title != "Repositories" else "Repository", "Used", "Grant"],
                [
                    [
                        f"<code>{esc(r.get(name))}</code>",
                        used_cell(r, how(r)),
                        granted_cell(r.get("granted")),
                    ]
                    for r in rows
                ],
            )
        )
    return out


def _models(folder: Path, found: Timeline) -> list[str]:
    exchanges = [e for e in found.events if e.get("type") == "model.exchange"]
    out = ['<h2 id="models">Model exchanges</h2>']
    if not exchanges:
        return [*out, '<p class="muted">The agent made no model calls through the gateway.</p>']
    out.append(
        '<p class="muted">Credentials are redacted. The prompt is what the agent sent; the '
        "answer is the text the model wrote back.</p>"
    )
    for e in exchanges:
        d = cast(dict[str, Any], e.get("data") or {})
        seq = e.get("seq")
        out.append(
            f'<h3><a href="#e{esc(seq)}">event {esc(seq)}</a> · {esc(summary.summarize(e))}</h3>'
        )
        for label, name in (("Prompt", f"{seq}.request.json"), ("Answer", f"{seq}.answer.txt")):
            path = folder / "model" / name
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="replace")
                if name.endswith(".json"):
                    with contextlib.suppress(ValueError):
                        text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
                out.append(
                    f"<details{' open' if label == 'Answer' else ''}><summary>{label} "
                    f'<span class="muted">({len(text)} characters)</span></summary>'
                    f"<pre>{esc(_clip(text))}</pre></details>"
                )
        if d.get("hosted_tools"):
            out.append(f"<p>Hosted tools: {esc(', '.join(map(str, d['hosted_tools'])))}</p>")
    return out


def _screenshots(folder: Path, found: Timeline) -> list[str]:
    shots = [e for e in found.events if e.get("type") == "browser.screenshot"]
    out = ['<h2 id="screens">Screenshots</h2>']
    if not shots:
        return [*out, '<p class="muted">Not a browser run.</p>']
    figures: list[str] = []
    for e in shots[:MAX_SCREENSHOTS]:
        d = cast(dict[str, Any], e.get("data") or {})
        name = Path(str(d.get("file") or "")).name
        path = folder / "screens" / name
        if not name or not path.is_file():
            continue
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        figures.append(
            f'<figure><img alt="Screenshot at event {esc(e.get("seq"))}" '
            f'src="data:image/jpeg;base64,{data}"><figcaption>'
            f'<a href="#e{esc(e.get("seq"))}">event {esc(e.get("seq"))}</a> · '
            f"{esc(summary.elapsed(e, found.start))} · {esc(d.get('url'))}</figcaption></figure>"
        )
    if len(shots) > MAX_SCREENSHOTS:
        out.append(f'<p class="muted">The first {MAX_SCREENSHOTS} of {len(shots)}.</p>')
    out.append(f'<div class="shots">{"".join(figures)}</div>')
    return out


def _timeline(found: Timeline) -> list[str]:
    out = [
        '<h2 id="timeline">Timeline</h2>',
        f'<p class="muted">{len(found.events)} events from every source, in order. '
        "Times are from the start of the run.</p>",
    ]
    rows = [
        f'<tr id="e{esc(e.get("seq"))}"><td>{esc(e.get("seq"))}</td>'
        f"<td>{esc(summary.elapsed(e, found.start))}</td><td>{esc(e.get('source'))}</td>"
        f'<td class="what">{esc(summary.summarize(e, full_hosts=True))}</td></tr>'
        for e in found.events
    ]
    out.append(
        '<table class="timeline"><thead><tr><th>#</th><th>Time</th><th>Source</th>'
        f"<th>What happened</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )
    if found.problems:
        out.append(
            '<p class="fail">Lines of events.jsonl that could not be read: '
            + esc(", ".join(f"{n} ({p})" for n, p in found.problems))
            + "</p>"
        )
    return out
