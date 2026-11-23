# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""`mirror init`: valid output, byte-identical for a seed on every host, CA kept private."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography import x509

from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.files import owner_only_problem
from mirrordimensions.project import Project
from mirrordimensions.service import init_project, validate
from mirrordimensions.world import denylist

GOLDEN = Path(__file__).resolve().parent.parent / "golden" / "init-48213"


def test_creates_a_valid_project(project_dir: Path) -> None:
    assert validate(Project(root=project_dir)) == []
    assert (project_dir / "agents").is_dir()
    assert (project_dir / ".mirror" / "ca" / "root-ca.crt").is_file()


@pytest.mark.parametrize("name", ["mirror.yaml", ".gitignore"])
def test_generated_files_match_golden_bytes(project_dir: Path, name: str) -> None:
    # The golden files are committed with \n endings and compared as bytes, so this test
    # failing on any one OS means generated output differs between hosts.
    assert (project_dir / name).read_bytes() == (GOLDEN / name).read_bytes()


def test_same_seed_same_files(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    init_project(a, name="shared", seed=7)
    init_project(b, name="shared", seed=7)
    assert (a / "mirror.yaml").read_bytes() == (b / "mirror.yaml").read_bytes()


def test_different_seed_different_company(tmp_path: Path) -> None:
    a = init_project(tmp_path / "a", seed=1)
    b = init_project(tmp_path / "b", seed=2)
    assert (a.company.name, a.seed) != (b.company.name, b.seed)


def test_generated_text_has_no_denied_words(project_dir: Path) -> None:
    text = (project_dir / "mirror.yaml").read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    body = body.replace("mattermost", "").replace("gitea", "")
    assert denylist.findings(body) == []


def test_root_ca_is_private_and_corporate(project_dir: Path) -> None:
    ca = project_dir / ".mirror" / "ca"
    for path in (ca, ca / "root-ca.key", ca / "root-ca.crt"):
        assert owner_only_problem(path) is None
    cert = x509.load_pem_x509_certificate((ca / "root-ca.crt").read_bytes())
    subject = cert.subject.rfc4514_string()
    assert "Internal Root CA" in subject
    assert denylist.findings(subject.replace("Internal Root CA", "")) == []
    constraints = cert.extensions.get_extension_for_class(x509.BasicConstraints).value
    assert constraints.ca is True


def test_refuses_existing_project(project_dir: Path) -> None:
    with pytest.raises(MirrorError, match="already holds a project"):
        init_project(project_dir)
