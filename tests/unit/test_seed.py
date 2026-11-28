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
