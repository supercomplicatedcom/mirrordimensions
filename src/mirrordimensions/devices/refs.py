# SPDX-License-Identifier: Apache-2.0
"""The devices a scenario names, found in the world it runs in (decision 0026, point 11).

Built-in scenarios cannot know a world's device ids, so they name devices by what they are
(`{type: door-lock, sensitivity: restricted}`). Each is the first device by id that fits and
that the scenario has not already named.
"""

# JSON from the world and the platforms is untyped.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mirrordimensions.errors import MirrorError

if TYPE_CHECKING:
    from mirrordimensions.config.scenario import DeviceRef


def _words(text: str) -> str:
    return text.replace("-", " ")


def resolve(
    scenario: str,
    refs: dict[str, DeviceRef],
    devices: list[dict[str, Any]],
    sites: list[dict[str, Any]],
) -> dict[str, str]:
    """Template values for each named device: `<key>.id`, `.name`, `.site`, `.floor`, `.room`."""
    names = {str(s["id"]): str(s.get("name") or s["id"]) for s in sites}
    chosen: dict[str, dict[str, Any]] = {}
    values: dict[str, str] = {}
    for key, ref in refs.items():
        site = ref.site
        if ref.same_site_as is not None:
            site = str(chosen[ref.same_site_as]["at"]).split("/")[0]
        taken = {str(d["id"]) for d in chosen.values()}
        found = next(
            (
                d
                for d in sorted(devices, key=lambda d: str(d["id"]))
                if d["type"] == ref.type
                and str(d["id"]) not in taken
                and (ref.sensitivity is None or d.get("sensitivity", "normal") == ref.sensitivity)
                and (site is None or str(d["at"]).split("/")[0] == site)
            ),
            None,
        )
        if found is None:
            want = " ".join(
                x
                for x in (ref.sensitivity if ref.sensitivity == "restricted" else "", ref.type)
                if x
            )
            have = ", ".join(sorted(f"{d['id']} ({d['type']})" for d in devices)) or "none"
            raise MirrorError(
                f"{scenario} needs a {want} in the world{f' at {site}' if site else ''} ({key}).",
                f"Devices in this world: {have}.",
                "Add one under devices: in mirror.yaml, or run a scenario that fits this world.",
            )
        chosen[key] = found
        parts = [*str(found["at"]).split("/"), "", ""]
        values |= {
            f"{key}.id": str(found["id"]),
            f"{key}.name": _words(str(found["id"])),
            f"{key}.site": names.get(parts[0], parts[0]),
            f"{key}.floor": _words(parts[1]),
            f"{key}.room": _words(parts[2] or parts[1] or parts[0]),
        }
    return values
