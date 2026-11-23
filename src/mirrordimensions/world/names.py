# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Plausible company names and domains, chosen from the seed."""

from __future__ import annotations

import re

from pydantic import BaseModel

from mirrordimensions.world import seeded

PLACES = (
    "Ashcombe",
    "Ashford",
    "Barrowfield",
    "Beaconsfield",
    "Birchmoor",
    "Blackwater",
    "Brackenridge",
    "Brightwell",
    "Brookhaven",
    "Calderstone",
    "Carrowmore",
    "Castleton",
    "Clearwater",
    "Coldharbour",
    "Crestfield",
    "Dalebrook",
    "Denholm",
    "Dunmore",
    "Eastbrook",
    "Elmstead",
    "Fairhaven",
    "Farrowdale",
    "Fernhill",
    "Glenrock",
    "Granford",
    "Greystone",
    "Halcyon",
    "Harwood",
    "Hawthorne",
    "Highcliff",
    "Hollins",
    "Ironbridge",
    "Juniper",
    "Kestrel",
    "Kingsbury",
    "Larkspur",
    "Linwood",
    "Marlow",
    "Meadowcroft",
    "Millbrook",
    "Northfield",
    "Northgate",
    "Norwood",
    "Oakhurst",
    "Orchard",
    "Pembroke",
    "Pinecrest",
    "Ravenscroft",
    "Redfern",
    "Ridgeway",
    "Rookwood",
    "Saltmarsh",
    "Silverdale",
    "Southwick",
    "Stonebridge",
    "Sutherland",
    "Thornbury",
    "Tidewater",
    "Upton",
    "Wexford",
    "Westvale",
    "Whitlock",
    "Willowmere",
    "Windmere",
    "Yarrow",
)

INDUSTRIES: dict[str, tuple[str, ...]] = {
    "logistics": ("Logistics", "Freight", "Distribution"),
    "software": ("Software", "Systems", "Digital"),
    "healthcare": ("Health", "Medical Group", "Care Partners"),
    "finance": ("Capital", "Financial", "Lending"),
    "manufacturing": ("Manufacturing", "Industries", "Components"),
    "retail": ("Retail", "Outfitters", "Home and Garden"),
    "insurance": ("Insurance", "Mutual", "Assurance"),
    "energy": ("Energy", "Power", "Utilities"),
}


class CompanySuggestion(BaseModel):
    name: str
    domain: str
    industry: str


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def suggest_company(seed: int, industry: str | None = None, attempt: int = 0) -> CompanySuggestion:
    """A company for this seed. `attempt` gives another suggestion for the same seed."""
    chosen = industry or seeded.pick(seed, "industry", sorted(INDUSTRIES))
    suffixes = INDUSTRIES.get(chosen, ("Group", "Partners", "Holdings"))
    place = seeded.pick(seed, f"place:{attempt}", PLACES)
    suffix = seeded.pick(seed, f"suffix:{attempt}", suffixes)
    name = f"{place} {suffix}"
    return CompanySuggestion(name=name, domain=f"{slug(name)}.com", industry=chosen)
