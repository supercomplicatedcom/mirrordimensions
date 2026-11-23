# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The file formats: environment manifest, agent file, scenario, run event and result."""

from mirrordimensions.config.agent import Agent
from mirrordimensions.config.events import Event
from mirrordimensions.config.manifest import Manifest
from mirrordimensions.config.result import Result
from mirrordimensions.config.scenario import Scenario

SCHEMAS = {
    "manifest": Manifest,
    "agent": Agent,
    "scenario": Scenario,
    "event": Event,
    "result": Result,
}

__all__ = ["SCHEMAS", "Agent", "Event", "Manifest", "Result", "Scenario"]
