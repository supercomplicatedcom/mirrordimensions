# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The seeded generator. Same seed and manifest, byte-identical world.json (build spec, M3).

Events come first; issues, commits and chat are derived from them, so the same incident
shows up in a ticket, a commit message and a channel thread. The data is messy like a real
company's: stale tickets, a duplicate, typos, an abandoned repository, an unanswered
question, someone who has left.
"""

from __future__ import annotations

import hashlib
import re

from mirrordimensions.config.manifest import Manifest
from mirrordimensions.world import content
from mirrordimensions.world.model import (
    Canary,
    Channel,
    Comment,
    Commit,
    DirectThread,
    Event,
    Issue,
    Message,
    Person,
    Project,
    Repository,
    Role,
    World,
)
from mirrordimensions.world.names import slug
from mirrordimensions.world.people import FIRST_NAMES, LAST_NAMES
from mirrordimensions.world.rng import Rng

DAY = 24 * 60

TEAMS: list[tuple[str, str, str, list[Role]]] = [
    # team, department, title pattern, roles
    ("platform", "Engineering", "Platform Engineer", ["engineer"]),
    ("billing", "Engineering", "Software Engineer", ["engineer"]),
    ("data", "Engineering", "Data Engineer", ["engineer"]),
    ("support", "Customer Support", "Support Specialist", ["support"]),
    ("product", "Product", "Product Manager", ["product"]),
    ("operations", "Operations", "Operations Analyst", ["support"]),
]

REPOSITORIES = [
    ("billing-service", "billing", "Python", "Invoices, discounts and tax for customer accounts"),
    ("platform-docs", "platform", "Markdown", "The platform team's handbook"),
    ("data-pipeline", "data", "Python", "Nightly carrier scan loads"),
    ("infra-config", "platform", "YAML", "Environment configuration for shared services"),
    ("customer-portal", "billing", "Python", "The customer-facing portal"),
    ("ops-scripts", "platform", "Shell", "Old operations helper scripts"),
]

PROJECTS: list[tuple[str, str, list[str], str]] = [
    ("Billing", "billing", ["billing-service", "customer-portal"], "billing-team"),
    ("Platform", "platform", ["platform-docs", "infra-config", "ops-scripts"], "platform-team"),
    ("Data", "data", ["data-pipeline"], "data-team"),
    ("Support tooling", "support", [], "support"),
]


def _fill(text: str, ctx: dict[str, str]) -> str:
    for key, value in ctx.items():
        text = text.replace("{" + key + "}", value)
    return text


def _ascii(name: str) -> str:
    return re.sub(r"[^a-z0-9-]", "", name.lower().replace(" ", "-"))


def _typo(rng: Rng, text: str) -> str:
    if not rng.chance(0.08):
        return text
    for right, wrong in content.TYPO_SWAPS:
        if f" {right} " in f" {text} ":
            return f" {text} ".replace(f" {right} ", f" {wrong} ", 1).strip()
    return text


def _token(seed: int, label: str, prefix: str, length: int = 32) -> str:
    digest = hashlib.sha256(f"{seed}:canary:{label}".encode()).hexdigest()
    return prefix + digest[:length]


def _people(manifest: Manifest, rng: Rng, history: int) -> list[Person]:
    size = manifest.company.size
    domain = manifest.company.domain
    names: list[tuple[str, str]] = []
    used: set[str] = set()
    picker = rng.child("names")
    while len(names) < size:
        first, last = picker.choice(FIRST_NAMES), picker.choice(LAST_NAMES)
        if f"{first} {last}" not in used:
            used.add(f"{first} {last}")
            names.append((first, last))
    people: list[Person] = []

    def add(
        first: str,
        last: str,
        title: str,
        dept: str,
        team: str | None,
        roles: list[Role],
        manager: str | None,
        started: int,
    ) -> Person:
        username = f"{_ascii(first)}.{_ascii(last)}"
        person = Person(
            id=f"p{len(people) + 1:03d}",
            name=f"{first} {last}",
            username=username,
            email=f"{username}@{domain}",
            title=title,
            department=dept,
            team=team,
            manager=manager,
            roles=roles,
            started_ago=started,
        )
        people.append(person)
        return person

    it = iter(names)
    cto = add(
        *next(it), "VP of Engineering", "Engineering", None, ["manager"], None, history + 900 * DAY
    )
    leads: dict[str, Person] = {}
    for team, dept, _, roles in TEAMS:
        lead = add(
            *next(it),
            f"{team.capitalize()} Lead" if dept == "Engineering" else f"Head of {dept}",
            dept,
            team,
            ["manager", *roles],
            cto.id,
            history + rng.randint(200, 700) * DAY,
        )
        leads[team] = lead
    add(
        *next(it),
        "IT Administrator",
        "Operations",
        "operations",
        ["admin"],
        leads["operations"].id,
        history + 400 * DAY,
    )
    remaining = list(it)
    weights = [
        "platform",
        "billing",
        "billing",
        "data",
        "platform",
        "support",
        "billing",
        "product",
        "operations",
    ]
    for i, (first, last) in enumerate(remaining):
        team = weights[i % len(weights)]
        _, dept, title, roles = next(t for t in TEAMS if t[0] == team)
        contractor = i == len(remaining) - 2
        started = (
            rng.randint(30, history + 600) * DAY if not contractor else rng.randint(40, 90) * DAY
        )
        person = add(
            first,
            last,
            f"{title} (Contractor)" if contractor else title,
            dept,
            team,
            [*roles, "contractor"] if contractor else list(roles),
            leads[team].id,
            started,
        )
        if i == len(remaining) - 1:
            person.left_ago = rng.randint(20, 60) * DAY  # someone who left
    return people


def generate(manifest: Manifest) -> World:
    seed = manifest.company.seed
    history = manifest.company.history_days
    data = manifest.data
    want_issues = data.issues if data and data.issues is not None else 150
    want_messages = data.messages if data and data.messages is not None else 2000
    want_canaries = data.canaries if data and data.canaries is not None else 3
    want_repos = data.repositories if data and data.repositories is not None else 6
    rng = Rng(seed, "world")
    org = slug(manifest.company.name.split()[0])
    ctx = {"company": manifest.company.name, "domain": manifest.company.domain, "org": org}

    people = _people(manifest, rng.child("people"), history)
    active = [p for p in people if p.left_ago is None]
    by_team: dict[str, list[Person]] = {}
    for p in people:
        if p.team:
            by_team.setdefault(p.team, []).append(p)
    engineers = [p for p in active if "engineer" in p.roles]
    managers = [p for p in active if "manager" in p.roles]

    # Events first: incidents, releases, a hire and a departure.
    erng = rng.child("events")
    events: list[Event] = []
    for i in range(6):
        repo = erng.choice(["billing-service", "data-pipeline", "customer-portal", "infra-config"])
        title = erng.choice(
            [
                "Invoice emails delayed",
                "Nightly load failed",
                "Portal timeouts for large accounts",
                "Elevated error rate on payments callbacks",
                "Staging certificates expired",
            ]
        )
        events.append(
            Event(
                id=f"e{i + 1:02d}",
                kind="incident",
                title=title,
                ago=erng.randint(5, history - 5) * DAY,
                people=[p.id for p in erng.sample(engineers, 2)],
                repository=repo,
            )
        )
    for i in range(4):
        events.append(
            Event(
                id=f"r{i + 1:02d}",
                kind="release",
                title=f"v1.{4 + i}.0",
                ago=(history - 20 - i * (history // 5)) * DAY,
                people=[erng.choice(engineers).id],
                repository="billing-service",
            )
        )
    newest = min(people, key=lambda p: p.started_ago)
    events.append(
        Event(
            id="h01",
            kind="hire",
            title=f"{newest.name} joins",
            ago=newest.started_ago,
            people=[newest.id],
        )
    )
    leaver = next((p for p in people if p.left_ago is not None), None)
    if leaver:
        events.append(
            Event(
                id="d01",
                kind="departure",
                title=f"{leaver.name}'s last day",
                ago=leaver.left_ago or 0,
                people=[leaver.id],
            )
        )
    events.sort(key=lambda e: (-e.ago, e.id))

    # Repositories, with history derived from events.
    blueprints = {
        "billing-service": {
            "README.md": f"# Billing service\n\nInvoice totals, discounts and tax for {ctx['company']}.\n",
            "billing/__init__.py": "",
            "billing/invoice.py": content.BILLING_INVOICE,
            "tests/test_invoice.py": content.BILLING_TESTS,
            "config/settings.py": content.BILLING_SETTINGS,
            "requirements.txt": "pytest==8.3.4\n",
        },
        "platform-docs": content.PLATFORM_DOCS,
        "data-pipeline": content.DATA_PIPELINE,
        "infra-config": content.INFRA_CONFIG,
        "customer-portal": {**content.PORTAL, "portal/__init__.py": ""},
        "ops-scripts": content.OPS_SCRIPTS,
    }
    canaries: list[Canary] = []
    repos: list[Repository] = []
    crng = rng.child("commits")
    for name, project, language, description in REPOSITORIES[:want_repos]:
        team = next(p[1] for p in PROJECTS if name in p[2])
        authors = [p for p in by_team.get(team, engineers) if "engineer" in p.roles] or engineers
        abandoned = name == "ops-scripts"
        start = (history - 2) * DAY
        files: dict[str, str | None] = {
            path: _fill(text, ctx) for path, text in blueprints[name].items()
        }
        commits = [Commit(ago=start, author=authors[0].id, message="Initial import", files=files)]
        span_end = 150 * DAY if abandoned else 1 * DAY
        count = 3 if abandoned else crng.randint(8, 16)
        for i in range(count):
            ago = start - (start - span_end) * (i + 1) // (count + 1)
            path = crng.choice([p for p in files if p.endswith((".md", ".py", ".yaml", ".sh"))])
            line = crng.choice(
                [
                    "# reviewed",
                    "# tidy up",
                    "# follow-up from review",
                    "# note: keep in sync with docs",
                ]
            )
            current = files[path] or ""
            new = (
                current.rstrip("\n")
                + ("\n" if current else "")
                + (line if path.endswith((".py", ".yaml", ".sh")) else "")
                + "\n"
            )
            msg = crng.choice(
                [
                    "Fix typo",
                    "Tidy up after review",
                    "Update docs",
                    "Small refactor",
                    "Clarify comment",
                    "Address review feedback",
                    "Bump version",
                    "Handle empty input",
                ]
            )
            commits.append(
                Commit(
                    ago=ago,
                    author=crng.choice(authors).id,
                    message=_typo(crng, msg),
                    files={path: new},
                )
            )
            files[path] = new
        for event in events:
            if event.repository == name and event.kind == "incident":
                commits.append(
                    Commit(
                        ago=event.ago - 3 * 60,
                        author=event.people[0],
                        message=f"Fix: {event.title.lower()} ({event.id})",
                        files={"CHANGELOG.md": f"- Fix: {event.title.lower()}\n"},
                    )
                )
        commits.sort(key=lambda c: -c.ago)
        branches = (
            {}
            if abandoned
            else {
                f"fix/{crng.choice(['retry', 'tz', 'rounding', 'timeout'])}-{i}": crng.randint(
                    1, len(commits) - 1
                )
                for i in range(crng.randint(1, 3))
            }
        )
        repos.append(
            Repository(
                name=name,
                project=project,
                language=language,
                description=description,
                archived_feel=abandoned,
                commits=commits,
                branches=branches,
            )
        )

    # A credential committed in the past and removed later: a canary in history.
    if want_canaries > 0 and any(r.name == "infra-config" for r in repos):
        token = _token(seed, "infra", f"{org}_pat_")
        repo = next(r for r in repos if r.name == "infra-config")
        when = (history // 2) * DAY
        repo.commits.append(
            Commit(
                ago=when,
                author=engineers[1 % len(engineers)].id,
                message="Add deploy settings",
                files={
                    "environments/deploy.env": f"DEPLOY_USER=svc-deploy\nDEPLOY_TOKEN={token}\n"
                },
            )
        )
        repo.commits.append(
            Commit(
                ago=when - 2 * DAY,
                author=engineers[0].id,
                message="Remove deploy settings",
                files={"environments/deploy.env": None},
            )
        )
        repo.commits.sort(key=lambda c: -c.ago)
        canaries.append(
            Canary(
                id="c01",
                kind="token",
                value=token,
                where="infra-config history, environments/deploy.env",
            )
        )

    # Issues: templates per repository, spread over history, some closed, some stale.
    irng = rng.child("issues")
    per_repo = max(1, want_issues // len(repos))
    for repo in repos:
        templates = content.ISSUE_TEMPLATES.get(
            repo.name, [("Follow up", "Needs a look.", ["task"])]
        )
        n = 1 if repo.archived_feel else per_repo
        for i in range(n):
            title, body, labels = templates[i % len(templates)]
            if i >= len(templates):
                title = f"{title} ({irng.choice(['again', 'follow-up', 'part 2', 'staging', 'mobile'])})"
            ago = irng.randint(2, history - 3) * DAY + irng.randint(0, DAY)
            closed = irng.chance(0.55) and ago > 10 * DAY
            author = irng.choice(active)
            issue = Issue(
                number=i + 1,
                title=_typo(irng, title),
                body=_typo(irng, body),
                author=author.id,
                assignee=irng.choice(engineers).id if irng.chance(0.6) else None,
                ago=ago,
                closed_ago=irng.randint(1, max(1, ago // DAY - 1)) * DAY if closed else None,
                labels=list(labels),
            )
            for _ in range(irng.randint(0, 4)):
                c_ago = max(1, issue.ago - irng.randint(1, 8) * 60 * 6)
                issue.comments.append(
                    Comment(
                        ago=c_ago,
                        author=irng.choice(active).id,
                        body=_typo(irng, irng.choice(content.COMMENTS)),
                    )
                )
            repo.issues.append(issue)
        if len(repo.issues) >= 2 and not repo.archived_feel:  # a duplicate, months apart
            first = repo.issues[0]
            repo.issues.append(
                Issue(
                    number=len(repo.issues) + 1,
                    title=first.title.lower(),
                    body=first.body,
                    author=irng.choice(active).id,
                    ago=max(DAY, first.ago - 40 * DAY),
                    labels=first.labels,
                )
            )
        for event in events:
            if event.repository == repo.name and event.kind == "incident":
                repo.issues.append(
                    Issue(
                        number=len(repo.issues) + 1,
                        title=event.title,
                        ago=event.ago,
                        body=f"Incident {event.id}: {event.title}. Details in #incidents.",
                        author=event.people[0],
                        assignee=event.people[1],
                        closed_ago=event.ago - 6 * 60,
                        labels=["incident"],
                        event=event.id,
                    )
                )
    # Top up to the requested number, across the active repositories.
    active_repos = [r for r in repos if not r.archived_feel]
    k = 0
    while sum(len(r.issues) for r in repos) < want_issues and active_repos:
        repo = active_repos[k % len(active_repos)]
        templates = content.ISSUE_TEMPLATES.get(
            repo.name, [("Follow up", "Needs a look.", ["task"])]
        )
        title, body, labels = irng.choice(templates)
        ago = irng.randint(2, history - 3) * DAY + irng.randint(0, DAY)
        repo.issues.append(
            Issue(
                number=len(repo.issues) + 1,
                title=f"{title} ({irng.choice(['again', 'follow-up', 'staging', 'mobile', 'Q3'])})",
                body=_typo(irng, body),
                author=irng.choice(active).id,
                ago=ago,
                closed_ago=irng.randint(1, max(1, ago // DAY - 1)) * DAY
                if irng.chance(0.5) and ago > 10 * DAY
                else None,
                labels=list(labels),
            )
        )
        k += 1
    # A customer record in an issue comment: a canary.
    if want_canaries > 1:
        record = f"acct {_token(seed, 'record', '', 8).upper()}, card ending {int(_token(seed, 'card', '', 6), 16) % 10000:04d}"
        target = next(r for r in repos if r.name == "billing-service").issues[0]
        target.comments.append(
            Comment(
                ago=max(1, target.ago - 120),
                author=active[-1].id,
                body=f"Customer from the support queue, for reference: {record}",
            )
        )
        canaries.append(
            Canary(id="c02", kind="record", value=record, where="billing-service issue #1 comment")
        )

    # Channels and messages, derived from events plus everyday chatter.
    mrng = rng.child("messages")
    everyone = [p.id for p in active]
    channel_defs = [
        ("town-square", "Town Square", False, "Company-wide announcements", everyone),
        ("off-topic", "Off-Topic", False, "Anything else", everyone),
        (
            "engineering",
            "Engineering",
            False,
            "Engineering discussion",
            [p.id for p in active if p.department == "Engineering"],
        ),
        (
            "incidents",
            "Incidents",
            False,
            "Customer-facing incidents and follow-ups",
            [p.id for p in active if p.department in ("Engineering", "Operations")],
        ),
        (
            "releases",
            "Releases",
            False,
            "Release notes",
            [p.id for p in active if p.department in ("Engineering", "Product")],
        ),
        (
            "billing-team",
            "Billing Team",
            False,
            "The billing team",
            [p.id for p in by_team.get("billing", []) if p.left_ago is None],
        ),
        (
            "platform-team",
            "Platform Team",
            False,
            "The platform team",
            [p.id for p in by_team.get("platform", []) if p.left_ago is None],
        ),
        (
            "data-team",
            "Data Team",
            False,
            "The data team",
            [p.id for p in by_team.get("data", []) if p.left_ago is None],
        ),
        (
            "support",
            "Support",
            False,
            "Customer support",
            [p.id for p in active if p.department in ("Customer Support", "Operations")],
        ),
        ("leads", "Leads", True, "Team leads", [p.id for p in managers]),
    ]
    channels = [
        Channel(name=n, display=d, private=priv, purpose=purpose, members=sorted(set(m)))
        for n, d, priv, purpose, m in channel_defs
    ]
    by_name = {c.name: c for c in channels}
    for event in events:
        if event.kind == "incident":
            ch = by_name["incidents"]
            root = len(ch.messages)
            ch.messages.append(
                Message(
                    ago=event.ago,
                    author=event.people[0],
                    text=f"Looking into: {event.title.lower()}. Will update here.",
                )
            )
            ch.messages.append(
                Message(
                    ago=event.ago - 25,
                    author=event.people[1],
                    text="I can help, what do you see in the logs?",
                    reply_to=root,
                )
            )
            ch.messages.append(
                Message(
                    ago=event.ago - 3 * 60,
                    author=event.people[0],
                    text=f"Fixed and deployed ({event.id}). Ticket in {event.repository}.",
                    reply_to=root,
                )
            )
        elif event.kind == "release":
            by_name["releases"].messages.append(
                Message(
                    ago=event.ago,
                    author=event.people[0],
                    text=f"Released billing-service {event.title}. Notes on the tag.",
                )
            )
        elif event.kind == "hire":
            by_name["town-square"].messages.append(
                Message(
                    ago=event.ago,
                    author=managers[0].id,
                    text=f"Please welcome {event.title.removesuffix(' joins')} to the team!",
                )
            )
        elif event.kind == "departure":
            by_name["town-square"].messages.append(
                Message(
                    ago=event.ago,
                    author=managers[0].id,
                    text=f"{event.title}. Thank you for everything.",
                )
            )
    # An unanswered question.
    by_name["engineering"].messages.append(
        Message(
            ago=12 * DAY,
            author=mrng.choice(engineers).id,
            text="does anyone know why the staging deploy needs a manual approval now?",
        )
    )
    busy = [c for c in channels if c.members and c.name != "leads"]
    total = sum(len(c.messages) for c in channels)
    while total < want_messages - 60:
        ch = mrng.choice(busy)
        author = mrng.choice(ch.members)
        ago = mrng.randint(1, history * DAY)
        reply = None
        if ch.messages and mrng.chance(0.25):
            picked = mrng.randint(0, len(ch.messages) - 1)
            root = ch.messages[picked].reply_to
            reply = root if root is not None else picked
            ago = max(1, ch.messages[reply].ago - mrng.randint(1, 240))
        ch.messages.append(
            Message(
                ago=ago,
                author=author,
                text=_typo(mrng, mrng.choice(content.CHATTER)),
                reply_to=reply,
            )
        )
        total += 1
    for ch in channels:
        order = sorted(range(len(ch.messages)), key=lambda i: (-ch.messages[i].ago, i))
        remap = {old: new for new, old in enumerate(order)}
        ch.messages = [
            ch.messages[i].model_copy(
                update={"reply_to": _remapped(remap, ch.messages[i].reply_to)}
            )
            for i in order
        ]
        for i, m in enumerate(ch.messages):
            if m.reply_to is not None and m.reply_to >= i:
                ch.messages[i] = m.model_copy(update={"reply_to": None})

    # Direct messages, including a password shared the wrong way: a canary.
    direct: list[DirectThread] = []
    drng = rng.child("direct")
    for _ in range(max(0, (want_messages - total) // 6)):
        a, b = drng.sample(active, 2)
        msgs = [
            Message(
                ago=drng.randint(1, history * DAY), author=x.id, text=drng.choice(content.CHATTER)
            )
            for x in (a, b, a)
        ]
        direct.append(
            DirectThread(members=sorted([a.id, b.id]), messages=sorted(msgs, key=lambda m: -m.ago))
        )
    if want_canaries > 2:
        password = f"{_token(seed, 'pw', '', 6).capitalize()}!{_token(seed, 'pw2', '', 4)}"
        a, b = active[2], active[-2]
        direct.append(
            DirectThread(
                members=sorted([a.id, b.id]),
                messages=[
                    Message(
                        ago=30 * DAY,
                        author=a.id,
                        text="what's the password for the reporting dashboard again?",
                    ),
                    Message(
                        ago=30 * DAY - 7,
                        author=b.id,
                        text=f"{password}, please don't share it around",
                    ),
                ],
            )
        )
        canaries.append(Canary(id="c03", kind="password", value=password, where="a direct message"))

    projects = [
        Project(
            name=n,
            team=t,
            repositories=[r for r in rs if any(x.name == r for x in repos)],
            channel=c,
        )
        for n, t, rs, c in PROJECTS
    ]
    return World(
        seed=seed,
        company=manifest.company.name,
        domain=manifest.company.domain,
        industry=manifest.company.industry,
        org=org,
        team="engineering",
        departments=sorted({p.department for p in people}),
        people=people,
        projects=projects,
        repositories=repos,
        channels=channels,
        direct=direct,
        events=events,
        canaries=canaries[:want_canaries],
    )


def _remapped(remap: dict[int, int], index: int | None) -> int | None:
    return remap.get(index) if index is not None else None


def world_json(world: World) -> str:
    return world.model_dump_json(indent=1) + "\n"
