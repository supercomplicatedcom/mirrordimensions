# SPDX-License-Identifier: Apache-2.0
"""The company's people as the building knows them: a badge each, where they sit, and when
they come in (decision 0026, point 9).

Everything is drawn from the world's seed and the person, so the same world always gives the
same badges and the same days. The simulator turns this into occupancy, camera motion and
badge entries in the access log.
"""

# JSON from the world and the platforms is untyped.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mirrordimensions.devices.world.sim import draw

if TYPE_CHECKING:
    from mirrordimensions.world.model import World

RESTRICTED_ROLES = ("admin",)  # whose badges also open restricted doors


def places(sites: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Each site's rooms (`site/floor/room`), or its floors where a floor names no rooms."""
    out: dict[str, list[str]] = {}
    for site in sites:
        found: list[str] = []
        for floor in site.get("floors") or []:
            rooms = list(floor.get("rooms") or [])
            if rooms:
                found += [f"{site['id']}/{floor['id']}/{r}" for r in rooms]
            else:
                found.append(f"{site['id']}/{floor['id']}")
        out[str(site["id"])] = found or [str(site["id"])]
    return out


def badge_holders(world: World, sites: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Everyone with a badge: current staff, and leavers, whose badges are disabled.

    Each person has a home site and a place there, an arrival between 07:30 and 10:00 and a
    departure eight to nine and a half hours later, local time.
    """
    rooms = places(sites)
    if not rooms:
        return []
    site_ids = sorted(rooms)
    out: list[dict[str, Any]] = []
    for person in sorted(world.people, key=lambda p: p.id):
        site = site_ids[int(draw(world.seed, "site", person.id) * len(site_ids))]
        options = rooms[site]
        place = options[int(draw(world.seed, "place", person.id) * len(options))]
        arrive = 450 + int(draw(world.seed, "arrive", person.id) * 150)  # minutes after midnight
        stay = 480 + int(draw(world.seed, "stay", person.id) * 90)
        number = 10000 + int(draw(world.seed, "badge", person.id) * 89999)
        out.append(
            {
                "id": person.id,
                "name": person.name,
                "username": person.username,
                "badge": f"{number:05d}",
                "site": site,
                "place": place,
                "arrive_min": arrive,
                "leave_min": arrive + stay,
                "restricted": any(r in RESTRICTED_ROLES for r in person.roles),
                # minutes before the platform starts; its badge was disabled then
                "left_ago": person.left_ago,
            }
        )
    return out
