# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The synthetic company: a typed graph, serialized to `.mirror/world.json`.

Times are offsets in minutes before the world is created (`ago`), never absolute dates,
so the same seed gives a byte-identical file whenever and wherever it is generated.
Seeding turns offsets into dates.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["engineer", "manager", "contractor", "admin", "support", "product"]


class Person(BaseModel):
    id: str
    name: str
    username: str
    email: str
    title: str
    department: str
    team: str | None = None
    manager: str | None = None
    roles: list[Role]
    started_ago: int = Field(description="minutes before creation")
    left_ago: int | None = None


class Commit(BaseModel):
    ago: int
    author: str
    message: str
    files: dict[str, str | None] = Field(description="path -> new content, or None to delete")


class Comment(BaseModel):
    ago: int
    author: str
    body: str


class Issue(BaseModel):
    number: int
    title: str
    body: str
    author: str
    assignee: str | None = None
    ago: int
    closed_ago: int | None = None
    labels: list[str] = Field(default_factory=list[str])
    comments: list[Comment] = Field(default_factory=list[Comment])
    event: str | None = None


class Repository(BaseModel):
    name: str
    project: str
    language: str
    description: str
    private: bool = True
    archived_feel: bool = False  # abandoned: no activity for months
    commits: list[Commit]
    issues: list[Issue] = Field(default_factory=list[Issue])
    branches: dict[str, int] = Field(
        default_factory=dict[str, int], description="branch -> commits ago it forked"
    )


class Message(BaseModel):
    ago: int
    author: str
    text: str
    reply_to: int | None = Field(
        default=None, description="index of the thread root in the same channel"
    )


class Channel(BaseModel):
    name: str
    display: str
    private: bool = False
    purpose: str = ""
    members: list[str]
    messages: list[Message] = Field(default_factory=list[Message])


class DirectThread(BaseModel):
    members: list[str]
    messages: list[Message]


class Project(BaseModel):
    name: str
    team: str
    repositories: list[str]
    channel: str


class Event(BaseModel):
    id: str
    kind: Literal["incident", "release", "hire", "departure", "migration"]
    title: str
    ago: int
    people: list[str]
    repository: str | None = None


class Canary(BaseModel):
    id: str
    kind: Literal["token", "password", "record"]
    value: str
    where: str


class World(BaseModel):
    version: Literal[1] = 1
    seed: int
    company: str
    domain: str
    industry: str
    org: str
    utc_offset: int = Field(
        default=0, description="the company's time zone, minutes east of UTC: office hours"
    )
    team: str
    departments: list[str]
    people: list[Person]
    projects: list[Project]
    repositories: list[Repository]
    channels: list[Channel]
    direct: list[DirectThread]
    events: list[Event]
    canaries: list[Canary]
    names: dict[str, str] = Field(
        default_factory=dict[str, str],
        description="What this world calls each core repository and channel, by the name the "
        "built-in scenarios use: `repo:billing-service` -> `invoicing` (decision 0029)",
    )
