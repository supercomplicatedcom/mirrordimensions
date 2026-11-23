# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path

import pytest

from mirrordimensions.service import init_project

GOLDEN_SEED = 48213


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """A freshly initialized project with the golden seed."""
    root = tmp_path / "northfield-ops"
    init_project(root, seed=GOLDEN_SEED)
    return root
