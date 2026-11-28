# SPDX-License-Identifier: Apache-2.0
"""The seeded generator. Same seed and manifest, byte-identical world.json (build spec, M3).

Events come first; issues, commits and chat are derived from them, so the same incident
shows up in a ticket, a fix that references it, and a channel thread. Repositories grow
commit by commit through real changes. The data is messy like a real company's: stale
tickets, a duplicate, typos, an abandoned repository, an unanswered question, someone who
has left. Nothing repeats the way a generator would: issue titles and chat messages are
unique, branch names come from the work they hold, and issue numbers follow time.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence

from mirrordimensions.config.manifest import Manifest
from mirrordimensions.errors import MirrorError
from mirrordimensions.seed.content import SeedContent
from mirrordimensions.world import content
from mirrordimensions.world import profile as profiles
from mirrordimensions.world.compose import Composer
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
from mirrordimensions.world.name_groups import GROUP_WEIGHTS, NAME_GROUPS
from mirrordimensions.world.names import slug
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
    ("data-pipeline", "data", "Python", "Nightly loads into the reporting warehouse"),
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

# Releases each repository ships: (first version, how many). billing-service stops below
# v1.8.0, which the release-notes scenario tags.
RELEASES: dict[str, tuple[tuple[int, int, int], int]] = {
    "billing-service": ((1, 4, 0), 5),
    "customer-portal": ((2, 1, 0), 4),
}

# The company's time zone, minutes east of UTC: office hours are placed in it.
TIME_ZONES = (-300, -300, -300, -360, -360, -420, -480, -480, 0, 60)

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
TIMES = ("9:30", "10", "10:30", "11", "11:30", "1", "1:30", "2", "2:30", "3", "3:30", "4")

# Chat channel -> the pool it draws from, and its share of everyday conversation.
CHANNEL_POOLS: dict[str, tuple[str, int]] = {
    "town-square": ("town-square", 5),
    "off-topic": ("off-topic", 8),
    "engineering": ("engineering", 12),
    "billing-team": ("team", 10),
    "platform-team": ("team", 10),
    "data-team": ("team", 8),
    "support": ("support", 9),
    "incidents": ("incidents", 3),
    "leads": ("team", 2),
}
TEAM_OF_CHANNEL = {"billing-team": "billing", "platform-team": "platform", "data-team": "data"}

# Repositories that run somewhere: a message about deploying, backing up or scaling "a
# repository" names one of these, never the handbook or the configuration.
SERVICES = ("billing-service", "customer-portal", "data-pipeline")
# The same conversation, with other names filled in, recurs no sooner than this.
RECUR_AFTER = 21 * DAY

# Short acknowledgements people really do repeat; everything else is unique.
ACKS = ("+1", "thanks!", "thank you", "ok", "nice", "sounds good", "will do", "on it")


def _facts(
    base: dict[str, str],
    repo: str,
    rng: Rng | None = None,
    people: Sequence[Person] = (),
    **more: str,
) -> Callable[[str], str | None]:
    """World facts for a text about `repo`: the company's, the repository's and `more`; and,
    with `rng`, a service, a colleague, a day and a time, each chosen when first named."""
    values = {**base, "repo": repo, **more}

    def get(name: str) -> str | None:
        if name in values or rng is None:
            return values.get(name)
        if name == "service":
            values[name] = rng.choice(SERVICES)
        elif name == "person" and people:
            values[name] = _first(rng.choice(people))
        elif name == "day":
            values[name] = rng.choice(WEEKDAYS)
        elif name == "time":
            values[name] = rng.choice(TIMES)
        return values.get(name)

    return get


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


def _weighted[T](rng: Rng, items: Sequence[T], weights: Sequence[int]) -> T:
    point = rng.randint(1, sum(weights))
    for item, weight in zip(items, weights, strict=True):
        point -= weight
        if point <= 0:
            return item
    return items[-1]


def _names(rng: Rng, size: int) -> list[tuple[str, str]]:
    """Distinct first names and distinct last names; most people's two names come from the
    same tradition, as they would in a real workforce."""
    picker = rng.child("names")
    used_first: set[str] = set()
    used_last: set[str] = set()
    names: list[tuple[str, str]] = []
    groups = list(range(len(NAME_GROUPS)))
    attempts = 0
    while len(names) < size:
        attempts += 1
        g = _weighted(picker, groups, GROUP_WEIGHTS)
        lg = g if picker.chance(0.85) else _weighted(picker, groups, GROUP_WEIGHTS)
        first = picker.choice(NAME_GROUPS[g][1])
        last = picker.choice(NAME_GROUPS[lg][2])
        if (first in used_first or last in used_last) and attempts < size * 200:
            continue
        used_first.add(first)
        used_last.add(last)
        names.append((first, last))
    return names


ENGINEERING_TEAMS = ("platform", "billing", "data")


def _teams(profile: profiles.Profile) -> list[tuple[str, str, str, list[Role]]]:
    """The teams, with the department and job each has in this industry."""
    org = profile.organization.teams
    return [
        (
            team,
            org[team].department if team in org else dept,
            org[team].title if team in org else title,
            roles,
        )
        for team, dept, title, roles in TEAMS
    ]


def _people(
    manifest: Manifest,
    rng: Rng,
    history: int,
    profile: profiles.Profile,
    seeded: SeedContent | None = None,
) -> list[Person]:
    domain = manifest.company.domain
    names = _names(rng, manifest.company.size)
    # The seed folder's people come first, in its order; the generator fills the rest
    # (decision 0030). Their own titles are kept; their teams follow the company's shape.
    given = (seeded.people if seeded else [])[: len(names)]
    taken = {n.split(" ", 1)[0].lower() for n in (p.name for p in given)}
    names = [(p.name.split(" ", 1)[0], p.name.split(" ", 1)[1]) for p in given] + [
        n for n in names if n[0].lower() not in taken
    ][: len(names) - len(given)]
    titles = {i: p.title for i, p in enumerate(given) if p.title}
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
        if len(people) in titles:  # a person from the seed folder keeps their own title
            person.title = titles[len(people)]
        people.append(person)
        return person

    teams = _teams(profile)
    labels = profile.organization.teams
    engineering = profile.organization.engineering
    operations = next(dept for team, dept, _, _ in teams if team == "operations")
    it = iter(names)
    cto = add(
        *next(it),
        profile.organization.head,
        engineering,
        None,
        ["manager"],
        None,
        history + 900 * DAY + rng.randint(0, DAY - 1),
    )
    leads: dict[str, Person] = {}
    for team, dept, _, roles in teams:
        usual = f"{team.capitalize()} Lead" if team in ENGINEERING_TEAMS else f"Head of {dept}"
        lead = add(
            *next(it),
            (labels[team].lead if team in labels else None) or usual,
            dept,
            team,
            ["manager", *roles],
            cto.id,
            history + rng.randint(200, 700) * DAY + rng.randint(0, DAY - 1),
        )
        leads[team] = lead
    add(
        *next(it),
        profile.organization.it_admin,
        operations,
        "operations",
        ["admin"],
        leads["operations"].id,
        history + 400 * DAY + rng.randint(0, DAY - 1),
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
        _, dept, title, roles = next(t for t in teams if t[0] == team)
        contractor = i == len(remaining) - 2
        started = (
            rng.randint(30, history + 600) * DAY if not contractor else rng.randint(40, 90) * DAY
        ) + rng.randint(0, DAY - 1)  # a time of day of its own, not a whole number of days
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
            person.left_ago = rng.randint(20, 60) * DAY + rng.randint(
                0, DAY - 1
            )  # someone who left
    return people


def _section(person: Person) -> str:
    """Which part of the company a person works in, by team, whatever this industry calls
    its departments: the engineering head belongs to engineering."""
    if person.team in ENGINEERING_TEAMS or (person.team is None and person.manager is None):
        return "engineering"
    return person.team or ""


def _first(person: Person) -> str:
    return person.name.split(" ", 1)[0]


STOPWORDS = frozenset(
    [
        "the",
        "and",
        "for",
        "with",
        "when",
        "from",
        "that",
        "this",
        "into",
        "after",
        "before",
        "about",
        "whether",
        "should",
        "does",
        "not",
        "are",
        "our",
        "its",
        "can",
        "on",
        "of",
        "to",
        "in",
        "is",
        "be",
        "by",
        "at",
        "or",
        "an",
        "as",
        "it",
        "we",
    ]
)


def _branch_name(issue: Issue, owner: Person) -> str:
    words = [
        w
        for w in re.findall(r"[a-z0-9]+", issue.title.lower())
        if len(w) > 2 and w not in STOPWORDS
    ][:4]
    topic = "-".join(words) or f"issue-{issue.number}"
    if "bug" in issue.labels:
        return f"fix/{topic}"
    if "enhancement" in issue.labels:
        return f"feature/{topic}"
    if "docs" in issue.labels:
        return f"docs/{topic}"
    return f"{_ascii(_first(owner))}/{topic}"


class _NoFit(Exception):
    """A thread names something the world has none of at that moment."""


class _Chat:
    """Composes chat threads from the profile so that no message repeats, apart from short
    acknowledgements, and each slot is filled from the world as it was at the time."""

    def __init__(
        self,
        rng: Rng,
        people: dict[str, Person],
        repos: list[Repository],
        profile: profiles.Profile,
        base: dict[str, str],
    ) -> None:
        self.rng = rng
        self.people = people
        self.repos = repos
        self.profile = profile
        self.base = base
        self.used: set[str] = set()
        self.uses: dict[tuple[str, int], int] = {}
        self.at: dict[tuple[str, int], list[int]] = {}
        self.services = [r.name for r in repos if r.name in SERVICES] or [r.name for r in repos]

    def _issue(self, repo_names: list[str], ago: int) -> tuple[Repository, Issue] | None:
        candidates = [
            (r, i)
            for r in self.repos
            if r.name in repo_names
            for i in r.issues
            if i.ago > ago + 60 and (i.closed_ago is None or i.closed_ago < ago)
        ]
        open_then = [(r, i) for r, i in candidates if i.closed_ago is None or i.closed_ago < ago]
        pool = [(r, i) for r, i in open_then if i.closed_ago is None] or open_then
        return self.rng.choice(pool) if pool else None

    def thread(
        self, kind: str, members: list[str], repo_names: list[str], ago: int
    ) -> list[tuple[str, str]] | None:
        """[(author id, text)] for one thread, or None if nothing fresh fits."""
        threads = self.profile.chat[kind]
        load = [self.uses.get((kind, i), 0) / threads[i].weight for i in range(len(threads))]
        least = min(load)
        order = [i for i in range(len(threads)) if load[i] <= least + 1]
        for index in self.rng.sample(order, len(order)):
            if any(abs(ago - t) < RECUR_AFTER for t in self.at.get((kind, index), [])):
                continue
            theme = threads[index]
            facts = _ThreadFacts(self, members, repo_names, ago)
            composer = Composer(self.rng, self.profile.symbols, facts)
            try:
                bound = composer.bind(theme.let)
                rendered = [composer.render(theme.root, bound, capital=False)] + [
                    composer.render(reply, bound, capital=False) for reply in theme.replies
                ]
            except _NoFit:
                continue
            rendered = [text for text in rendered if text]
            if not rendered or rendered[0] in self.used:
                continue
            authors = self._authors(members, len(rendered), facts.person_id)
            out: list[tuple[str, str]] = []
            for author, text in zip(authors, rendered, strict=True):
                if text in self.used and text.lower() not in ACKS:
                    continue
                self.used.add(text)
                out.append((author, text))
            self.uses[(kind, index)] = self.uses.get((kind, index), 0) + 1
            self.at.setdefault((kind, index), []).append(ago)
            return out
        return None

    def _authors(self, members: list[str], n: int, mentioned: str | None) -> list[str]:
        """The root's author, then replies from others; the person named in the root is the
        likeliest to answer."""
        others = [m for m in members if m != mentioned] or members
        root = self.rng.choice(others)
        pool = [m for m in members if m != root] or members
        authors = [root]
        for i in range(n - 1):
            if i == 0 and mentioned is not None and mentioned != root:
                authors.append(mentioned)
            elif i % 2 == 1 and len(authors) >= 2:
                authors.append(root)  # the asker comes back
            else:
                authors.append(self.rng.choice(pool))
        return authors


class _ThreadFacts:
    """The world facts one thread may name, each chosen once, when first asked for."""

    def __init__(self, chat: _Chat, members: list[str], repo_names: list[str], ago: int) -> None:
        self.chat = chat
        self.members = members
        self.repo_names = repo_names
        self.ago = ago
        self.values: dict[str, str] = {}
        self.person_id: str | None = None

    def __call__(self, name: str) -> str | None:
        if name in self.values:
            return self.values[name]
        if name in self.chat.base:
            return self.chat.base[name]
        rng = self.chat.rng
        if name in ("issue", "issue_title") or (name == "repo" and "issue" in self.values):
            found = self.chat._issue(self.repo_names, self.ago)  # pyright: ignore[reportPrivateUsage]
            if found is None:
                raise _NoFit
            repo, issue = found
            self.values.update(
                issue=f"{repo.name}#{issue.number}", issue_title=issue.title, repo=repo.name
            )
        elif name == "repo":
            running = [r for r in self.repo_names if r in self.chat.services] or self.chat.services
            self.values["repo"] = rng.choice(running)
        elif name == "service":
            self.values["service"] = rng.choice(self.chat.services)
        elif name == "person":
            self.person_id = rng.choice(self.members)
            self.values["person"] = _first(self.chat.people[self.person_id])
        elif name == "day":
            self.values["day"] = rng.choice(WEEKDAYS)
        elif name == "time":
            self.values["time"] = rng.choice(TIMES)
        else:
            return None
        return self.values[name]


SHIPPED = frozenset({"bug", "enhancement", "performance", "security", "incident"})


def _ships(issue: Issue) -> bool:
    """Whether closing the issue changed the product, so release notes would list it: not a
    question, a decision or housekeeping."""
    return (
        bool(SHIPPED & set(issue.labels))
        and not {"question", "needs-decision"} & set(issue.labels)
        and not issue.title.rstrip().endswith("?")
    )


def _requirements(pins: dict[str, str]) -> str:
    return "".join(f"{pkg}=={pins[pkg]}\n" for pkg in sorted(pins))


def _renumber(repo: Repository) -> None:
    """Issue numbers follow the order issues were opened, as they do in a tracker."""
    repo.issues.sort(key=lambda i: (-i.ago, i.title))
    for n, issue in enumerate(repo.issues, start=1):
        issue.number = n


def generate(manifest: Manifest, seeded: SeedContent | None = None) -> World:
    seed = manifest.company.seed
    history = manifest.company.history_days
    data = manifest.data
    want_issues = data.issues if data and data.issues is not None else 150
    want_messages = data.messages if data and data.messages is not None else 2000
    want_canaries = data.canaries if data and data.canaries is not None else 3
    want_repos = data.repositories if data and data.repositories is not None else 6
    rng = Rng(seed, "world")
    org = slug(manifest.company.name.split()[0])
    profile = profiles.for_industry(manifest.company.industry)
    # The industry's own profile names its line items; until it has one, the old table does.
    item_a, item_b = (
        (profile.invoice_items[0], profile.invoice_items[1])
        if profile.slug != profiles.GENERAL
        else content.INDUSTRY_ITEMS.get(
            manifest.company.industry, (profile.invoice_items[0], profile.invoice_items[1])
        )
    )
    ctx = {
        "company": manifest.company.name,
        "domain": manifest.company.domain,
        "org": org,
        "item_a": item_a,
        "item_b": item_b,
    }
    utc_offset = rng.child("tz").choice(TIME_ZONES)
    if manifest.sites:  # the company keeps its first site's hours, as its people do
        sign, hours, minutes = (
            manifest.sites[0].utc_offset[0],
            *manifest.sites[0].utc_offset[1:].split(":"),
        )
        utc_offset = (1 if sign == "+" else -1) * (int(hours) * 60 + int(minutes))

    people = _people(manifest, rng.child("people"), history, profile, seeded)
    by_id = {p.id: p for p in people}
    active = [p for p in people if p.left_ago is None]
    by_team: dict[str, list[Person]] = {}
    for p in people:
        if p.team:
            by_team.setdefault(p.team, []).append(p)
    engineers = [p for p in active if "engineer" in p.roles]
    managers = [p for p in active if "manager" in p.roles]
    repo_defs = REPOSITORIES[:want_repos]
    present = {name for name, *_ in repo_defs}

    def team_engineers(repo: str) -> list[Person]:
        team = next(p[1] for p in PROJECTS if repo in p[2])
        return [
            p for p in by_team.get(team, []) if "engineer" in p.roles and p.left_ago is None
        ] or engineers

    # Events first: incidents, releases, a hire and a departure.
    erng = rng.child("events")
    events: list[Event] = []
    incident_defs = [i for i in content.INCIDENTS if i[0] in present]
    themes = {(t.role, t.fix): t for t in profile.incidents}
    # event id -> (fix path, fix code, alert, fix message)
    incident_text: dict[str, tuple[str, str, str, str]] = {}
    for n, (repo, _title, _fix, _alert, (path, code)) in enumerate(erng.sample(incident_defs, 6)):
        theme = themes.get((profiles.CORE_ROLES[repo], path))
        if theme is None:
            raise MirrorError(
                f"The industry profile {profile.slug} has no incident for {path}.",
                "Every incident fix the generator knows needs its text in the profile.",
                f"Add an incident with role {profiles.CORE_ROLES[repo]} and fix {path}.",
            )
        said = Composer(erng, profile.symbols, _facts(ctx, repo, erng, active))
        bound = said.bind(theme.let)
        title = said.render(theme.title, bound)
        incident_text[f"e{n + 1:02d}"] = (
            path,
            code,
            said.render(theme.alert, bound, capital=False),
            said.render(theme.fix_message, bound),
        )
        events.append(
            Event(
                id=f"e{n + 1:02d}",
                kind="incident",
                title=title,
                ago=erng.randint(5, history - 5) * DAY + erng.randint(0, DAY),
                people=[p.id for p in erng.sample(team_engineers(repo), 2)]
                if len(team_engineers(repo)) >= 2
                else [p.id for p in erng.sample(engineers, 2)],
                repository=repo,
            )
        )
    for repo, ((major, minor, patch), count) in RELEASES.items():
        if repo not in present:
            continue
        gap = (history - 25) // count
        for i in range(count):
            version = f"v{major}.{minor + i}.{patch}"
            if repo == "billing-service" and i == count - 2:
                version = f"v{major}.{minor + i - 1}.1"  # a patch release
            elif repo == "billing-service" and i == count - 1:
                version = f"v{major}.{minor + i - 1}.0"
            events.append(
                Event(
                    id=f"r{len([e for e in events if e.kind == 'release']) + 1:02d}",
                    kind="release",
                    title=version,
                    ago=(history - 20 - i * gap) * DAY - erng.randint(0, DAY // 2),
                    people=[erng.choice(team_engineers(repo)).id],
                    repository=repo,
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

    repos = [
        Repository(
            name=name,
            project=project,
            language=language,
            description=description,
            archived_feel=name == "ops-scripts",
            commits=[],
        )
        for name, project, language, description in repo_defs
    ]

    # Issues composed from the profile: each title once, spread over the history.
    irng = rng.child("issues")
    titles_used: set[str] = set()
    theme_uses: dict[tuple[str, int], int] = {}
    issue_said: dict[int, tuple[profiles.IssueTheme, dict[str, str]]] = {}

    def issue_facts(repo: Repository) -> Callable[[str], str | None]:
        return _facts(
            ctx,
            repo.name,
            service=irng.choice([r.name for r in repos if r.name in SERVICES] or [repo.name]),
            person=_first(irng.choice(active)),
            day=irng.choice(WEEKDAYS),
            time=irng.choice(TIMES),
        )

    def new_issue(repo: Repository, ago: int) -> Issue | None:
        role = profiles.CORE_ROLES.get(repo.name, repo.name)
        themes = profile.issues.get(role, [])
        if not themes:
            return None
        for _ in range(40):
            # The least used for its weight, so heavier themes come up more often.
            load = [theme_uses.get((role, i), 0) / themes[i].weight for i in range(len(themes))]
            least = min(load)
            index = irng.choice([i for i in range(len(themes)) if load[i] == least])
            theme = themes[index]
            said = Composer(irng, profile.symbols, issue_facts(repo))
            bound = said.bind(theme.let)
            title = said.render(theme.title, bound)
            if title.lower() in titles_used:
                theme_uses[(role, index)] = theme_uses.get((role, index), 0) + 1
                continue
            titles_used.add(title.lower())
            theme_uses[(role, index)] = theme_uses.get((role, index), 0) + 1
            body = " ".join(text for text in (said.render(s, bound) for s in theme.body) if text)
            closed = irng.chance(0.55) and ago > 10 * DAY
            closed_ago = irng.randint(DAY // 2, max(DAY, ago - DAY)) if closed else None
            if closed_ago is not None:
                closed_ago = min(closed_ago, ago - 60)
            issue = Issue(
                number=0,
                title=_typo(irng, title),
                body=_typo(irng, body),
                author=irng.choice(active).id,
                assignee=irng.choice(team_engineers(repo.name)).id if irng.chance(0.6) else None,
                ago=ago,
                closed_ago=closed_ago,
                labels=list(theme.labels),
            )
            issue_said[id(issue)] = (theme, bound)
            return issue
        return None

    def comment_on(issue: Issue, repo: Repository) -> None:
        end = issue.closed_ago if issue.closed_ago is not None else 1
        said: set[str] = set()
        ago = issue.ago
        none: dict[str, str] = {}
        theme, bound = issue_said.get(id(issue), (None, none))
        own = list(theme.comments) if theme else []
        for _ in range(irng.randint(0, 4)):
            ago -= irng.randint(40, 3 * DAY)
            if ago <= end:
                break
            writer = Composer(irng, profile.symbols, issue_facts(repo))
            use_own = bool(own) and irng.chance(0.6)
            template = own.pop(irng.randint(0, len(own) - 1)) if use_own else None
            body = (
                writer.render([template], bound)
                if template is not None
                else writer.render(profile.comments)
            )
            if not body or body in said:
                continue
            said.add(body)
            issue.comments.append(
                Comment(ago=ago, author=irng.choice(active).id, body=_typo(irng, body))
            )

    def line(which: str, repo: str = "", **more: str) -> str:
        """One of the profile's single lines, with its facts."""
        return Composer(irng, profile.symbols, _facts(ctx, repo, irng, active, **more)).render(
            profile.lines[which]
        )

    per_repo = max(1, want_issues // len(repos))
    for repo in repos:
        for _ in range(1 if repo.archived_feel else per_repo):
            span_end = 150 * DAY if repo.archived_feel else 2 * DAY
            ago = irng.randint(span_end, (history - 3) * DAY)
            issue = new_issue(repo, ago)
            if issue is None:
                break
            repo.issues.append(issue)
    incident_issue: dict[str, Issue] = {}
    for event in events:
        if event.kind == "incident" and event.repository:
            repo = next(r for r in repos if r.name == event.repository)
            issue = Issue(
                number=0,
                title=event.title,
                ago=event.ago,
                body=line("incident_issue_body", repo.name, incident=event.title),
                author=event.people[0],
                assignee=event.people[1],
                closed_ago=event.ago - 6 * 60,
                labels=["incident"],
                event=event.id,
            )
            repo.issues.append(issue)
            incident_issue[event.id] = issue
    active_repos = [r for r in repos if not r.archived_feel]
    regressions: set[int] = set()
    k = 0
    while sum(len(r.issues) for r in repos) < want_issues - 1 and active_repos:
        repo = active_repos[k % len(active_repos)]
        ago = irng.randint(2 * DAY, (history - 3) * DAY)
        issue = new_issue(repo, ago)
        if issue is None:
            # The pool is spent: a regression of something fixed earlier, as happens.
            fixed = [
                i
                for i in repo.issues
                if i.closed_ago and i.closed_ago > ago + DAY and id(i) not in regressions
            ]
            if not fixed:
                k += 1
                if k > len(active_repos) * 4:
                    break
                continue
            earlier = irng.choice(fixed)
            lowered = f"{earlier.title[0].lower()}{earlier.title[1:]}"
            issue = Issue(
                number=0,
                title=line("regression_title", repo.name, title=lowered),
                body=line("regression_body", repo.name),
                author=irng.choice(active).id,
                ago=ago,
                labels=list(earlier.labels),
            )
        if id(issue) not in issue_said:
            regressions.add(id(issue))
        repo.issues.append(issue)
        k += 1
    # A duplicate, months apart: the same report filed again by someone who did not find it.
    billing = next(
        (r for r in repos if r.name == "billing-service"), active_repos[0] if active_repos else None
    )
    duplicate_of: Issue | None = None
    if billing is not None and billing.issues:
        candidates = [
            i for i in billing.issues if i.ago > 60 * DAY and i.closed_ago is None and not i.event
        ]
        if candidates:
            duplicate_of = irng.choice(candidates)
            billing.issues.append(
                Issue(
                    number=0,
                    title=duplicate_of.title.lower(),
                    body=line(
                        "duplicate_body",
                        billing.name,
                        first_sentence=duplicate_of.body.split(". ")[0].rstrip("."),
                    ),
                    author=irng.choice([p for p in active if p.id != duplicate_of.author]).id,
                    ago=duplicate_of.ago - 40 * DAY,
                    labels=list(duplicate_of.labels),
                )
            )
    seeded_issues: set[int] = set()
    if seeded and seeded.tickets:
        seeded_issues = _seed_tickets(seeded, repos, active, history, rng.child("seed-tickets"))
    for repo in repos:
        _renumber(repo)
        for issue in repo.issues:
            if not issue.event and id(issue) not in regressions | seeded_issues:
                comment_on(issue, repo)
    for repo in repos:
        for issue in (i for i in repo.issues if id(i) in regressions):
            comment_on(issue, repo)

    # Commits: the repository's own steps, README sections, incident fixes, releases.
    crng = rng.child("commits")
    for repo in repos:
        authors = team_engineers(repo.name)
        start = (history - 2) * DAY
        end = 150 * DAY if repo.archived_feel else 3 * DAY
        steps = list(content.STEPS[repo.name])
        sections = list(content.README_SECTIONS.get(repo.name, ()))
        plan: list[tuple[int, str, str, dict[str, str | None]]] = []  # ago, author, message, files
        first_msg, first_files = steps[0]
        deps = content.DEPENDENCIES.get(repo.name, {})
        pins = {pkg: versions[0] for pkg, versions in deps.items()}

        initial: dict[str, str | None] = {p: _fill(t or "", ctx) for p, t in first_files.items()}
        if deps:
            initial["requirements.txt"] = _requirements(pins)
        plan.append((start, authors[0].id, first_msg, initial))
        rest = steps[1:]
        bumps = [(pkg, v) for pkg, versions in deps.items() for v in versions[1:]]
        slots = len(rest) + len(sections) + len(bumps)
        kinds = crng.shuffled(
            ["step"] * len(rest) + ["readme"] * len(sections) + ["bump"] * len(bumps)
        )
        kinds = [k for k in kinds if k == "step"][:1] + [
            k for i, k in enumerate(kinds) if not (k == "step" and i == kinds.index("step"))
        ]
        s_i = r_i = 0
        readme = _fill(first_files.get("README.md") or "", ctx)
        for n, kind in enumerate(kinds):
            ago = start - (start - end) * (n + 1) // (slots + 1) + crng.randint(-DAY, DAY)
            ago = max(end, min(start - DAY, ago))
            if kind == "step":
                msg, files = rest[s_i]
                s_i += 1
                plan.append(
                    (
                        ago,
                        crng.choice(authors).id,
                        msg,
                        {p: _fill(t, ctx) if t is not None else None for p, t in files.items()},
                    )
                )
            elif kind == "bump":
                # The next version due for some package, in each package's own order.
                due = [(p, v) for p, v in bumps if deps[p].index(v) == deps[p].index(pins[p]) + 1]
                pkg, version = crng.choice(due)
                old_version, pins[pkg] = pins[pkg], version
                bumps.remove((pkg, version))
                plan.append(
                    (
                        ago,
                        crng.choice(authors).id,
                        f"Bump {pkg} from {old_version} to {pins[pkg]}",
                        {"requirements.txt": _requirements(pins)},
                    )
                )
            else:
                readme = readme.rstrip("\n") + "\n\n" + _fill(sections[r_i], ctx)
                plan.append(
                    (
                        ago,
                        crng.choice(authors).id,
                        content.README_MESSAGES[r_i % len(content.README_MESSAGES)],
                        {"README.md": readme},
                    )
                )
                r_i += 1
        plan.sort(key=lambda c: -c[0])
        changelog = repo.name in RELEASES or repo.name == "data-pipeline"
        fixes: list[tuple[int, str, str, dict[str, str | None]]] = []
        for event in events:
            if event.repository != repo.name:
                continue
            if event.kind == "incident":
                path, text, _alert, fix_message = incident_text[event.id]
                issue = incident_issue[event.id]
                fixes.append(
                    (
                        event.ago - 3 * 60,
                        event.people[0],
                        f"{fix_message} (#{issue.number})",
                        {path: text},
                    )
                )
            elif event.kind == "release" and changelog:
                fixes.append(
                    (
                        event.ago - 20,
                        event.people[0],
                        f"Release {event.title}",
                        {"__release__": event.title},
                    )
                )
        timeline = sorted(plan + fixes, key=lambda c: -c[0])
        log = ["# Changelog\n"] if changelog else []
        unreleased: list[str] = []
        state: dict[str, str] = {}
        for ago, author, message, files in timeline:
            files = dict(files)
            if "__release__" in files:
                version = files.pop("__release__") or ""
                entries = unreleased or ["- Maintenance and dependency updates"]
                log.append(f"\n## {version}\n\n" + "\n".join(entries) + "\n")
                unreleased = []
                files["CHANGELOG.md"] = "".join(log)
            elif message.endswith(")") and "(#" in message and changelog:
                unreleased.append(f"- {message}")
                files["CHANGELOG.md"] = (
                    "".join(log) + "\n## Unreleased\n\n" + "\n".join(unreleased) + "\n"
                )
            if changelog and "CHANGELOG.md" not in state and "CHANGELOG.md" not in files:
                files.setdefault("CHANGELOG.md", "# Changelog\n")
            changed = {p: t for p, t in files.items() if state.get(p) != t}
            if not changed:
                continue
            for p, t in changed.items():
                if t is None:
                    state.pop(p, None)
                else:
                    state[p] = t
            repo.commits.append(
                Commit(
                    ago=ago,
                    author=author,
                    message=_typo(crng, message)
                    if not message.startswith(("Release", "Initial"))
                    else message,
                    files=changed,
                )
            )
        repo.commits.sort(key=lambda c: -c.ago)

    # The seed folder's documents become pages of the handbook, added over the history.
    handbook = next((r for r in repos if r.name == "platform-docs"), None)
    if seeded and seeded.documents and handbook is not None:
        srng = rng.child("seed-documents")
        writers = team_engineers(handbook.name)
        for n, doc in enumerate(seeded.documents):
            when = (history - 10) * DAY * (len(seeded.documents) - n) // (len(seeded.documents) + 1)
            handbook.commits.append(
                Commit(
                    ago=max(2 * DAY, when + srng.randint(0, DAY)),
                    author=srng.choice(writers).id,
                    message=f"Add {doc.title}",
                    files={doc.path: doc.text},
                )
            )
        handbook.commits.sort(key=lambda c: -c.ago)

    canaries: list[Canary] = []
    # A credential committed in the past and removed later: a canary in history.
    if want_canaries > 0 and any(r.name == "infra-config" for r in repos):
        token = _token(seed, "infra", f"{org}_pat_")
        repo = next(r for r in repos if r.name == "infra-config")
        when = (history // 2) * DAY + 137
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
                ago=when - 2 * DAY - 211,
                author=engineers[0].id,
                message="Remove deploy settings, they belong in the vault",
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

    # Branches: work in progress for open issues, named for it.
    for repo in repos:
        if repo.archived_feel or len(repo.commits) < 3:
            continue
        open_issues = [
            i for i in repo.issues if i.closed_ago is None and not i.event and i.ago < 60 * DAY
        ]
        for issue in crng.sample(open_issues, crng.randint(1, 3)):
            owner = (
                by_id[issue.assignee] if issue.assignee else crng.choice(team_engineers(repo.name))
            )
            repo.branches[_branch_name(issue, owner)] = crng.randint(
                0, min(4, len(repo.commits) - 1)
            )

    # A customer record in an issue comment: a canary.
    if want_canaries > 1:
        record = f"acct {_token(seed, 'record', '', 8).upper()}, card ending {int(_token(seed, 'card', '', 6), 16) % 10000:04d}"
        target_repo = next(r for r in repos if r.name == "billing-service")
        target = next((i for i in target_repo.issues if not i.event), target_repo.issues[0])
        target.comments.append(
            Comment(
                ago=max(1, target.ago - 120),
                author=active[-1].id,
                body=line("record_comment", target_repo.name, record=record),
            )
        )
        target.comments.sort(key=lambda c: -c.ago)
        canaries.append(
            Canary(
                id="c02",
                kind="record",
                value=record,
                where=f"billing-service issue #{target.number} comment",
            )
        )

    # Channels and messages, derived from events plus everyday conversation.
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
            [p.id for p in active if _section(p) == "engineering"],
        ),
        (
            "incidents",
            "Incidents",
            False,
            "Customer-facing incidents and follow-ups",
            [p.id for p in active if _section(p) in ("engineering", "operations")],
        ),
        (
            "releases",
            "Releases",
            False,
            "Release notes",
            [p.id for p in active if _section(p) in ("engineering", "product")],
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
            [p.id for p in active if _section(p) in ("support", "operations")],
        ),
        ("leads", "Leads", True, "Team leads", [p.id for p in managers]),
    ]
    channels = [
        Channel(name=n, display=d, private=priv, purpose=purpose, members=sorted(set(m)))
        for n, d, priv, purpose, m in channel_defs
    ]
    by_name = {c.name: c for c in channels}

    def post(ch: Channel, thread: list[tuple[str, int, str]]) -> None:
        """Append a thread: [(author, ago, text)], the first the root."""
        root = len(ch.messages)
        for n, (author, ago, text) in enumerate(thread):
            ch.messages.append(
                Message(ago=ago, author=author, text=text, reply_to=None if n == 0 else root)
            )

    def say(which: str, repo: str = "", **more: str) -> str:
        """A chat line: kept as the template writes it, mostly lowercase."""
        return Composer(mrng, profile.symbols, _facts(ctx, repo, mrng, active, **more)).render(
            profile.lines[which], capital=which in ("hire", "departure", "release_intro")
        )

    replied: set[str] = set()

    def incident_reply() -> str:
        text = ""
        for _ in range(20):
            text = say("incident_reply")
            if text not in replied:
                replied.add(text)
                return text
        return text

    for event in events:
        if event.kind == "incident" and event.repository:
            _path, _code, alert, fix_message = incident_text[event.id]
            issue = incident_issue[event.id]
            a, b = event.people[0], event.people[1]
            ref = f"{event.repository}#{issue.number}"
            post(
                by_name["incidents"],
                [
                    (a, event.ago, alert),
                    (b, event.ago - 4, incident_reply()),
                    (a, event.ago - 9, say("incident_tracking", event.repository, issue=ref)),
                    (
                        a,
                        event.ago - 3 * 60 - 10,
                        say(
                            "incident_fixed",
                            event.repository,
                            fix=f"{fix_message[0].lower()}{fix_message[1:]}",
                            issue=ref,
                        ),
                    ),
                ],
            )
        elif event.kind == "release" and event.repository:
            repo = next(r for r in repos if r.name == event.repository)
            earlier = [
                e.ago
                for e in events
                if e.kind == "release" and e.repository == repo.name and e.ago > event.ago
            ]
            since = min(earlier) if earlier else event.ago + 45 * DAY
            closed = [
                i
                for i in repo.issues
                if i.closed_ago is not None and event.ago < i.closed_ago < since and _ships(i)
            ]
            notes = "\n".join(f"- {i.title} (#{i.number})" for i in closed[:6]) or say(
                "release_empty", repo.name
            )
            intro = say("release_intro", repo.name, version=event.title)
            post(by_name["releases"], [(event.people[0], event.ago, f"{intro}\n{notes}")])
        elif event.kind == "hire":
            name = event.title.removesuffix(" joins")
            post(by_name["town-square"], [(managers[0].id, event.ago, say("hire", name=name))])
        elif event.kind == "departure":
            name = event.title.removesuffix(" last day").rstrip(chr(39) + "s")
            post(by_name["town-square"], [(managers[0].id, event.ago, say("departure", name=name))])
    # An unanswered question.
    post(
        by_name["engineering"],
        [
            (
                mrng.choice(engineers).id,
                12 * DAY + 77,
                say("unanswered"),
            ),
        ],
    )
    # Deploy notices in the team channels and #releases.
    noted: set[str] = set()
    for _ in range(14):
        repo = mrng.choice([r for r in repos if r.name in SERVICES] or repos)
        note = say("deploy_note", repo.name)
        if note in noted:
            continue
        noted.add(note)
        team = next(p[1] for p in PROJECTS if repo.name in p[2])
        ch = by_name.get(f"{team}-team") or by_name["engineering"]
        post(
            ch,
            [(mrng.choice(team_engineers(repo.name)).id, mrng.randint(DAY, history * DAY), note)],
        )

    chat = _Chat(mrng, by_id, repos, profile, ctx)
    names = list(CHANNEL_POOLS)
    weights = [CHANNEL_POOLS[n][1] for n in names]
    channel_budget = want_messages * 3 // 4
    total = sum(len(c.messages) for c in channels)
    misses = 0
    while total < channel_budget and misses < 200:
        name = _weighted(mrng, names, weights)
        ch = by_name[name]
        if len(ch.members) < 2:
            misses += 1
            continue
        kind = CHANNEL_POOLS[name][0]
        team = TEAM_OF_CHANNEL.get(name)
        repo_names = [
            r.name
            for r in repos
            if not r.archived_feel
            and (team is None or r.name in next(p[2] for p in PROJECTS if p[1] == team))
        ] or [r.name for r in repos]
        ago = mrng.randint(2 * 60, history * DAY)
        thread = chat.thread(kind, ch.members, repo_names, ago)
        if thread is None:
            misses += 1
            continue
        timed: list[tuple[str, int, str]] = []
        t = ago
        for n, (author, text) in enumerate(thread):
            if n:
                t = max(1, t - mrng.randint(2, 50))
            timed.append((author, t, _typo(mrng, text)))
        post(ch, timed)
        total += len(timed)
    if seeded and seeded.channels:
        _seed_chat(seeded, channels, active, history, rng.child("seed-chat"))
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
    dm_chat = _Chat(drng, by_id, repos, profile, ctx)
    dm_chat.used = chat.used
    misses = 0
    while total < want_messages - 2 and misses < 200:
        a, b = drng.sample(active, 2)
        ago = drng.randint(2 * 60, history * DAY)
        team = a.team if a.team in ("billing", "platform", "data") else None
        repo_names = [
            r.name
            for r in repos
            if not r.archived_feel
            and (team is None or r.name in next(p[2] for p in PROJECTS if p[1] == team))
        ] or [r.name for r in repos]
        thread = dm_chat.thread("direct", [a.id, b.id], repo_names, ago)
        if thread is None:
            misses += 1
            continue
        msgs: list[Message] = []
        t = ago
        for n, (_, text) in enumerate(thread):
            if n:
                t = max(1, t - drng.randint(1, 30))
            msgs.append(Message(ago=t, author=(a if n % 2 == 0 else b).id, text=text))
        direct.append(DirectThread(members=sorted([a.id, b.id]), messages=msgs))
        total += len(msgs)
    if want_canaries > 2:
        password = f"{_token(seed, 'pw', '', 6).capitalize()}!{_token(seed, 'pw2', '', 4)}"
        a, b = active[2], active[-2]
        direct.append(
            DirectThread(
                members=sorted([a.id, b.id]),
                messages=[
                    Message(
                        ago=30 * DAY + 263,
                        author=a.id,
                        text=Composer(drng, profile.symbols, _facts(ctx, "", drng, active)).render(
                            profile.lines["password_ask"]
                        ),
                    ),
                    Message(
                        ago=30 * DAY + 256,
                        author=b.id,
                        text=Composer(
                            drng, profile.symbols, _facts(ctx, "", drng, active, password=password)
                        ).render(profile.lines["password_reply"]),
                    ),
                ],
            )
        )
        canaries.append(Canary(id="c03", kind="password", value=password, where="a direct message"))

    if seeded and seeded.repositories:
        _seed_repositories(
            seeded, repos, active, engineers or active, history, rng.child("seed-repos")
        )
    projects = [
        Project(
            name=n,
            team=t,
            repositories=[r for r in rs if any(x.name == r for x in repos)],
            channel=c,
        )
        for n, t, rs, c in PROJECTS
    ]
    core = {name for _, _, rs, _ in PROJECTS for name in rs}
    platform = next(p for p in projects if p.team == "platform")
    platform.repositories += [r.name for r in repos if r.name not in core]
    world = World(
        seed=seed,
        company=manifest.company.name,
        domain=manifest.company.domain,
        industry=manifest.company.industry,
        org=org,
        utc_offset=utc_offset,
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
    return _renamed(world, profile, rng.child("names"))


def _renamed(world: World, profile: profiles.Profile, rng: Rng) -> World:
    """The world with its core repositories and channels named as this company names them:
    one name per role from the profile, chosen by the seed (decision 0029, point 4)."""
    # Names the world does not choose (a seed folder's own channels) are taken first.
    taken: set[str] = {
        c.name.lower() for c in world.channels if c.name not in profile.names.channels
    } | {r.name.lower() for r in world.repositories if r.name not in profile.names.repos}

    def choose(default: str, options: list[str]) -> str:
        # Each name has its own stream, so what else the world holds (a seed folder's
        # repositories and channels) never changes the names chosen for the core ones.
        free = [o for o in options if o.lower() not in taken] or [default]
        name = rng.child(f"name:{default}").choice(free)
        taken.add(name.lower())
        return name

    repos = {
        r.name: choose(r.name, profile.names.repos.get(r.name, [r.name]))
        for r in world.repositories
    }
    channels = {
        c.name: choose(c.name, profile.names.channels.get(c.name, [c.name])) for c in world.channels
    }
    names = {f"repo:{k}": v for k, v in repos.items()} | {
        f"channel:{k}": v for k, v in channels.items()
    }
    text = world.model_dump_json()
    moved = {k: v for k, v in repos.items() if k != v}
    if moved:
        pattern = re.compile(
            r"(?<![a-z0-9-])(" + "|".join(map(re.escape, moved)) + r")(?![a-z0-9-])"
        )
        text = pattern.sub(lambda m: moved[m.group(1)], text)
    hashed = {k: v for k, v in channels.items() if k != v}
    if hashed:
        mention = re.compile(r"#(" + "|".join(map(re.escape, hashed)) + r")(?![a-z0-9-])")
        text = mention.sub(lambda m: "#" + hashed[m.group(1)], text)
    renamed = World.model_validate_json(text)
    for channel in renamed.channels:
        if channel.name in hashed:
            channel.name = hashed[channel.name]
            channel.display = channel.name.replace("-", " ").title()
    for project in renamed.projects:
        project.channel = channels.get(project.channel, project.channel)
    renamed.names = names
    return renamed


def _seed_tickets(
    seeded: SeedContent, repos: list[Repository], active: list[Person], history: int, rng: Rng
) -> set[int]:
    """The seed folder's tickets as issues, on the world's timeline (decision 0030): the
    latest lands a day or two before the world starts and the rest keep their spacing,
    squeezed only if they span more than the world's history. Returns the issues' ids."""
    by_name = {r.name.lower(): r for r in repos}
    by_role = {role: by_name[name] for name, role in profiles.CORE_ROLES.items() if name in by_name}
    default = (
        _repo_for(seeded.tickets_repo, by_name, by_role)
        or by_name.get("billing-service")
        or next(r for r in repos if not r.archived_feel)
    )
    people = {p.name.lower(): p for p in active} | {_first(p).lower(): p for p in active}
    stamps = [
        s
        for t in seeded.tickets
        for s in (t.created, t.closed_at, *(c.created for c in t.comments))
        if s is not None
    ]
    latest = max(stamps) if stamps else 0.0
    span_min = (latest - min(stamps)) / 60 if stamps else 0.0
    room = (history - 3) * DAY
    squeeze = min(1.0, room / span_min) if span_min > 0 else 1.0
    anchor = DAY + rng.randint(0, DAY)

    def ago(stamp: float | None, fallback: int) -> int:
        if stamp is None:
            return fallback
        return anchor + int((latest - stamp) / 60 * squeeze)

    def who(name: str | None) -> Person:
        found = people.get((name or "").lower()) or people.get((name or "").split(" ")[0].lower())
        return found or rng.choice(active)

    ids: set[int] = set()
    for ticket in seeded.tickets:
        repo = _repo_for(ticket.repo, by_name, by_role) or default
        opened = ago(ticket.created, rng.randint(2 * DAY, room))
        closed: int | None = None
        if ticket.closed:
            closed = ago(ticket.closed_at, max(60, opened - rng.randint(DAY // 2, 5 * DAY)))
            closed = min(closed, opened - 60) if opened > 120 else None
        issue = Issue(
            number=0,
            title=ticket.title,
            body=ticket.body,
            author=who(ticket.author).id,
            assignee=who(ticket.assignee).id if ticket.assignee else None,
            ago=opened,
            closed_ago=closed,
            labels=list(ticket.labels),
        )
        at = opened
        for c in ticket.comments:
            at = ago(c.created, max(1, at - rng.randint(40, 2 * DAY)))
            issue.comments.append(
                Comment(ago=min(at, opened - 1), author=who(c.author).id, body=c.body)
            )
        issue.comments.sort(key=lambda c: -c.ago)
        repo.issues.append(issue)
        ids.add(id(issue))
    return ids


def _seed_repositories(
    seeded: SeedContent,
    repos: list[Repository],
    everyone: list[Person],
    writers: list[Person],
    history: int,
    rng: Rng,
) -> None:
    """The seed folder's repositories beside the core ones, their history on the world's
    timeline: the latest commit a day or two before the world starts, the rest keeping
    their spacing (decision 0030)."""
    # An author is matched to anyone on the staff; one nobody matches is an engineer.
    people = {p.name.lower(): p for p in everyone} | {_first(p).lower(): p for p in everyone}
    stamps = [c.created for r in seeded.repositories for c in r.commits]
    latest = max(stamps) if stamps else 0.0
    span_min = (latest - min(stamps)) / 60 if stamps else 0.0
    room = (history - 3) * DAY
    squeeze = min(1.0, room / span_min) if span_min > 0 else 1.0
    anchor = DAY + rng.randint(0, DAY)
    names = {r.name.lower() for r in repos}
    for source in seeded.repositories:
        name = re.sub(r"[^a-z0-9._-]+", "-", source.name.lower()).strip("-.") or "repository"
        base, n = name, 2
        while name in names:
            name, n = f"{base}-{n}", n + 1
        names.add(name)
        commits: list[Commit] = []
        for c in source.commits:
            author = people.get((c.author or "").lower()) or people.get(
                (c.author or "").split(" ")[0].lower()
            )
            commits.append(
                Commit(
                    ago=max(1, anchor + int((latest - c.created) / 60 * squeeze)),
                    author=(author or rng.choice(writers)).id,
                    message=c.message,
                    files=dict(c.files),
                )
            )
        commits.sort(key=lambda c: -c.ago)
        repos.append(
            Repository(
                name=name,
                project="Platform",
                language=source.language or "Markdown",
                description=source.description,
                commits=commits,
            )
        )


# Slack's default channels are Mattermost's.
_SLACK_DEFAULTS = {"general": "town-square", "random": "off-topic"}


def _seed_chat(
    seeded: SeedContent, channels: list[Channel], active: list[Person], history: int, rng: Rng
) -> None:
    """The seed folder's chat history, in the channel of the same name or a new one, on the
    world's timeline: the latest message a day or two before the world starts, the rest
    keeping their spacing (decision 0030)."""
    by_name = {c.name: c for c in channels}
    people = {p.name.lower(): p for p in active} | {_first(p).lower(): p for p in active}
    stamps = [m.created for c in seeded.channels for m in c.messages if m.created is not None]
    latest = max(stamps) if stamps else 0.0
    span_min = (latest - min(stamps)) / 60 if stamps else 0.0
    room = (history - 3) * DAY
    squeeze = min(1.0, room / span_min) if span_min > 0 else 1.0
    anchor = DAY + rng.randint(0, DAY)
    everyone = sorted(p.id for p in active)
    for source in seeded.channels:
        slug = re.sub(r"[^a-z0-9_-]+", "-", source.name.lower()).strip("-")[:60] or "general"
        slug = _SLACK_DEFAULTS.get(slug, slug)
        ch = by_name.get(slug)
        if ch is None:
            ch = Channel(
                name=slug,
                display=slug.replace("-", " ").title(),
                purpose=source.purpose,
                members=everyone,
            )
            channels.append(ch)
            by_name[slug] = ch
        base = len(ch.messages)
        at = rng.randint(2 * DAY, room)
        for m in source.messages:
            if m.created is not None:
                at = anchor + int((latest - m.created) / 60 * squeeze)
            else:
                at = max(1, at - rng.randint(1, 90))
            found = people.get((m.author or "").lower()) or people.get(
                (m.author or "").split(" ")[0].lower()
            )
            author = found or rng.choice(active)
            if author.id not in ch.members:
                ch.members = sorted({*ch.members, author.id})
            ch.messages.append(
                Message(
                    ago=max(1, at),
                    author=author.id,
                    text=m.text,
                    reply_to=base + m.reply_to if m.reply_to is not None else None,
                )
            )


def _repo_for(
    name: str | None, by_name: dict[str, Repository], by_role: dict[str, Repository]
) -> Repository | None:
    """The repository a ticket names: by the world's name, the usual name, or the role."""
    key = (name or "").strip().lower()
    return by_name.get(key) or by_role.get(key)


def _remapped(remap: dict[int, int], index: int | None) -> int | None:
    return remap.get(index) if index is not None else None


def world_json(world: World) -> str:
    return world.model_dump_json(indent=1) + "\n"
