# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The one API that the command line, the portal and the operator MCP server all call.

Front ends render these functions' typed results; they contain no logic of their own.
"""

from mirrordimensions.service.project import (
    InitResult,
    Status,
    init_project,
    load_project,
    status,
    validate,
)
from mirrordimensions.service.schema import json_schema

__all__ = [
    "InitResult",
    "Status",
    "init_project",
    "json_schema",
    "load_project",
    "status",
    "validate",
]
