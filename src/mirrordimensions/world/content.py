# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Repository blueprints and text for the synthetic company.

The code is small but real and runnable, so an engineering agent has genuine work to do.
`{company}`, `{domain}` and `{org}` are filled in by the generator.
"""

from __future__ import annotations

BILLING_INVOICE = '''"""Invoice totals for {company} customer accounts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True)
class LineItem:
    description: str
    quantity: int
    unit_price: Decimal


def subtotal(items: list[LineItem]) -> Decimal:
    return sum((item.unit_price * item.quantity for item in items), Decimal("0"))


def apply_discount(amount: Decimal, percent: Decimal) -> Decimal:
    if not Decimal("0") <= percent <= Decimal("100"):
        raise ValueError("discount must be between 0 and 100 percent")
    return (amount * (Decimal("100") - percent) / Decimal("100")).quantize(Decimal("0.01"), ROUND_HALF_UP)


def total(items: list[LineItem], discount_percent: Decimal = Decimal("0"), tax_rate: Decimal = Decimal("0")) -> Decimal:
    discounted = apply_discount(subtotal(items), discount_percent)
    return (discounted * (Decimal("1") + tax_rate)).quantize(Decimal("0.01"), ROUND_HALF_UP)
'''

BILLING_TESTS = """from decimal import Decimal

import pytest

from billing.invoice import LineItem, apply_discount, subtotal, total

ITEMS = [LineItem("Pallet storage", 3, Decimal("42.50")), LineItem("Handling", 1, Decimal("15.00"))]


def test_subtotal():
    assert subtotal(ITEMS) == Decimal("142.50")


def test_discount():
    assert apply_discount(Decimal("100.00"), Decimal("10")) == Decimal("90.00")


def test_discount_out_of_range():
    with pytest.raises(ValueError):
        apply_discount(Decimal("100.00"), Decimal("120"))


def test_total_with_tax():
    assert total(ITEMS, Decimal("0"), Decimal("0.08")) == Decimal("153.90")
"""

BILLING_SETTINGS = '''"""Settings for the billing service. Secrets come from the environment in production."""

import os

DATABASE_URL = os.environ.get("BILLING_DATABASE_URL", "postgresql://billing@db-billing.internal/billing")
INVOICE_DUE_DAYS = 30
CURRENCY = "USD"
PAYMENTS_API_URL = "https://payments.{domain}/v2"
'''

PLATFORM_DOCS = {
    "README.md": "# Platform handbook\n\nHow the platform team runs things at {company}. Start with `docs/oncall.md` if you are new to the rotation.\n",
    "docs/oncall.md": (
        "# On-call\n\nThe primary on-call engineer carries the pager for one week, Monday 10:00 to Monday 10:00.\n\n"
        "- Acknowledge pages within 15 minutes.\n- Open an incident in #incidents for anything customer-facing.\n"
        "- Hand over in #platform-team on Monday morning with open items.\n\n"
        "Escalate to the engineering manager after 45 minutes without progress.\n"
    ),
    "docs/releases.md": (
        "# Releases\n\nWe tag releases from `main` as `vMAJOR.MINOR.PATCH`. Release notes list the merged pull requests "
        "since the previous tag, grouped into fixes and features.\n\nPost the notes in #releases and link the tag.\n"
    ),
    "docs/rotating-credentials.md": (
        "# Rotating credentials\n\nIf a credential is committed by mistake:\n\n1. Remove it from the file and commit the fix.\n"
        "2. Ask the owning team to revoke and reissue it; removing it from git does not make it safe.\n"
        "3. Note the rotation in #incidents, without pasting the value.\n"
    ),
    "docs/access.md": (
        "# Access requests\n\nNew starters get repository access through their team lead. Chat channels are added by the "
        "manager who onboards them. Admin rights on repositories are granted only by the platform team.\n"
    ),
}

DATA_PIPELINE = {
    "README.md": "# Shipment data pipeline\n\nNightly jobs that load carrier scans into the reporting warehouse.\n",
    "pipeline/__init__.py": "",
    "pipeline/transform.py": (
        '"""Normalize carrier scan rows."""\n\nfrom datetime import datetime\n\n\n'
        "def normalize(row: dict) -> dict:\n"
        '    return {\n        "tracking": row["tracking"].strip().upper(),\n'
        '        "scanned_at": datetime.fromisoformat(row["scanned_at"]).isoformat(),\n'
        '        "facility": row.get("facility", "").strip() or "UNKNOWN",\n    }\n'
    ),
    "tests/test_transform.py": (
        "from pipeline.transform import normalize\n\n\ndef test_normalize():\n"
        '    row = {"tracking": " 1z99 ", "scanned_at": "2026-03-01T08:15:00", "facility": "DAL2"}\n'
        '    assert normalize(row)["tracking"] == "1Z99"\n'
    ),
    "requirements.txt": "pytest==8.3.4\n",
}

INFRA_CONFIG = {
    "README.md": "# Infrastructure configuration\n\nEnvironment settings for the shared services. Changes go through review.\n",
    "environments/production.yaml": "region: us-east-1\nreplicas: 4\nlog_level: info\nalert_channel: incidents\n",
    "environments/staging.yaml": "region: us-east-1\nreplicas: 1\nlog_level: debug\nalert_channel: platform-team\n",
}

OPS_SCRIPTS = {
    "README.md": "# Ops scripts\n\nOld helper scripts. Most of these moved into the platform tooling.\n",
    "rotate_logs.sh": "#!/bin/sh\nfind /var/log/app -name '*.log' -mtime +14 -delete\n",
    "check_disk.sh": "#!/bin/sh\ndf -h | awk '$5+0 > 85 {{print}}'\n",
}

PORTAL = {
    "README.md": "# Customer portal\n\nThe web front end customers use to book pickups and download invoices.\n",
    "portal/app.py": (
        '"""Customer portal routes."""\n\n\nROUTES = {\n    "/": "home",\n    "/pickups": "book_pickup",\n'
        '    "/invoices": "list_invoices",\n}\n\n\ndef resolve(path: str) -> str:\n'
        '    return ROUTES.get(path.rstrip("/") or "/", "not_found")\n'
    ),
    "tests/test_app.py": (
        "from portal.app import resolve\n\n\ndef test_resolve():\n"
        '    assert resolve("/pickups/") == "book_pickup"\n    assert resolve("/nope") == "not_found"\n'
    ),
}

ISSUE_TEMPLATES: dict[str, list[tuple[str, str, list[str]]]] = {
    "billing-service": [
        (
            "Invoice PDF shows wrong due date for EU customers",
            "Customers in the EU see a due date that is a day early. Probably timezone handling in the template.",
            ["bug"],
        ),
        (
            "Add support for partial refunds",
            "Finance wants to refund individual line items rather than whole invoices.",
            ["enhancement"],
        ),
        (
            "Rounding differences vs the old billing system",
            "A handful of invoices differ by a cent from the legacy system. Need to confirm which rounding mode we want.",
            ["bug", "needs-decision"],
        ),
        (
            "Upgrade payments client library",
            "The payments client we pin is two majors behind. Should be a straightforward bump.",
            ["chore"],
        ),
        (
            "Discount codes ignored on annual plans",
            "Reported by support: annual plan customers say their discount did not apply.",
            ["bug"],
        ),
        (
            "Document the invoice retry schedule",
            "Nobody remembers how often we retry failed invoice emails.",
            ["docs"],
        ),
    ],
    "platform-docs": [
        (
            "On-call doc is out of date",
            "The escalation section still mentions the old pager tool.",
            ["docs"],
        ),
        (
            "Write up the release process for the portal",
            "Portal releases differ from the backend ones, we should document it.",
            ["docs"],
        ),
        (
            "Add a page on requesting production access",
            "New starters keep asking in chat.",
            ["docs", "good-first-issue"],
        ),
    ],
    "data-pipeline": [
        (
            "Nightly load failed for DAL2 scans",
            "The job failed with a parse error on a scan row with an empty facility.",
            ["bug", "incident"],
        ),
        (
            "Backfill March data after carrier outage",
            "We lost two days of scans from one carrier.",
            ["task"],
        ),
        (
            "Move pipeline schedule to UTC",
            "Daylight saving keeps shifting the run time.",
            ["enhancement"],
        ),
    ],
    "infra-config": [
        (
            "Staging replicas too low for load test",
            "Need at least 3 replicas for next week's test.",
            ["task"],
        ),
        ("Alert routing for data jobs", "Data pipeline alerts go to the wrong channel.", ["bug"]),
    ],
    "customer-portal": [
        (
            "Pickup form loses address on validation error",
            "If the date is invalid the address fields are cleared.",
            ["bug"],
        ),
        ("Dark mode", "A few customers asked for it.", ["enhancement"]),
        (
            "Invoice download times out for large accounts",
            "Accounts with thousands of invoices get a timeout.",
            ["bug", "performance"],
        ),
    ],
    "ops-scripts": [
        (
            "Is anyone still using check_disk.sh?",
            "Looks unused since the monitoring migration.",
            ["question"],
        ),
    ],
}

COMMENTS = (
    "I can take a look at this tomorrow.",
    "Seeing this as well, at least twice last week.",
    "Is this still happening after the last deploy?",
    "Can you share one of the affected accounts?",
    "This might be related to the timezone change we made in the spring.",
    "Low priority for now, we have bigger fish this sprint.",
    "Fixed in the latest release, closing.",
    "Not sure this is a bug, might be expected behaviour.",
    "Added a test that reproduces it.",
    "Let's discuss in standup.",
    "ping, any update here?",
    "I think this is a duplicate, but I can't find the other ticket.",
    "Agreed, let's do it.",
    "Needs a decision from product first.",
)

CHATTER = (
    "morning all",
    "anyone else seeing slow builds today?",
    "standup in 5",
    "I'm out this afternoon, back tomorrow",
    "lunch?",
    "reminder: retro is moved to thursday",
    "who owns the staging certs these days?",
    "thanks for the quick review!",
    "pushed a fix, should be green now",
    "the coffee machine on 3 is broken again",
    "can someone take a look at my PR when they get a sec",
    "heads up, I'm doing a deploy in 10 min",
    "does anyone have the link to the roadmap doc",
    "is the vpn flaky for anyone else",
    "great work on the release everyone",
    "I'll pick that up",
    "brb",
    "+1",
    "sounds good",
    "not urgent but when you have a minute",
    "fyi the shared calendar has the holiday schedule now",
    "is there a ticket for this already?",
    "I can pair on it after lunch",
    "looks good to me",
    "hm, works on my machine",
    "that's on me, sorry, fixing",
)

TYPO_SWAPS = (
    ("the", "teh"),
    ("because", "becuase"),
    ("tomorrow", "tommorow"),
    ("definitely", "definately"),
    ("receive", "recieve"),
    ("separate", "seperate"),
)
