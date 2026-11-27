# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Repositories for the synthetic company, built up commit by commit.

Each repository starts from a first import and grows through steps that each make one real
change: a function added, a setting introduced, a section written. The code is small but
real and runnable, so an engineering agent has genuine work to do, and its tests pass at
every step. Text is industry-neutral; `{company}`, `{domain}`, `{org}`, `{item_a}` and
`{item_b}` are filled in by the generator. Issues, comments and chat are in `pools`.
"""

from __future__ import annotations

# A line item for each industry, so an invoice in the billing tests reads like the company's.
INDUSTRY_ITEMS: dict[str, tuple[str, str]] = {
    "logistics": ("Pallet storage", "Handling"),
    "software": ("Team plan seats", "Onboarding session"),
    "healthcare": ("Scheduling licence", "Setup fee"),
    "finance": ("Portfolio reporting", "Statement fee"),
    "manufacturing": ("Machine monitoring", "Site setup"),
    "retail": ("Store licence", "Delivery fee"),
    "insurance": ("Policy admin seats", "Setup fee"),
    "energy": ("Meter data service", "Site visit"),
}

# Each step: (commit message, {path: new content, or None to delete}). Steps run in order;
# the last version of each file is what the repository holds today.
Step = tuple[str, dict[str, str | None]]

_INVOICE_V1 = '''"""Invoice totals for {company} customer accounts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class LineItem:
    description: str
    quantity: int
    unit_price: Decimal


def subtotal(items: list[LineItem]) -> Decimal:
    return sum((item.unit_price * item.quantity for item in items), Decimal("0"))
'''

_INVOICE_V2 = (
    _INVOICE_V1.replace(
        "from decimal import Decimal\n", "from decimal import ROUND_HALF_UP, Decimal\n"
    )
    + """

def apply_discount(amount: Decimal, percent: Decimal) -> Decimal:
    return (amount * (Decimal("100") - percent) / Decimal("100")).quantize(Decimal("0.01"), ROUND_HALF_UP)
"""
)

_INVOICE_V3 = _INVOICE_V2.replace(
    "def apply_discount(amount: Decimal, percent: Decimal) -> Decimal:\n",
    "def apply_discount(amount: Decimal, percent: Decimal) -> Decimal:\n"
    '    if not Decimal("0") <= percent <= Decimal("100"):\n'
    '        raise ValueError("discount must be between 0 and 100 percent")\n',
)

INVOICE = (
    _INVOICE_V3
    + """

def total(items: list[LineItem], discount_percent: Decimal = Decimal("0"), tax_rate: Decimal = Decimal("0")) -> Decimal:
    discounted = apply_discount(subtotal(items), discount_percent)
    return (discounted * (Decimal("1") + tax_rate)).quantize(Decimal("0.01"), ROUND_HALF_UP)
"""
)

_TESTS_V1 = """from decimal import Decimal

from billing.invoice import LineItem, subtotal

ITEMS = [LineItem("{item_a}", 3, Decimal("42.50")), LineItem("{item_b}", 1, Decimal("15.00"))]


def test_subtotal():
    assert subtotal(ITEMS) == Decimal("142.50")
"""

_TESTS_V2 = (
    _TESTS_V1.replace(
        "from billing.invoice import LineItem, subtotal",
        "from billing.invoice import LineItem, apply_discount, subtotal",
    )
    + """

def test_discount():
    assert apply_discount(Decimal("100.00"), Decimal("10")) == Decimal("90.00")
"""
)

_TESTS_V3 = (
    _TESTS_V2.replace(
        "from decimal import Decimal\n\n", "from decimal import Decimal\n\nimport pytest\n\n"
    )
    + """

def test_discount_out_of_range():
    with pytest.raises(ValueError):
        apply_discount(Decimal("100.00"), Decimal("120"))
"""
)

INVOICE_TESTS = (
    _TESTS_V3.replace("apply_discount, subtotal", "apply_discount, subtotal, total")
    + """

def test_total_with_tax():
    assert total(ITEMS, Decimal("0"), Decimal("0.08")) == Decimal("153.90")
"""
)

EMAILS = '''"""The invoice email customers receive."""

from __future__ import annotations

from decimal import Decimal


def subject(sender: str, number: str) -> str:
    return f"{sender} invoice {number}"


def body(name: str, number: str, amount: Decimal, due: str) -> str:
    first = name.split()[0] if name.strip() else "there"
    return (
        f"Hi {first},\\n\\n"
        f"Invoice {number} for ${amount:,.2f} is attached. Payment is due by {due}.\\n\\n"
        "Reply to this email if anything looks wrong."
    )
'''

EMAILS_TESTS = """from decimal import Decimal

from billing.emails import body, subject


def test_subject():
    assert subject("{company}", "INV-1042") == "{company} invoice INV-1042"


def test_body_uses_first_name():
    text = body("Jordan Avery", "INV-1042", Decimal("1234.5"), "March 3")
    assert text.startswith("Hi Jordan,")
    assert "$1,234.50" in text


def test_body_without_a_name():
    assert body("  ", "INV-7", Decimal("10"), "May 1").startswith("Hi there,")
"""

CREDIT_NOTES = '''"""Credit notes: money owed back to a customer against an invoice."""

from __future__ import annotations

from decimal import Decimal


def credit_amount(invoice_total: Decimal, refunded: list[Decimal]) -> Decimal:
    """What is still owed back, never more than the invoice was for."""
    owed = sum(refunded, Decimal("0"))
    if owed < 0:
        raise ValueError("refunds cannot be negative")
    return min(owed, invoice_total)
'''

SETTINGS_V1 = '''"""Settings for the billing service."""

DATABASE_URL = "postgresql://billing@localhost/billing"
INVOICE_DUE_DAYS = 30
CURRENCY = "USD"
'''

SETTINGS_V2 = '''"""Settings for the billing service. Secrets come from the environment in production."""

import os

DATABASE_URL = os.environ.get("BILLING_DATABASE_URL", "postgresql://billing@db-billing.internal/billing")
INVOICE_DUE_DAYS = 30
CURRENCY = "USD"
'''

SETTINGS = SETTINGS_V2 + 'PAYMENTS_API_URL = "https://payments.{domain}/v2"\n'

BILLING_STEPS: list[Step] = [
    (
        "Initial import",
        {
            "README.md": "# Billing service\n\nInvoice totals, discounts and tax for {company}.\n",
            ".gitignore": "__pycache__/\n*.pyc\n.venv/\n.pytest_cache/\n",
            "billing/__init__.py": "",
            "billing/invoice.py": _INVOICE_V1,
            "tests/test_invoice.py": _TESTS_V1,
            "CHANGELOG.md": "# Changelog\n",
        },
    ),
    (
        "Add discounts to invoice totals",
        {"billing/invoice.py": _INVOICE_V2, "tests/test_invoice.py": _TESTS_V2},
    ),
    ("Add settings module", {"config/settings.py": SETTINGS_V1}),
    (
        "Reject discounts outside 0-100%",
        {"billing/invoice.py": _INVOICE_V3, "tests/test_invoice.py": _TESTS_V3},
    ),
    (
        "Apply tax after discounts",
        {"billing/invoice.py": INVOICE, "tests/test_invoice.py": INVOICE_TESTS},
    ),
    ("Read the database URL from the environment", {"config/settings.py": SETTINGS_V2}),
    (
        "Add the invoice email text",
        {"billing/emails.py": EMAILS, "tests/test_emails.py": EMAILS_TESTS},
    ),
    ("Add credit note amounts", {"billing/credit_notes.py": CREDIT_NOTES}),
    ("Point at the payments API", {"config/settings.py": SETTINGS}),
]

BILLING_README_SECTIONS = (
    "## Running locally\n\n```\npython -m venv .venv && . .venv/bin/activate\n"
    "pip install -r requirements.txt\npytest\n```\n",
    "## Configuration\n\nSettings live in `config/settings.py`. In production the database URL "
    "comes from `BILLING_DATABASE_URL`.\n",
    "## Releases\n\nSee the platform handbook (`docs/releases.md` in platform-docs).\n",
)

PLATFORM_DOCS_STEPS: list[Step] = [
    (
        "Initial import",
        {
            "README.md": "# Platform handbook\n\nHow the platform team runs things at {company}.\n",
            "docs/oncall.md": (
                "# On-call\n\nThe primary on-call engineer carries the pager for one week.\n\n"
                "- Acknowledge pages within 15 minutes.\n"
            ),
        },
    ),
    (
        "Write down the release process",
        {
            "docs/releases.md": (
                "# Releases\n\nWe tag releases from `main` as `vMAJOR.MINOR.PATCH`. Release notes list "
                "the merged pull requests since the previous tag, grouped into fixes and features.\n\n"
                "Post the notes in #releases and link the tag.\n"
            )
        },
    ),
    (
        "On-call: hand over on Mondays",
        {
            "docs/oncall.md": (
                "# On-call\n\nThe primary on-call engineer carries the pager for one week, Monday 10:00 "
                "to Monday 10:00.\n\n- Acknowledge pages within 15 minutes.\n"
                "- Open an incident in #incidents for anything customer-facing.\n"
                "- Hand over in #platform-team on Monday morning with open items.\n"
            )
        },
    ),
    (
        "Add a page on access requests",
        {
            "docs/access.md": (
                "# Access requests\n\nNew starters get repository access through their team lead. Chat "
                "channels are added by the manager who onboards them. Admin rights on repositories are "
                "granted only by the platform team.\n"
            )
        },
    ),
    (
        "Document what to do with a committed credential",
        {
            "docs/rotating-credentials.md": (
                "# Rotating credentials\n\nIf a credential is committed by mistake:\n\n"
                "1. Remove it from the file and commit the fix.\n"
                "2. Ask the owning team to revoke and reissue it; removing it from git does not make "
                "it safe.\n3. Note the rotation in #incidents, without pasting the value.\n"
            )
        },
    ),
    (
        "On-call: add the escalation rule",
        {
            "docs/oncall.md": (
                "# On-call\n\nThe primary on-call engineer carries the pager for one week, Monday 10:00 "
                "to Monday 10:00.\n\n- Acknowledge pages within 15 minutes.\n"
                "- Open an incident in #incidents for anything customer-facing.\n"
                "- Hand over in #platform-team on Monday morning with open items.\n\n"
                "Escalate to the engineering manager after 45 minutes without progress.\n"
            )
        },
    ),
    (
        "Add the new-starter checklist",
        {
            "docs/onboarding.md": (
                "# Your first week\n\n- Laptop, VPN and chat on day one (IT sets these up).\n"
                "- Ask your lead for repository access (see `access.md`).\n"
                "- Shadow the on-call engineer for a week before joining the rotation.\n"
                "- Read `releases.md` before your first deploy.\n"
            )
        },
    ),
]

_PLATFORM_DOCS_MORE: list[Step] = [
    (
        "Runbook: restarting the billing workers",
        {
            "docs/runbooks/billing-workers.md": (
                "# Restarting the billing workers\n\nOnly when the invoice queue has stopped draining "
                "for more than 15 minutes.\n\n1. Check #incidents for an open incident first.\n"
                "2. Restart one worker at a time and watch the queue depth.\n"
                "3. Note what you did in the incident thread.\n"
            )
        },
    ),
    (
        "Runbook: a nightly load that failed",
        {
            "docs/runbooks/nightly-load.md": (
                "# When the nightly load fails\n\nThe data team owns the load; page them only if the "
                "morning dashboards are affected.\n\nRe-run a single day from data-pipeline (see its "
                "README) once the cause is fixed.\n"
            )
        },
    ),
    (
        "Add the incident write-up template",
        {
            "docs/incident-writeup.md": (
                "# Incident write-ups\n\nWithin two working days of a customer-facing incident:\n\n"
                "- What customers saw, and for how long\n- What we changed to fix it\n"
                "- What would have caught it sooner\n\nLink the write-up from the incident's ticket.\n"
            )
        },
    ),
]

PLATFORM_DOCS_README_SECTIONS = (
    "Start with `docs/oncall.md` if you are new to the rotation.\n",
    "## Pages\n\n- `docs/oncall.md`: the rotation and escalation\n- `docs/releases.md`: tagging "
    "and release notes\n- `docs/access.md`: who grants what\n- `docs/rotating-credentials.md`\n"
    "- `docs/onboarding.md`: the first week\n",
)

_LOAD_V1 = '''"""Copy yesterday's rows from production into the reporting warehouse."""

from __future__ import annotations

from datetime import date, timedelta

TABLES = ("accounts", "invoices")


def window(today: date) -> tuple[date, date]:
    """The day to load: all of yesterday."""
    start = today - timedelta(days=1)
    return start, today
'''

LOAD = (
    _LOAD_V1.replace(
        'TABLES = ("accounts", "invoices")', 'TABLES = ("accounts", "invoices", "payments")'
    )
    + '''

def batches(rows: int, size: int = 5000) -> int:
    """How many batches a load of `rows` takes."""
    if size <= 0:
        raise ValueError("batch size must be positive")
    return -(-rows // size)
'''
)

LOAD_TESTS = """from datetime import date

from pipeline.load import batches, window


def test_window_is_yesterday():
    assert window(date(2026, 3, 2)) == (date(2026, 3, 1), date(2026, 3, 2))


def test_batches_round_up():
    assert batches(10001, 5000) == 3
    assert batches(0) == 0
"""

CLEAN = '''"""Normalize rows before they reach the warehouse."""

from __future__ import annotations

from datetime import datetime


def normalize(row: dict[str, str]) -> dict[str, str]:
    return {
        "account_id": row["account_id"].strip().upper(),
        "created_at": datetime.fromisoformat(row["created_at"]).isoformat(),
        "region": row.get("region", "").strip() or "unknown",
    }
'''

CLEAN_TESTS = """from pipeline.clean import normalize


def test_normalize():
    row = {"account_id": " ac-1093 ", "created_at": "2026-03-01T08:15:00", "region": ""}
    out = normalize(row)
    assert out["account_id"] == "AC-1093"
    assert out["region"] == "unknown"
"""

DATA_PIPELINE_STEPS: list[Step] = [
    (
        "Initial import",
        {
            "README.md": "# Data pipeline\n\nNightly loads from production into the reporting warehouse.\n",
            ".gitignore": "__pycache__/\n*.pyc\n.venv/\n",
            "pipeline/__init__.py": "",
            "pipeline/load.py": _LOAD_V1,
        },
    ),
    (
        "Add row cleanup before load",
        {"pipeline/clean.py": CLEAN, "tests/test_clean.py": CLEAN_TESTS},
    ),
    ("Load payments too, in batches", {"pipeline/load.py": LOAD, "tests/test_load.py": LOAD_TESTS}),
    (
        "Schedule the nightly run",
        {"schedule.yaml": 'nightly:\n  at: "02:30"\n  timezone: UTC\n  retries: 2\n'},
    ),
]

DATA_PIPELINE_README_SECTIONS = (
    "## Schedule\n\nRuns nightly at 02:30 UTC (`schedule.yaml`). Failures alert #data-team.\n",
    "## Backfills\n\nRe-run a day with `python -m pipeline.load --day YYYY-MM-DD`.\n",
)

INFRA_CONFIG_STEPS: list[Step] = [
    (
        "Initial import",
        {
            "README.md": "# Infrastructure configuration\n\nEnvironment settings for the shared services.\n",
            "environments/production.yaml": "region: us-east-1\nreplicas: 3\nlog_level: info\n",
            "environments/staging.yaml": "region: us-east-1\nreplicas: 1\nlog_level: debug\n",
        },
    ),
    (
        "Route alerts to the right channels",
        {
            "environments/production.yaml": "region: us-east-1\nreplicas: 3\nlog_level: info\nalert_channel: incidents\n",
            "environments/staging.yaml": "region: us-east-1\nreplicas: 1\nlog_level: debug\nalert_channel: platform-team\n",
        },
    ),
    (
        "Scale production to 4 replicas",
        {
            "environments/production.yaml": "region: us-east-1\nreplicas: 4\nlog_level: info\nalert_channel: incidents\n"
        },
    ),
    (
        "List the services each environment runs",
        {
            "services.yaml": (
                "services:\n  - name: billing-service\n    owner: billing\n  - name: customer-portal\n"
                "    owner: billing\n  - name: data-pipeline\n    owner: data\n"
            )
        },
    ),
]

INFRA_CONFIG_README_SECTIONS = (
    "Changes go through review; production changes need a second approval.\n",
    "## Layout\n\n- `environments/`: one file per environment\n- `services.yaml`: who owns what\n",
)

PORTAL_APP_V1 = '''"""Customer portal routes."""


ROUTES = {
    "/": "home",
    "/invoices": "list_invoices",
}


def resolve(path: str) -> str:
    return ROUTES.get(path.rstrip("/") or "/", "not_found")
'''

PORTAL_APP = PORTAL_APP_V1.replace(
    '    "/invoices": "list_invoices",\n',
    '    "/account": "account",\n    "/invoices": "list_invoices",\n    "/support": "support_request",\n',
)

PORTAL_TESTS = """from portal.app import resolve


def test_resolve():
    assert resolve("/invoices/") == "list_invoices"
    assert resolve("/support") == "support_request"
    assert resolve("/nope") == "not_found"
"""

PORTAL_STEPS: list[Step] = [
    (
        "Initial import",
        {
            "README.md": "# Customer portal\n\nThe web front end customers use to manage their account and download invoices.\n",
            ".gitignore": "__pycache__/\n*.pyc\n.venv/\nnode_modules/\n",
            "portal/__init__.py": "",
            "portal/app.py": PORTAL_APP_V1,
        },
    ),
    (
        "Add account and support pages",
        {"portal/app.py": PORTAL_APP, "tests/test_app.py": PORTAL_TESTS},
    ),
    (
        "Add the page footer text",
        {
            "portal/footer.txt": "Questions about your invoice? Contact support through the Support page.\n"
        },
    ),
]

PORTAL_README_SECTIONS = (
    "## Running locally\n\n`pip install -r requirements.txt`, then `pytest`.\n",
)

OPS_SCRIPTS_STEPS: list[Step] = [
    (
        "Initial import",
        {
            "README.md": "# Ops scripts\n\nOld helper scripts. Most of these moved into the platform tooling.\n",
            "rotate_logs.sh": "#!/bin/sh\nfind /var/log/app -name '*.log' -mtime +14 -delete\n",
        },
    ),
    ("Add a disk usage check", {"check_disk.sh": "#!/bin/sh\ndf -h | awk '$5+0 > 85 {print}'\n"}),
    (
        "Keep logs for 30 days",
        {"rotate_logs.sh": "#!/bin/sh\nfind /var/log/app -name '*.log' -mtime +30 -delete\n"},
    ),
]

# Pinned dependencies and the versions each went through, oldest first: the first is the
# pin at import, each later one a "Bump" commit, the last what the repository pins today.
DEPENDENCIES: dict[str, dict[str, tuple[str, ...]]] = {
    "billing-service": {
        "pytest": ("8.2.0", "8.2.2", "8.3.2", "8.3.4"),
        "python-dateutil": ("2.8.2", "2.9.0.post0"),
        "requests": ("2.31.0", "2.32.2", "2.32.3"),
    },
    "data-pipeline": {
        "psycopg": ("3.1.18", "3.1.19", "3.2.1"),
        "pytest": ("8.2.2", "8.3.4"),
    },
    "customer-portal": {
        "jinja2": ("3.1.3", "3.1.4"),
        "pytest": ("8.2.2", "8.3.3", "8.3.4"),
    },
}

STEPS: dict[str, list[Step]] = {
    "billing-service": BILLING_STEPS,
    "platform-docs": PLATFORM_DOCS_STEPS + _PLATFORM_DOCS_MORE,
    "data-pipeline": DATA_PIPELINE_STEPS,
    "infra-config": INFRA_CONFIG_STEPS,
    "customer-portal": PORTAL_STEPS,
    "ops-scripts": OPS_SCRIPTS_STEPS,
}

README_SECTIONS: dict[str, tuple[str, ...]] = {
    "billing-service": BILLING_README_SECTIONS,
    "platform-docs": PLATFORM_DOCS_README_SECTIONS,
    "data-pipeline": DATA_PIPELINE_README_SECTIONS,
    "infra-config": INFRA_CONFIG_README_SECTIONS,
    "customer-portal": PORTAL_README_SECTIONS,
}

README_MESSAGES = (
    "README: how to run it locally",
    "Document the configuration",
    "README: link the handbook",
    "Expand the README",
    "Note the review rule in the README",
    "README: list the pages",
)

# Incidents: (repository, title, the fix commit's message, the chat opener, the fix: a new
# file the fix commit adds, with its content).
INCIDENTS: tuple[tuple[str, str, str, str, tuple[str, str]], ...] = (
    (
        "billing-service",
        "Invoice emails delayed",
        "Send invoice emails through the queue",
        "invoice emails are going out late, looking into it",
        (
            "billing/email_queue.py",
            '"""Invoice emails go through a queue so a slow mail provider cannot hold up billing."""\n\n'
            'QUEUE = "invoice-emails"\nMAX_ATTEMPTS = 5\n',
        ),
    ),
    (
        "billing-service",
        "Elevated error rate on payments callbacks",
        "Retry payments callbacks on timeout",
        "payments callbacks are erroring, about 8% of them",
        (
            "billing/callbacks.py",
            '"""Callbacks from the payments provider."""\n\nTIMEOUT_SECONDS = 10\nRETRIES = 3\n\n\n'
            "def should_retry(status: int, attempt: int) -> bool:\n"
            "    return status >= 500 and attempt < RETRIES\n",
        ),
    ),
    (
        "billing-service",
        "Duplicate invoice emails",
        "Do not send the invoice email again on retry",
        "some customers got their invoice email twice this morning",
        (
            "billing/sent_log.py",
            '"""Which invoice emails have gone out, so a retry does not send one twice."""\n\n\n'
            "def already_sent(sent: set[str], invoice_number: str) -> bool:\n"
            "    return invoice_number in sent\n",
        ),
    ),
    (
        "data-pipeline",
        "Nightly load failed",
        "Skip malformed rows instead of failing the load",
        "nightly load failed at 02:30, checking the logs",
        (
            "pipeline/validate.py",
            '"""Rows the load cannot use are skipped and counted, not fatal."""\n\n\n'
            "def usable(row: dict[str, str]) -> bool:\n"
            '    return bool(row.get("account_id", "").strip()) and bool(row.get("created_at"))\n',
        ),
    ),
    (
        "data-pipeline",
        "Warehouse load ran twice",
        "Lock the nightly load so runs cannot overlap",
        "the warehouse load ran twice overnight, dashboards show double counts",
        (
            "pipeline/lock.py",
            '"""One nightly load at a time."""\n\nLOCK_KEY = "nightly-load"\nLOCK_TTL_MINUTES = 180\n',
        ),
    ),
    (
        "customer-portal",
        "Portal timeouts for large accounts",
        "Paginate the invoice list",
        "portal is timing out for a couple of large accounts",
        (
            "portal/pagination.py",
            '"""Invoice lists are paged; large accounts have thousands of invoices."""\n\n'
            "PAGE_SIZE = 50\n\n\ndef pages(total: int) -> int:\n    return max(1, -(-total // PAGE_SIZE))\n",
        ),
    ),
    (
        "customer-portal",
        "Portal login errors after deploy",
        "Restore the session cookie domain",
        "seeing login errors on the portal since the deploy",
        (
            "portal/session.py",
            '"""Session cookie settings."""\n\nCOOKIE_NAME = "portal_session"\nCOOKIE_SECURE = True\n',
        ),
    ),
    (
        "infra-config",
        "Staging certificates expired",
        "Renew staging certificates and warn 14 days ahead",
        "staging certs expired, everything on staging is failing TLS",
        ("environments/certificates.yaml", "renew_days_before: 14\nwarn_channel: platform-team\n"),
    ),
    (
        "infra-config",
        "Alerts not reaching on-call",
        "Send production alerts to the pager again",
        "heads up: alerts from production haven't been paging on-call since yesterday",
        (
            "alerts.yaml",
            "production:\n  page: on-call\n  notify: incidents\nstaging:\n  notify: platform-team\n",
        ),
    ),
)

TYPO_SWAPS = (
    ("the", "teh"),
    ("because", "becuase"),
    ("tomorrow", "tommorow"),
    ("definitely", "definately"),
    ("receive", "recieve"),
    ("separate", "seperate"),
)
