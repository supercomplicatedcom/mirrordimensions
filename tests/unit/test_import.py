# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""M8: world import (decision 0025). The importers against synthetic fixtures, the common
draft, conflicts, decisions, and apply into a world definition that builds."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from mirrordimensions.config.manifest import Manifest
from mirrordimensions.errors import MirrorError
from mirrordimensions.importers import mcp_config, mcp_tools, openapi, terraform
from mirrordimensions.importers._common import load_document
from mirrordimensions.project import Project
from mirrordimensions.service import imports, load_project

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portal_fixture

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "import"
# Planted in the fixtures to prove they are never kept.
SECRETS = (
    "3f9c2a7be41d8806c5f1e2a9b7d43c6e8f0a1b2c",  # code host token in an MCP server's variables
    "k7wq3n9xpb1rz5tm8dhy2fcs6a",  # chat token
    "Tr0ub4dor-northfield-77",  # database password, sensitive and in an output
    "wJ9pQe2Lr7Vt4Ky8Nc3Hs6Bd1Mf5Gz0XaUoTiRe",  # access key secret
    "AKIAZ7QX3NORTHFIELD1",  # access key id
    "Harbor-Kestrel-2291",  # a user's password
)
PEOPLE = ("Priya Raman", "priya.raman", "@northfield-logistics.com", "orders_admin", "deploy-bot")


def _read(importer: Any, name: str) -> Any:
    path = FIXTURES / name
    data = load_document(path)
    assert importer.detect(path, data)
    return importer.read(path, data)


@pytest.fixture
def project(tmp_path: Path) -> Project:
    return load_project(portal_fixture.make_project(tmp_path))


def _all(project: Project) -> imports.ImportReview:
    return imports.import_sources(project, sorted(FIXTURES.iterdir()))


# -- each importer --------------------------------------------------------------------------


def test_the_mcp_configuration_names_servers_products_and_hostnames() -> None:
    result = _read(mcp_config.McpConfig(), "mcp.json")
    by = {(f.subject, f.kind): f.value for f in result.facts}
    assert by[("mcp:eng-tools", "hostname")] == {
        "hostname": "mcp.northfield-logistics.com",
        "endpoint": "/mcp",
    }
    # Servers on the agent's machine say which products it works in, and where.
    assert by[("gitea", "system")]["product"] == "gitea"
    assert by[("gitea", "hostname")] == {"hostname": "git.northfield-logistics.com"}
    assert by[("mattermost", "hostname")] == {"hostname": "chat.northfield-logistics.com"}
    # One header and two tokens in variables.
    assert result.skipped_secrets == 3


def test_an_exported_tool_list_belongs_to_its_server() -> None:
    result = _read(mcp_tools.McpTools(), "eng-tools.tools.json")
    tools = [f for f in result.facts if f.kind == "tool"]
    assert {f.subject for f in result.facts} == {"mcp:eng-tools"}
    assert len(tools) == 12 and tools[0].value["inputSchema"]["type"] == "object"
    server = next(f for f in result.facts if f.kind == "system").value
    assert server["server_info"] == {"name": "eng-tools", "version": "2.3.1"}


def test_an_openapi_description_gives_the_system_its_hostname_and_endpoints() -> None:
    result = _read(openapi.OpenApi(), "payments-api.yaml")
    system = next(f for f in result.facts if f.kind == "system")
    assert system.subject == "payments-api" and system.value["kind"] == "internal-service"
    host = next(f for f in result.facts if f.kind == "hostname").value
    assert host == {"hostname": "eu.payments.northfield-logistics.com", "base_path": "/v2"}
    assert sum(f.kind == "endpoint" for f in result.facts) == 5
    gitea = _read(openapi.OpenApi(), "gitea-api.json")
    assert {f.subject for f in gitea.facts} == {"gitea"}  # the title names the product


def test_terraform_state_keeps_structure_and_drops_secrets_and_people() -> None:
    result = _read(terraform.Terraform(), "terraform.json")
    kept = {f.subject: f.value for f in result.facts}
    assert kept["database:orders-db"] == {
        "category": "database",
        "name": "orders-db",
        "type": "aws_db_instance",
        "engine": "postgres",
    }
    assert "queue:shipment-events" in kept and "bucket:northfield-shipping-labels" in kept
    assert kept["dns:git.northfield-logistics.com"]["hostname"] == "git.northfield-logistics.com"
    assert kept["gitea"]["product"] == "gitea"  # a resource of the product's own provider
    # The database password (sensitive), the access key's id and secret, and the sensitive
    # output; the user resource is skipped whole, as a person.
    assert result.skipped_secrets == 4 and result.skipped_people == 1


def test_a_file_of_no_known_kind_is_refused_with_the_kinds_it_could_be(tmp_path: Path) -> None:
    other = tmp_path / "notes.json"
    other.write_text('{"meeting": "Tuesday"}', encoding="utf-8")
    with pytest.raises(MirrorError, match="not a kind of file import reads") as info:
        imports.detect_source(other)
    assert "--as" in info.value.fix
    with pytest.raises(MirrorError, match="No importer called"):
        imports.detect_source(other, "spreadsheet")


# -- the draft ------------------------------------------------------------------------------


def test_no_secret_from_any_fixture_is_written_anywhere_in_the_project(project: Project) -> None:
    _all(project)
    imports.decide(project, "gitea.hostname", "git.northfield-logistics.com")
    imports.apply_import(project)
    written = [p for p in project.root.rglob("*") if p.is_file()]
    assert any(p.name == "draft.json" for p in written)
    for path in written:
        text = path.read_bytes().decode("utf-8", "replace")
        for secret in SECRETS:
            assert secret not in text, f"{secret} in {path.relative_to(project.root)}"


def test_no_persons_name_or_email_is_in_any_fact(project: Project) -> None:
    review = _all(project)
    draft = (project.state_dir / "import" / "draft.json").read_text(encoding="utf-8")
    facts = json.dumps(json.loads(draft)["facts"])
    for detail in PEOPLE:
        assert detail not in facts, detail
    assert review.skipped_people == 2  # the user resource, and an address in a tool's text
    # The draft holds what is needed and is readable only by its owner.
    if sys.platform != "win32":
        assert (project.state_dir / "import" / "draft.json").stat().st_mode & 0o077 == 0


def test_disagreeing_hostnames_are_a_conflict_that_apply_waits_for(project: Project) -> None:
    review = _all(project)
    (conflict,) = review.conflicts
    assert conflict.id == "gitea.hostname"
    choices = {c.value: c.sources for c in conflict.choices}
    assert set(choices) == {"git.northfield-logistics.com", "code.northfield-logistics.com"}
    # The DNS record in Terraform supports what the agent's configuration says.
    assert any("Terraform" in s for s in choices["git.northfield-logistics.com"])
    with pytest.raises(MirrorError, match="not settled"):
        imports.apply_import(project)
    with pytest.raises(MirrorError, match="not one of the values"):
        imports.decide(project, "gitea.hostname", "gitea.northfield-logistics.com")
    settled = imports.decide(project, "gitea.hostname", "git.northfield-logistics.com")
    assert settled.open_conflicts == 0
    assert next(f for f in settled.findings if f.id == "gitea").hostname == (
        "git.northfield-logistics.com"
    )


def test_apply_writes_a_world_that_builds_with_unavailable_systems_listed(
    project: Project,
) -> None:
    from mirrordimensions.config.loader import load_model
    from mirrordimensions.mcp.world import toolset
    from mirrordimensions.network.sandbox import plan_from

    review = _all(project)
    tools = next(f for f in review.findings if f.id == "mcp:eng-tools")
    unavailable = {t.name: t.reason for t in tools.tools if not t.mapped}
    assert unavailable == {
        "search_wiki": "no system in this import serves it",
        "create_release": "no system in this import serves it",
    }
    imports.decide(project, "gitea.hostname", "git.northfield-logistics.com")
    imports.decide(project, "queue:shipment-events", "leave-out")
    changes = imports.apply_import(project)
    assert any(
        "not served (no system backs them): search_wiki, create_release" in c.what for c in changes
    )
    manifest, problems = load_model(project.manifest_path, Manifest)
    assert manifest is not None, problems
    apps = {a.id: a for a in manifest.apps}
    assert apps["code"].hostname == "git.northfield-logistics.com"  # updated in place
    assert apps["payments-api"].build == "unavailable"
    assert manifest.company.domain == "northfield-logistics.com"
    assert [i["name"] for i in manifest.infrastructure] == [
        "northfield-shipping-labels",
        "orders-db",
    ]
    server = apps["eng-tools"]
    assert server.serves is not None and server.serves.backed_by == ["chat", "code"]
    loaded = toolset.load(project.root, "eng-tools", server.serves.model_dump(), set(apps))
    assert len(loaded.names) == 10 and "search_wiki" not in loaded.names
    plan = plan_from(manifest)
    assert "payments-api" not in {a.id for a in plan.apps}  # recorded, left out of creation
    # Every entry the import wrote is traced to the facts it came from.
    traced = imports.provenance(project)
    assert {"apps.code", "apps.eng-tools", "apps.payments-api", "company"} <= set(traced)
    assert all(traced[k] for k in traced)


def test_applying_twice_changes_nothing_more(project: Project) -> None:
    _all(project)
    imports.decide(project, "gitea.hostname", "git.northfield-logistics.com")
    imports.apply_import(project)
    first = project.manifest_path.read_text(encoding="utf-8")
    imports.apply_import(project)
    assert project.manifest_path.read_text(encoding="utf-8") == first


def test_reading_a_file_again_replaces_what_it_said(project: Project) -> None:
    _all(project)
    first = len(imports.get_import(project).findings)
    imports.import_sources(project, [FIXTURES / "terraform.json"])
    assert len(imports.get_import(project).findings) == first
    imports.discard_import(project)
    with pytest.raises(MirrorError, match="Nothing has been imported"):
        imports.get_import(project)


def test_the_command_line_reads_settles_and_applies(project: Project) -> None:
    from typer.testing import CliRunner

    from mirrordimensions.cli.app import app

    def mirror(*args: str) -> Any:
        return CliRunner().invoke(app, ["--project", str(project.root), *args])

    read = mirror("world", "import", *[str(p) for p in sorted(FIXTURES.iterdir())])
    assert read.exit_code == 0, read.output
    assert "1 disagreement(s) to settle" in read.output and "none stored" in read.output
    refused = mirror("world", "import", "apply")
    assert refused.exit_code != 0
    shown = mirror("world", "import", "show", "--conflicts")
    assert "gitea.hostname" in shown.output and "git.northfield-logistics.com" in shown.output
    assert (
        mirror(
            "world", "import", "decide", "gitea.hostname", "git.northfield-logistics.com"
        ).exit_code
        == 0
    )
    applied = mirror("world", "import", "apply")
    assert applied.exit_code == 0, applied.output
    assert "Payments API added" in applied.output and "mirror world create" in applied.output
