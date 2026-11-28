# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The seed folder: read only it, never run or follow anything, drop secrets, list personal
data, and build the world from what is left (decision 0030)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from mirrordimensions.config.manifest import Manifest
from mirrordimensions.errors import MirrorError
from mirrordimensions.project import Project
from mirrordimensions.seed import reader
from mirrordimensions.seed.content import read_seed
from mirrordimensions.seed.detect import personal_in, secret_on
from mirrordimensions.service import seed as seed_svc
from mirrordimensions.service.project import init_project
from mirrordimensions.world import publictext
from mirrordimensions.world.generate import generate

DOMAIN = "halden-health.com"


def _folder(tmp_path: Path) -> Path:
    root = tmp_path / "seed"
    (root / "hr").mkdir(parents=True)
    (root / "runbooks").mkdir()
    (root / "hr" / "staff.csv").write_text(
        "Full Name,Job Title,Department\n"
        "Rosa Delgado,Head of Claims Engineering,Engineering\n"
        "Tomasz Wierzbicki,Integration Engineer,Engineering\n",
        encoding="utf-8",
    )
    (root / "runbooks" / "claims-backlog.md").write_text(
        "# Clearing the claims backlog\n\nCheck the clearinghouse queue first.\n"
        "DB_PASSWORD=Sup3rS3cretValue99\nEscalate after two hours.\n",
        encoding="utf-8",
    )
    return root


def _can_link(tmp_path: Path) -> bool:
    try:
        (tmp_path / "probe").symlink_to(tmp_path)
    except (OSError, NotImplementedError):
        return False
    (tmp_path / "probe").unlink()
    return True


def test_links_out_of_the_folder_are_never_followed(tmp_path: Path) -> None:
    if not _can_link(tmp_path):
        pytest.skip("this host cannot make symbolic links without privileges")
    root = _folder(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.md").write_text("# Private\n", encoding="utf-8")
    (root / "linked-dir").symlink_to(outside)
    (root / "linked.md").symlink_to(outside / "private.md")
    found = reader.read_folder(root)
    assert all("private" not in f.text.lower() for f in found.files)
    assert {p for p, _ in found.skipped} >= {"linked-dir", "linked.md"}
    with pytest.raises(MirrorError, match="is a link"):
        reader.read_folder(root / "linked-dir")


def test_a_repository_is_one_item_and_hooks_are_never_read(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    repo = root / "claims-service"
    (repo / ".git" / "hooks").mkdir(parents=True)
    (repo / ".git" / "hooks" / "post-checkout").write_text("#!/bin/sh\nexit 1\n", "utf-8")
    (repo / "README.md").write_text("# Claims service\n", encoding="utf-8")
    found = reader.read_folder(root)
    assert "claims-service" in found.repositories
    assert not any(f.path.startswith("claims-service/") for f in found.files)


def test_big_files_and_other_kinds_are_left_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _folder(tmp_path)
    (root / "big.md").write_text("x" * 5000, encoding="utf-8")
    (root / "photo.png").write_bytes(b"\x89PNG")
    (root / "latin1.txt").write_bytes("caf\xe9".encode("latin-1"))
    monkeypatch.setattr(reader, "MAX_FILE_BYTES", 1000)
    skipped = dict(reader.read_folder(root).skipped)
    assert "larger than" in skipped["big.md"]
    assert "not a kind" in skipped["photo.png"]
    assert "UTF-8" in skipped["latin1.txt"]


def test_secrets_are_dropped_whole_lines_and_counted(tmp_path: Path) -> None:
    content, review = read_seed(_folder(tmp_path), DOMAIN)
    page = next(d for d in content.documents if d.title == "Clearing the claims backlog")
    assert "Sup3rS3cret" not in page.text and "DB_PASSWORD" not in page.text
    assert "Escalate after two hours." in page.text
    assert [(d.path, d.lines) for d in review.secrets_dropped] == [
        ("runbooks/claims-backlog.md", 1)
    ]
    for line in (
        "token = ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "aws_access_key_id = " + "AKIA" + "ABCDEFGHIJKLMNOP",  # built here: no key in the file
        "postgres://app:hunter2@db.internal/claims",
        "stripeSecretKey: 'abc123xyz9'",
    ):
        assert secret_on(line), line
    assert not secret_on("The token expired yesterday, so we rotated it.")


def test_personal_data_is_listed_by_file_and_line_never_silently_kept() -> None:
    text = (
        "Rosa, rosa@halden-health.com\n"
        "Vendor desk desk@vendorcorp.example.net or 555-210-3344.\n"
        "card 4111 1111 1111 1111, ssn 123-45-6789\n"
        "Ship to 12 Baker Street\n"
        "Order 2024-11-03 for 4417 units\n"
    )
    kinds = [(p.line, p.kind) for p in personal_in("notes.md", text, DOMAIN)]
    assert (1, "email address") not in kinds  # the company's own address
    assert {(2, "email address"), (2, "phone number"), (3, "card number")} <= set(kinds)
    assert {(3, "national id"), (4, "street address")} <= set(kinds)
    assert not [k for k in kinds if k[0] == 5]  # dates and quantities are not people


def test_people_documents_and_seed_yaml(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    (root / "people.csv").write_text(
        "first_name,last_name,team\nIkenna,Obi,Claims\nMei,Lin,Data\n", encoding="utf-8"
    )
    (root / "tickets.csv").write_text("Summary,Status\nBatch stalls,Open\n", encoding="utf-8")
    (root / "draft.md").write_text("# Draft\n", encoding="utf-8")
    (root / "seed.yaml").write_text("leave_out: [draft.md]\n", encoding="utf-8")
    content, review = read_seed(root, DOMAIN)
    # Files are read folder by folder, in order: the top level first, then hr/.
    assert [p.name for p in content.people] == [
        "Ikenna Obi",
        "Mei Lin",
        "Rosa Delgado",
        "Tomasz Wierzbicki",
    ]
    assert content.people[2].title == "Head of Claims Engineering"
    assert [d.path for d in content.documents] == ["docs/runbooks/claims-backlog.md"]
    assert ("draft.md", "left out by seed.yaml") in review.not_read
    assert ("tickets.csv", "tickets") in {(i.path, i.kind) for i in review.items}
    assert [t.title for t in content.tickets] == ["Batch stalls"]


def test_the_world_is_built_from_the_folder_and_the_agent_cannot_see_where(
    tmp_path: Path,
) -> None:
    root = init_project(tmp_path / "halden", seed=48213).root
    project = Project(root=root)
    folder = _folder(tmp_path)
    (folder / "contacts.md").write_text(
        "# Contacts\n\nVendor: desk@vendorcorp.example.net\n", "utf-8"
    )
    with pytest.raises(MirrorError, match="personal data"):
        seed_svc.seed_world(project, folder)
    assert seed_svc.load_content(project) is None  # nothing is used until it is accepted
    review = seed_svc.seed_world(project, folder, accept_personal=True)
    assert review.personal_accepted
    if os.name != "nt":  # owner-only on POSIX hosts
        assert (project.state_dir / "seed" / "content.json").stat().st_mode & 0o077 == 0
    loaded = YAML(typ="safe").load(project.manifest_path.read_text("utf-8"))  # pyright: ignore[reportUnknownMemberType]
    manifest = Manifest.model_validate(loaded)
    world = generate(manifest, seed_svc.load_content(project))
    assert [p.name for p in world.people[:2]] == ["Rosa Delgado", "Tomasz Wierzbicki"]
    assert world.people[0].title == "Head of Claims Engineering"
    pages = {path for r in world.repositories for c in r.commits for path in c.files}
    assert "docs/runbooks/claims-backlog.md" in pages
    text = world.model_dump_json()
    assert str(folder) not in text and "seed" not in {r.name for r in world.repositories}
    # The user's own text is not counted as public text, and is not the package's anyway.
    skip = seed_svc.seeded_texts(project)
    assert skip and publictext.check(world, skip=skip).total <= publictext.check(world).total


def test_a_new_seed_copy_rebuilds_the_company(tmp_path: Path) -> None:
    from mirrordimensions.service.worlddef import first_stage_affected, project_hash

    root = init_project(tmp_path / "halden", seed=48213).root
    project = Project(root=root)
    loaded = YAML(typ="safe").load(project.manifest_path.read_text("utf-8"))  # pyright: ignore[reportUnknownMemberType]
    manifest = Manifest.model_validate(loaded)
    before = project_hash(project, manifest)
    seed_svc.seed_world(project, _folder(tmp_path))
    after = project_hash(project, manifest)
    assert first_stage_affected(before, after) == 1  # the company is generated again
    assert first_stage_affected(after, project_hash(project, manifest)) == 9  # and is stable


def _json(value: object) -> str:
    import json

    return json.dumps(value)


def test_tickets_from_a_sheet_and_from_jira_github_and_linear_exports(tmp_path: Path) -> None:
    root = tmp_path / "seed"
    root.mkdir()
    (root / "sheet.csv").write_text(
        "Summary,Status,Priority,Reporter,Comment\n"
        "Claims batch stalls overnight,Open,High,Rosa Delgado,Seen again on Monday\n"
        "Remit file rejected,Done,Low,,\n",
        encoding="utf-8",
    )
    jira = {
        "issues": [
            {
                "key": "CLM-12",
                "fields": {
                    "summary": "Eligibility check times out",
                    "description": "Started after the payer change.\napi_key: sk-abcdefghijklmnopqrstuvwxyz",
                    "status": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}},
                    "labels": ["eligibility"],
                    "issuetype": {"name": "Bug"},
                    "created": "2025-03-04T10:15:00.000+0000",
                    "comment": {
                        "comments": [
                            {"body": "Looking", "author": {"displayName": "Tomasz Wierzbicki"}}
                        ]
                    },
                },
            }
        ]
    }
    (root / "jira.json").write_text(_json(jira), encoding="utf-8")
    github = [
        {
            "title": "Portal shows stale balance",
            "body": "Refresh fixes it.",
            "state": "closed",
            "labels": [{"name": "bug"}],
            "created_at": "2025-02-01T09:00:00Z",
            "closed_at": "2025-02-03T09:00:00Z",
        }
    ]
    (root / "github.json").write_text(_json(github), encoding="utf-8")
    linear = {
        "nodes": [
            {"title": "Add payer to the remit report", "description": "", "state": {"name": "Todo"}}
        ]
    }
    (root / "linear.json").write_text(_json(linear), encoding="utf-8")
    content, review = read_seed(root, DOMAIN)
    titles = {t.title: t for t in content.tickets}
    assert set(titles) == {
        "Claims batch stalls overnight",
        "Remit file rejected",
        "Eligibility check times out",
        "Portal shows stale balance",
        "Add payer to the remit report",
    }
    assert (
        titles["Remit file rejected"].closed and not titles["Claims batch stalls overnight"].closed
    )
    assert titles["Claims batch stalls overnight"].comments[0].body == "Seen again on Monday"
    jira_ticket = titles["Eligibility check times out"]
    assert "sk-" not in jira_ticket.body and "payer change" in jira_ticket.body  # value by value
    assert jira_ticket.labels == ["eligibility", "bug"] and jira_ticket.created is not None
    assert titles["Portal shows stale balance"].closed
    assert {i.kind for i in review.items} == {"tickets"}


def test_tickets_land_on_the_worlds_timeline_keeping_their_spacing(tmp_path: Path) -> None:
    root = init_project(tmp_path / "halden", seed=48213).root
    project = Project(root=root)
    folder = _folder(tmp_path)
    tickets = [
        {
            "title": "First report of the remit gap",
            "created_at": "2023-01-10T09:00:00Z",
            "state": "open",
            "repository": "data-pipeline",
        },
        {
            "title": "Second report of the remit gap",
            "created_at": "2023-01-20T09:00:00Z",
            "state": "open",
        },
    ]
    (folder / "tickets.json").write_text(_json(tickets), encoding="utf-8")
    (folder / "seed.yaml").write_text("tickets_repo: infra\n", encoding="utf-8")
    seed_svc.seed_world(project, folder)
    loaded = YAML(typ="safe").load(project.manifest_path.read_text("utf-8"))  # pyright: ignore[reportUnknownMemberType]
    world = generate(Manifest.model_validate(loaded), seed_svc.load_content(project))
    names = {r.name: r for r in world.repositories}
    from mirrordimensions.world import naming

    data = names[naming.repos(world)["data-pipeline"]]
    infra = names[naming.repos(world)["infra-config"]]
    first = next(i for i in data.issues if i.title == "First report of the remit gap")
    second = next(i for i in infra.issues if i.title == "Second report of the remit gap")
    day = 24 * 60
    assert day <= second.ago <= 2 * day  # the latest, a day or two before the world starts
    assert first.ago - second.ago == 10 * day  # the spacing is kept
    assert (
        first.number < next(i.number for i in data.issues if i.ago < first.ago)
        if any(i.ago < first.ago for i in data.issues)
        else True
    )  # numbers follow time


def _slack(root: Path) -> None:
    export = root / "slack"
    (export / "claims-ops").mkdir(parents=True)
    (export / "incidents").mkdir()
    (export / "users.json").write_text(
        _json(
            [
                {"id": "U1", "name": "rosa", "profile": {"real_name": "Rosa Delgado"}},
                {"id": "U2", "name": "tomasz", "profile": {"real_name": "Tomasz Wierzbicki"}},
            ]
        ),
        encoding="utf-8",
    )
    (export / "channels.json").write_text(
        _json(
            [
                {"name": "claims-ops", "purpose": {"value": "Claims operations"}},
                {"name": "incidents"},
                {"name": "general"},
            ]
        ),
        encoding="utf-8",
    )
    (export / "claims-ops" / "2025-03-03.json").write_text(
        _json(
            [
                {
                    "type": "message",
                    "user": "U1",
                    "text": "<@U2> can you check the remit queue?",
                    "ts": "1741000000.000100",
                },
                {
                    "type": "message",
                    "user": "U2",
                    "text": "on it, see <https://wiki.example/q|the queue page>",
                    "ts": "1741000300.000200",
                    "thread_ts": "1741000000.000100",
                },
                {
                    "type": "message",
                    "subtype": "channel_join",
                    "user": "U2",
                    "text": "joined",
                    "ts": "1741000400.0",
                },
            ]
        ),
        encoding="utf-8",
    )
    (export / "incidents" / "2025-03-04.json").write_text(
        _json(
            [
                {
                    "type": "message",
                    "user": "U2",
                    "text": "eligibility calls timing out again",
                    "ts": "1741090000.0",
                }
            ]
        ),
        encoding="utf-8",
    )


def test_a_slack_export_and_a_mattermost_export_become_channels(tmp_path: Path) -> None:
    root = tmp_path / "seed"
    root.mkdir()
    _slack(root)
    (root / "mattermost.jsonl").write_text(
        "\n".join(
            _json(r)
            for r in [
                {
                    "type": "user",
                    "user": {"username": "amara", "first_name": "Amara", "last_name": "Osei"},
                },
                {"type": "channel", "channel": {"name": "eligibility", "purpose": "Payer checks"}},
                {
                    "type": "post",
                    "post": {
                        "channel": "eligibility",
                        "user": "amara",
                        "message": "payer B is back up",
                        "create_at": 1741100000000,
                        "replies": [
                            {
                                "user": "amara",
                                "message": "confirmed on two claims",
                                "create_at": 1741100060000,
                            }
                        ],
                    },
                },
            ]
        ),
        encoding="utf-8",
    )
    content, review = read_seed(root, DOMAIN)
    by = {c.name: c for c in content.channels}
    assert set(by) == {"claims-ops", "incidents", "eligibility"}  # general had no messages
    ops = by["claims-ops"].messages
    assert [m.text for m in ops] == [
        "Tomasz can you check the remit queue?",
        "on it, see the queue page",
    ]
    assert ops[1].reply_to == 0 and ops[0].author == "Rosa Delgado"
    assert by["eligibility"].messages[1].reply_to == 0
    kinds = {i.kind for i in review.items}
    assert {"Slack export", "Mattermost export"} <= kinds
    assert not any(i.path.startswith("slack/") for i in review.items if i.kind != "Slack export")


def test_seeded_chat_joins_its_channel_or_makes_its_own_on_the_timeline(tmp_path: Path) -> None:
    root = init_project(tmp_path / "halden", seed=48213).root
    project = Project(root=root)
    folder = _folder(tmp_path)
    _slack(folder)
    seed_svc.seed_world(project, folder)
    loaded = YAML(typ="safe").load(project.manifest_path.read_text("utf-8"))  # pyright: ignore[reportUnknownMemberType]
    world = generate(Manifest.model_validate(loaded), seed_svc.load_content(project))
    from mirrordimensions.world import naming

    channels = {c.name: c for c in world.channels}
    ops = channels["claims-ops"]  # a channel of its own, with everyone in it
    texts = [m.text for m in ops.messages]
    assert texts == ["Tomasz can you check the remit queue?", "on it, see the queue page"]
    assert ops.messages[1].reply_to == 0
    incidents = channels[naming.channels(world)["incidents"]]  # merged into the world's own
    seeded = next(m for m in incidents.messages if m.text == "eligibility calls timing out again")
    day = 24 * 60
    assert day <= seeded.ago <= 2 * day  # the latest message, a day or two before the world starts
    names = [c.name for c in world.channels]
    assert len(names) == len(set(names))  # the world's own names never collide with seeded ones


def _repo(folder: Path, name: str) -> Path:
    from dulwich import porcelain

    path = folder / name
    path.mkdir(parents=True)
    porcelain.init(str(path))
    steps = [
        (
            1_700_000_000,
            "Rosa Delgado",
            {
                "README.md": "# Claims service\n\nRoutes claims to payers.\n",
                "claims/route.py": "def route(claim):\n    return claim.payer\n",
            },
        ),
        (
            1_700_000_000 + 5 * 86400,
            "Tomasz Wierzbicki",
            {
                "claims/route.py": "def route(claim):\n    return claim.payer or 'self-pay'\n",
                "config.env": "PAYER_URL=https://payer.internal\nPAYER_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz0123456789\n",
                "logo.png": "\x89PNG\x00\x00binary",
            },
        ),
    ]
    for when, who, files in steps:
        for rel, text in files.items():
            target = path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode("latin-1") if rel.endswith(".png") else text.encode())
            porcelain.add(str(path), [str(target)])
        porcelain.commit(
            str(path),
            message=f"Change by {who}".encode(),
            author=f"{who} <{who.split()[0].lower()}@vendorcorp.example.net>".encode(),
            committer=b"CI <ci@vendorcorp.example.net>",
            author_timestamp=when,
            commit_timestamp=when,
            no_verify=True,
        )
    return path


def test_a_repository_comes_in_with_its_history_and_nothing_runs(tmp_path: Path) -> None:
    root = tmp_path / "seed"
    root.mkdir()
    repo = _repo(root, "claims-service")
    marker = tmp_path / "hook-ran"
    hook = repo / ".git" / "hooks" / "post-checkout"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    hook.chmod(0o755)
    content, review = read_seed(root, DOMAIN)
    assert not marker.exists()  # objects are read, nothing is checked out or run
    seeded = content.repositories[0]
    assert seeded.name == "claims-service" and seeded.language == "Python"
    assert seeded.description == "Routes claims to payers."
    assert [c.author for c in seeded.commits] == ["Rosa Delgado", "Tomasz Wierzbicki"]
    second = seeded.commits[1].files
    assert "logo.png" not in second  # binary files are left out
    assert "PAYER_TOKEN" not in (second["config.env"] or "") and "PAYER_URL" in (
        second["config.env"] or ""
    )
    assert any(d.path == "claims-service" for d in review.secrets_dropped)
    assert ("claims-service", "git repository") in {(i.path, i.kind) for i in review.items}


def test_a_repository_that_reaches_outside_the_folder_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "seed"
    root.mkdir()
    elsewhere = _repo(tmp_path, "elsewhere")
    worktree = root / "pointer"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {elsewhere / '.git'}\n", encoding="utf-8")
    borrowed = _repo(root, "borrowed")
    (borrowed / ".git" / "objects" / "info").mkdir(parents=True, exist_ok=True)
    (borrowed / ".git" / "objects" / "info" / "alternates").write_text(
        str(elsewhere / ".git" / "objects") + "\n", encoding="utf-8"
    )
    content, review = read_seed(root, DOMAIN)
    assert content.repositories == []
    why = dict(review.not_read)
    assert "worktree or submodule" in why["pointer"]
    assert "borrows objects" in why["borrowed"]


def test_seeded_repositories_join_the_world_on_its_timeline(tmp_path: Path) -> None:
    root = init_project(tmp_path / "halden", seed=48213).root
    project = Project(root=root)
    folder = _folder(tmp_path)
    _repo(folder, "claims-service")
    seed_svc.seed_world(project, folder, accept_personal=True)  # the commits' vendor addresses
    loaded = YAML(typ="safe").load(project.manifest_path.read_text("utf-8"))  # pyright: ignore[reportUnknownMemberType]
    world = generate(Manifest.model_validate(loaded), seed_svc.load_content(project))
    repo = next(r for r in world.repositories if r.name == "claims-service")
    first, second = sorted(repo.commits, key=lambda c: -c.ago)
    day = 24 * 60
    assert day <= second.ago <= 2 * day and first.ago - second.ago == 5 * day
    people = {p.id: p.name for p in world.people}
    assert people[first.author] == "Rosa Delgado" and people[second.author] == "Tomasz Wierzbicki"
    assert any("claims-service" in p.repositories for p in world.projects)
    assert len({r.name for r in world.repositories}) == len(world.repositories)


def test_seeded_repositories_and_channels_never_rename_the_core_ones(tmp_path: Path) -> None:
    root = init_project(tmp_path / "halden", seed=48213).root
    project = Project(root=root)
    loaded = YAML(typ="safe").load(project.manifest_path.read_text("utf-8"))  # pyright: ignore[reportUnknownMemberType]
    manifest = Manifest.model_validate(loaded)
    plain = generate(manifest).names
    folder = _folder(tmp_path)
    _repo(folder, "claims-service")
    _slack(folder)
    seed_svc.seed_world(project, folder, accept_personal=True)
    seeded = generate(manifest, seed_svc.load_content(project)).names
    assert {k: seeded[k] for k in plain} == plain  # the core names are the same
    assert seeded["repo:claims-service"] == "claims-service"  # and the seeded ones are recorded
