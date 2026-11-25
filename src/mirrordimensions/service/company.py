# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Read-only slices of the synthetic company, for `mirror world show <slice>` and the portal's
Company screen (build spec, "Portal")."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from mirrordimensions.project import Project
from mirrordimensions.service import agents as agents_svc

Slice = Literal["people", "projects", "canaries"]
MINUTES_PER_DAY = 60 * 24


class PersonRow(BaseModel):
    id: str
    name: str
    username: str
    email: str
    title: str
    department: str
    team: str | None
    manager: str | None
    roles: list[str]
    started_days_ago: int
    left: bool


class ProjectRow(BaseModel):
    name: str
    team: str
    repositories: list[str]
    channel: str


class CanaryRow(BaseModel):
    id: str
    kind: str
    where: str
    value: str


class Company(BaseModel):
    company: str
    domain: str
    industry: str
    seed: int
    people: list[PersonRow] = Field(default_factory=list[PersonRow])
    projects: list[ProjectRow] = Field(default_factory=list[ProjectRow])
    canaries: list[CanaryRow] = Field(default_factory=list[CanaryRow])


def company(
    project: Project, slices: tuple[Slice, ...] = ("people", "projects", "canaries")
) -> Company:
    world = agents_svc._world(project)  # pyright: ignore[reportPrivateUsage]
    out = Company(
        company=world.company, domain=world.domain, industry=world.industry, seed=world.seed
    )
    if "people" in slices:
        out.people = [
            PersonRow(
                id=p.id,
                name=p.name,
                username=p.username,
                email=p.email,
                title=p.title,
                department=p.department,
                team=p.team,
                manager=p.manager,
                roles=[str(r) for r in p.roles],
                started_days_ago=p.started_ago // MINUTES_PER_DAY,
                left=p.left_ago is not None,
            )
            for p in world.people
        ]
    if "projects" in slices:
        out.projects = [
            ProjectRow(name=p.name, team=p.team, repositories=p.repositories, channel=p.channel)
            for p in world.projects
        ]
    if "canaries" in slices:
        out.canaries = [
            CanaryRow(id=c.id, kind=c.kind, where=c.where, value=c.value) for c in world.canaries
        ]
    return out
