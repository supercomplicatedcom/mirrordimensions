# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Text pools for the synthetic company: issues, comments and chat, industry-neutral."""

from __future__ import annotations

ISSUES: dict[str, tuple[tuple[str, str, tuple[str, ...]], ...]] = {
    "billing-service": (
        (
            "Invoice total is off by one cent on multi-line discounts",
            (
                "Seen on 14 accounts last month. Rounding happens per line in billing/invoice.py "
                "but the discount is applied to the subtotal, so the two disagree."
            ),
            ("bug",),
        ),
        (
            "Add a credit note for partial refunds",
            (
                "Support currently issues a full refund and re-bills the difference by hand. We "
                "need a credit note linked to the original invoice."
            ),
            ("enhancement",),
        ),
        (
            "Payment retry runs twice for failed card charges on Mondays",
            (
                "The retry job fires from both the old cron entry and the new scheduler. Roughly "
                "40 customers got two retry emails last week."
            ),
            (
                "bug",
                "incident",
            ),
        ),
        (
            "Investigate slow invoice PDF generation for accounts with 200+ line items",
            (
                "Rendering takes about 25 seconds and the worker times out. Probably the per-line "
                "font loading."
            ),
            ("performance",),
        ),
        (
            "Should annual plans prorate on upgrade or at next renewal?",
            (
                "Finance and support gave different answers. Needs a decision before we touch the "
                "proration code."
            ),
            (
                "question",
                "needs-decision",
            ),
        ),
        (
            "Tax rate is not refreshed after a customer changes billing country",
            (
                "The old rate sticks until the next invoice cycle. Reproduce by changing the "
                "country on an account with a draft invoice."
            ),
            ("bug",),
        ),
        (
            "Add retry backoff to the invoice email sender",
            (
                "Right now a bounced send is retried every minute for an hour. Move to exponential "
                "backoff and cap at 6 attempts."
            ),
            ("enhancement",),
        ),
        (
            "Refund API returns 500 when the invoice has already been fully credited",
            (
                "Expected a 409 with a readable message. The stack trace points at "
                "billing/invoice.py around the credit lookup."
            ),
            ("bug",),
        ),
        (
            "Document the invoice numbering scheme in CHANGELOG.md",
            (
                "Nobody remembers when we switched from the yearly prefix to the continuous "
                "counter. Worth a short entry."
            ),
            ("docs",),
        ),
        (
            "Pin requirements.txt versions for the PDF library",
            (
                "A minor release changed the default margins and every invoice shifted by 4mm. Pin "
                "it and add a note."
            ),
            ("chore",),
        ),
        (
            "Currency rounding differs between preview and final invoice",
            (
                "The preview page rounds half up, the final render uses banker's rounding. "
                "Customers notice when the numbers move."
            ),
            ("bug",),
        ),
        (
            "Add unit tests covering tax-exempt accounts",
            (
                "Coverage for the exempt path is basically missing. Start with one account that "
                "has a valid certificate on file."
            ),
            (
                "good-first-issue",
                "task",
            ),
        ),
        (
            "Discount codes should be case insensitive",
            'A customer typed SPRING10 in lowercase and got "invalid code". Normalise on input.',
            (
                "bug",
                "good-first-issue",
            ),
        ),
        (
            "Investigate duplicate invoices created on the first of the month",
            (
                "Found 6 duplicates in the November run, all for accounts that changed plan within "
                "the previous 24 hours."
            ),
            (
                "bug",
                "incident",
            ),
        ),
        (
            "Can we stop sending the invoice email as both HTML and plain text?",
            "The plain text version is out of date and nobody reads it. Asking before I remove it.",
            ("question",),
        ),
        (
            "Proration on mid-cycle downgrade uses the wrong day count",
            (
                "Months with 31 days are charged as if they had 30. Spotted by finance on the "
                "October close."
            ),
            ("bug",),
        ),
        (
            "Move default settings out of config/settings.py into environment variables",
            (
                "Three values are hard coded and differ between staging and production. Should be "
                "read from the environment at startup."
            ),
            ("chore",),
        ),
        (
            "Add a dry-run flag to the month-end billing job",
            "Finance wants to see totals before anything is sent. A report to stdout is enough.",
            ("enhancement",),
        ),
        (
            "Credit balance is not shown on the PDF invoice",
            (
                "Customers with a credit see the full amount due and then get a confusing email. "
                "Print the balance line when it is above zero."
            ),
            ("bug",),
        ),
        (
            "Invoice date shows UTC instead of the customer's timezone",
            (
                "Customers in Australia see the invoice dated the day before. Display only, stored "
                "value is fine."
            ),
            ("bug",),
        ),
        (
            "Audit logging for manual invoice edits",
            (
                "We cannot tell who changed a total after issue. Add a record with user, old value "
                "and new value."
            ),
            (
                "enhancement",
                "security",
            ),
        ),
        (
            "Write a runbook for a stuck billing run",
            (
                "Last time it took three people and half a day. Put the steps in the handbook once "
                "we agree on them."
            ),
            (
                "docs",
                "task",
            ),
        ),
        (
            "Late fee calculation ignores the grace period setting",
            (
                "The setting exists but is only read for monthly plans. Annual plans are charged "
                "from day one."
            ),
            ("bug",),
        ),
        (
            "Support multiple tax IDs per account",
            (
                "A handful of EU customers have separate IDs per subsidiary. Currently only one is "
                "stored and printed."
            ),
            ("enhancement",),
        ),
        (
            "Failed payment emails go out at 3am local time",
            "Schedule them for business hours in the customer's timezone.",
            ("enhancement",),
        ),
        (
            "Why does the nightly reconcile skip invoices under 1.00?",
            "Found a comment saying it is intentional, but no explanation. Anyone remember?",
            ("question",),
        ),
        (
            "Voided invoices still appear in the accounts receivable export",
            "Finance filters them by hand every week. The export should exclude status void.",
            ("bug",),
        ),
        (
            "Add a unique constraint on invoice number per account",
            "We found two rows with the same number while debugging the November duplicates.",
            (
                "task",
                "bug",
            ),
        ),
        (
            "Handle zero-amount invoices without sending an email",
            (
                "Free trial conversions generate an invoice for 0.00 and a confusing email. "
                "Suppress the send."
            ),
            ("enhancement",),
        ),
        (
            "Upgrade the PDF library to the latest minor release",
            (
                "Current version is 18 months old and has an open advisory for malformed fonts. "
                "Check the rendering diff first."
            ),
            (
                "chore",
                "security",
            ),
        ),
        (
            "Refund reason is optional but the report assumes it is set",
            (
                "The weekly refunds report crashes on null reasons. Either require it or default "
                'to "unspecified".'
            ),
            ("bug",),
        ),
        (
            'Rename "adjustment" to "credit" in customer-facing text',
            "Support keeps explaining the difference. Copy only, no data changes.",
            (
                "docs",
                "good-first-issue",
            ),
        ),
        (
            "Discount stacking order is undocumented",
            (
                "Percentage then fixed, or fixed then percentage? The result differs by up to 3 "
                "percent. Please document and fix if needed."
            ),
            (
                "question",
                "docs",
            ),
        ),
        (
            "Expose the invoice due date in the API response",
            "Two integrations parse it out of the PDF. Add due_date to the JSON.",
            ("enhancement",),
        ),
        (
            "Batch payment retries to avoid hitting the card processor rate limit",
            "We got throttled on the 3rd for about 20 minutes. Spread retries across the hour.",
            ("performance",),
        ),
        (
            "Customer with an annual plan was charged monthly after a card update",
            (
                "Account was moved to the monthly schedule when the card was replaced. Needs a "
                "look at the plan reassignment code."
            ),
            (
                "bug",
                "incident",
            ),
        ),
        (
            "Add a changelog entry for each tax table update",
            (
                "Tax table changes are invisible in the history. A line in CHANGELOG.md per update "
                "would help the auditors."
            ),
            ("chore",),
        ),
        (
            "Remove the unused legacy invoice template",
            (
                "Nothing has rendered it since the spring. Delete it and the two fixtures that "
                "still reference it."
            ),
            ("chore",),
        ),
        (
            "Reminder emails are sent for invoices paid by bank transfer the same day",
            "Reconciliation runs at 6am, reminders at 5am. Swap the order or add a same-day check.",
            ("bug",),
        ),
        (
            "Add a per-account billing contact separate from the login email",
            "Several customers want invoices sent to an accounts payable address.",
            (
                "enhancement",
                "needs-decision",
            ),
        ),
    ),
    "platform-docs": (
        (
            "Update docs/oncall.md with the new escalation order",
            (
                "The secondary now comes before the engineering manager. The handbook still shows "
                "the old order."
            ),
            ("docs",),
        ),
        (
            "Add a section on rotating the pager tool schedule",
            "Currently one person edits the schedule from memory. Write down the steps.",
            (
                "docs",
                "task",
            ),
        ),
        (
            "docs/rotating-credentials.md is missing the warehouse service account",
            (
                "Rotation steps cover production Postgres and the portal but not the reporting "
                "warehouse reader."
            ),
            (
                "docs",
                "security",
            ),
        ),
        (
            "Clarify who approves production access requests in docs/access.md",
            'The page says "a manager" without saying which one. Two requests sat for a week.',
            (
                "docs",
                "question",
            ),
        ),
        (
            "Write a one-page onboarding checklist for new engineers",
            (
                "First week: laptop, VPN, repo access, chat channels, on-call shadowing. Keep it "
                "short."
            ),
            (
                "docs",
                "good-first-issue",
            ),
        ),
        (
            "Document the release freeze before holidays in docs/releases.md",
            "Nobody knew the freeze started on the 18th. Add the dates and the exception process.",
            ("docs",),
        ),
        (
            "Add a runbook for restoring a Postgres snapshot into staging",
            "Needed it twice this year and had to ask in chat both times.",
            (
                "docs",
                "task",
            ),
        ),
        (
            "Broken link to the VPN setup guide in the handbook",
            "The link points at a page that was moved. Found while onboarding someone on Tuesday.",
            (
                "docs",
                "bug",
            ),
        ),
        (
            "docs/oncall.md says pager hours are 9 to 5 but the rota covers nights",
            "Confusing for people joining the rota. Clarify the hours and the handoff time.",
            ("docs",),
        ),
        (
            "Add a glossary of internal service names",
            "New joiners ask what the portal, the warehouse and the billing service each do.",
            (
                "docs",
                "enhancement",
            ),
        ),
        (
            "Explain how to request a new shared mailbox",
            "The process changed in September. Current text still says to email IT.",
            ("docs",),
        ),
        (
            "What is the retention period for chat history?",
            "Someone asked in support. I could not find it in the handbook.",
            ("question",),
        ),
        (
            "Add a page on how code review works here",
            (
                "Who reviews what, how long we aim to take, when to merge. Pull from what we "
                "already do."
            ),
            (
                "docs",
                "enhancement",
            ),
        ),
        (
            "Outdated screenshots in the laptop setup page",
            "The VPN client UI has changed twice since these were taken.",
            (
                "docs",
                "good-first-issue",
            ),
        ),
        (
            "Document the process for adding a new repository",
            (
                "Naming, branch protection, CI template, default reviewers. Currently tribal "
                "knowledge."
            ),
            (
                "docs",
                "task",
            ),
        ),
        (
            "Add the weekly release calendar to docs/releases.md",
            'Releases go out Tuesday and Thursday. The page only says "regularly".',
            ("docs",),
        ),
        (
            "Describe what to do when you lose your laptop",
            "Who to tell, how to revoke access, what gets wiped. Security asked for this.",
            (
                "docs",
                "security",
            ),
        ),
        (
            "Where do incident write-ups live?",
            "We have three folders that look similar. Pick one and say so in the handbook.",
            (
                "question",
                "needs-decision",
            ),
        ),
        (
            "Handbook search returns pages from the old wiki",
            "Probably an indexing leftover. Needs someone to check what is still published.",
            (
                "bug",
                "chore",
            ),
        ),
        (
            "Add expense policy summary for contractors",
            "Contractors ask what they can claim. Link to the policy and give three common cases.",
            ("docs",),
        ),
        (
            "Write down how secrets are shared between teammates",
            "People still paste credentials in chat. Document the approved way.",
            (
                "docs",
                "security",
            ),
        ),
        (
            "Typo in the access request template",
            '"Justifcation" appears twice. Trivial but visible.',
            (
                "docs",
                "good-first-issue",
            ),
        ),
        (
            "Add a page on how to read the pager tool alerts",
            "New on-call engineers do not know the difference between a page and a notification.",
            ("docs",),
        ),
        (
            "Document the staging refresh schedule",
            (
                "Staging data is refreshed Sundays at 2am. Several people were surprised when "
                "their data vanished."
            ),
            ("docs",),
        ),
        (
            "Add a table of who owns which service",
            "Needed during incidents and always out of date. Include a last-reviewed date.",
            (
                "docs",
                "task",
            ),
        ),
        (
            "docs/access.md should list the standard roles",
            "Read-only, developer, admin. And what each one can do in production.",
            ("docs",),
        ),
        (
            "Remove references to the retired status page",
            "Three pages still link to it. Replace with the current one.",
            (
                "docs",
                "chore",
            ),
        ),
        (
            "Document the on-call compensation policy",
            "HR confirmed the numbers. We just need to publish them in docs/oncall.md.",
            ("docs",),
        ),
        (
            "Add a checklist for leaving the company",
            "Offboarding steps for managers: access, laptop, pager rota, shared documents.",
            (
                "docs",
                "task",
            ),
        ),
        (
            "Handover template for end of on-call week",
            (
                "People write it differently each time. Propose a short format and put it in the "
                "handbook."
            ),
            (
                "enhancement",
                "docs",
            ),
        ),
        (
            "Explain how to get a new VPN profile",
            "The old guide mentions a client we no longer use.",
            (
                "docs",
                "bug",
            ),
        ),
        (
            "Do we still need the page about the old build server?",
            "It was switched off in the summer. I would delete it, but wanted to ask.",
            ("question",),
        ),
        (
            "Add rollback steps to docs/releases.md",
            "The page covers shipping but not undoing. Include the command and who to tell.",
            ("docs",),
        ),
        (
            "Document how to request a temporary production database role",
            "Time-boxed access for debugging, with approval and an expiry.",
            (
                "docs",
                "security",
            ),
        ),
        (
            "Style guide for runbooks",
            "Some start with commands, others with background. Agree on one structure.",
            (
                "docs",
                "needs-decision",
            ),
        ),
        (
            "Add a section about working across time zones",
            "We now have people in three time zones. Cover core hours and meeting etiquette.",
            ("docs",),
        ),
        (
            "Link the quarterly access review checklist from docs/access.md",
            "Security runs it every quarter and the page is hard to find.",
            (
                "docs",
                "chore",
            ),
        ),
        (
            "Rotate the shared credentials list after the last offboarding",
            (
                "The checklist in docs/rotating-credentials.md was not followed fully. Track what "
                "is still open."
            ),
            (
                "task",
                "security",
            ),
        ),
    ),
    "data-pipeline": (
        (
            "Nightly load from production Postgres finished two hours late on Monday",
            (
                "Started at the usual 1am but the orders table took 3 hours instead of 1. Probably "
                "the long vacuum that ran in parallel."
            ),
            (
                "incident",
                "performance",
            ),
        ),
        (
            "Add a backfill option for the invoices table",
            (
                "Finance needs three months reloaded after the rounding fix. Today we have to run "
                "SQL by hand."
            ),
            ("enhancement",),
        ),
        (
            "Dashboard for monthly recurring revenue is missing the last day of the month",
            "Looks like the cutoff uses UTC midnight and the report expects local time.",
            ("bug",),
        ),
        (
            "Investigate duplicated rows in the accounts dimension",
            "About 120 accounts appear twice after the schema change on the 9th.",
            ("bug",),
        ),
        (
            "Schema change on the customers table broke the nightly job",
            (
                "A new nullable column was added upstream and the loader fails on unknown fields. "
                "Make the loader tolerant."
            ),
            (
                "bug",
                "incident",
            ),
        ),
        (
            "Schedule the weekly summary load for Sunday evening",
            "Currently runs Monday at 6am, which is too late for the Monday morning meeting.",
            ("enhancement",),
        ),
        (
            "Why does the load skip rows with a null updated_at?",
            "Some older accounts have no value there and never get refreshed. Is that intended?",
            ("question",),
        ),
        (
            "Reduce the nightly load window from 3 hours to under 90 minutes",
            (
                "Use incremental loads for the three biggest tables. Estimated saving about 40 "
                "percent."
            ),
            (
                "performance",
                "enhancement",
            ),
        ),
        (
            "Alert when the nightly load has not finished by 6am",
            "We only find out when someone opens a dashboard. Send a message to the data channel.",
            ("enhancement",),
        ),
        (
            "Document the table naming convention in the warehouse",
            "Some tables use plural names and some singular. Pick one and write it down.",
            (
                "docs",
                "needs-decision",
            ),
        ),
        (
            "Fix timezone handling for the support tickets feed",
            "Tickets created after 11pm show on the next day in the weekly report.",
            ("bug",),
        ),
        (
            "Add row count checks after each load step",
            "If a table loads with zero rows we should fail, not carry on.",
            ("enhancement",),
        ),
        (
            "Archive warehouse tables older than 24 months",
            "Storage is growing about 8 percent per quarter. Needs a retention decision first.",
            (
                "needs-decision",
                "chore",
            ),
        ),
        (
            "Backfill failed halfway through the invoices table",
            "The second chunk timed out and the job did not resume. Need checkpointing.",
            ("bug",),
        ),
        (
            "The revenue dashboard and the finance spreadsheet disagree by 0.3 percent",
            (
                "Narrowed it down to refunds issued after the cutoff. Looking for the owner of the "
                "dashboard query."
            ),
            (
                "question",
                "bug",
            ),
        ),
        (
            "Rename the staging schema in the warehouse",
            "It is called temp but production reports read from it. Rename to something accurate.",
            ("chore",),
        ),
        (
            "Make the loader idempotent",
            (
                "Running it twice for the same date should give the same result. Right now it "
                "duplicates rows."
            ),
            (
                "bug",
                "enhancement",
            ),
        ),
        (
            "Upgrade the warehouse client library",
            "Current version drops connections after 30 minutes on long queries.",
            ("chore",),
        ),
        (
            "Add a data dictionary for the customers dimension",
            "Analysts ask what each column means every other week.",
            ("docs",),
        ),
        (
            "Add column-level lineage notes to the README",
            "Where does the account status come from, and which jobs touch it?",
            ("docs",),
        ),
        (
            "Investigate why the Friday load takes longer than other days",
            "Consistently 30 minutes slower. Might be the weekly export running at the same time.",
            ("performance",),
        ),
        (
            "Handle deleted accounts in the nightly sync",
            (
                "Deleted rows in Postgres stay in the warehouse forever. We need soft deletes or a "
                "purge step."
            ),
            (
                "bug",
                "needs-decision",
            ),
        ),
        (
            "Reports break when a column is renamed upstream",
            "Add a contract check so schema changes are flagged before the load.",
            ("enhancement",),
        ),
        (
            "Add retries around the Postgres read replica connection",
            (
                "A brief network blip failed the whole job on the 14th. Retry three times with a "
                "short delay."
            ),
            ("bug",),
        ),
        (
            "Pause the nightly job during the planned database maintenance",
            "The window is Saturday 1 to 3am. Add a skip rule so we do not get a false alert.",
            ("task",),
        ),
        (
            "Dashboards show stale data after daylight saving change",
            "Cached results use the old offset for a week.",
            ("bug",),
        ),
        (
            "Move warehouse credentials to the secrets manager",
            (
                "Currently in an environment file on the job host. Security flagged it in the last "
                "review."
            ),
            (
                "security",
                "chore",
            ),
        ),
        (
            "How do we handle late-arriving invoice updates?",
            (
                "An invoice edited three days after issue is not picked up by the incremental "
                "load. Looking for opinions."
            ),
            (
                "question",
                "needs-decision",
            ),
        ),
        (
            "Add a freshness indicator to the main dashboard",
            "Show when the data was last loaded, so people stop asking in chat.",
            (
                "enhancement",
                "good-first-issue",
            ),
        ),
        (
            "Clean up unused tables in the reporting schema",
            (
                "Found 31 tables with no reads in 6 months. List them in the issue and check with "
                "owners."
            ),
            ("chore",),
        ),
        (
            "Parallelise the customer events load",
            "It is single-threaded and by far the slowest step. Try 4 workers.",
            ("performance",),
        ),
        (
            "Failed load notifications go to a channel nobody reads",
            "Point them at the data team channel and add the on-call person.",
            ("bug",),
        ),
        (
            "Document how to run the pipeline locally",
            (
                "The README stops at installing dependencies. Needs steps for the local database "
                "and a small data set."
            ),
            ("docs",),
        ),
        (
            "Row counts in the warehouse differ from Postgres by 17 on the orders table",
            "Persistent since the weekend. Likely rows updated during the load window.",
            ("bug",),
        ),
        (
            "Add support for loading a single date range",
            "Useful for fixes. Today the job always loads from the last watermark.",
            ("enhancement",),
        ),
        (
            "Decide whether to keep the old weekly export",
            "Three recipients, no clear owner. Ask finance if they still use it.",
            (
                "question",
                "needs-decision",
            ),
        ),
        (
            "Standardise job names in the scheduler",
            "Some are snake case, some have dates in the name. Makes alerts hard to read.",
            ("chore",),
        ),
        (
            "Reconcile the customer count between the portal and the warehouse",
            "Portal says 1,942 active accounts, warehouse says 1,951.",
            (
                "bug",
                "task",
            ),
        ),
        (
            "Add a smoke check that runs after each deploy of the pipeline",
            "Query one known table and check it returns rows. Cheap and catches the obvious.",
            ("enhancement",),
        ),
        (
            "Compress the nightly export files",
            "They are 2.4 GB each and uploaded uncompressed.",
            (
                "performance",
                "good-first-issue",
            ),
        ),
    ),
    "infra-config": (
        (
            "Increase billing-service replicas to 4 in production",
            (
                "The 9am spike leaves two replicas above 80 percent CPU. Change in "
                "environments/production.yaml."
            ),
            (
                "enhancement",
                "performance",
            ),
        ),
        (
            "Staging has the old log retention setting",
            (
                "Staging keeps logs for 90 days, production for 30. Make them match in "
                "environments/staging.yaml."
            ),
            ("chore",),
        ),
        (
            "Alert threshold for disk usage is too sensitive",
            (
                "Fires at 70 percent on the database host and nobody acts until 85. Raise to 80 "
                "and add a second tier."
            ),
            ("enhancement",),
        ),
        (
            "Add a second region for the customer portal",
            "Needs a decision on cost and failover plan before we write any config.",
            (
                "needs-decision",
                "enhancement",
            ),
        ),
        (
            "Secrets in environments/staging.yaml should reference the secrets manager",
            "Three values are pasted in plain text. Replace with references and rotate them.",
            (
                "security",
                "bug",
            ),
        ),
        (
            "Document the environment variables used by the portal",
            "Names are scattered across the YAML. Collect them in one table.",
            ("docs",),
        ),
        (
            "Staging uses a smaller database instance than production, is that deliberate?",
            "It makes load comparisons unreliable. Asking before I change anything.",
            ("question",),
        ),
        (
            "Pager alert for failed backups is not routed to the platform rota",
            "It goes to the old shared mailbox. Update the routing in the alert config.",
            (
                "bug",
                "incident",
            ),
        ),
        (
            "Reduce log verbosity for the invoice workers",
            "Debug logging was left on after the last investigation. We are paying for the volume.",
            (
                "chore",
                "performance",
            ),
        ),
        (
            "Add health check endpoints to the shared services config",
            "Two services have none and the load balancer cannot tell if they are up.",
            ("enhancement",),
        ),
        (
            "Set memory limits on the reporting workers",
            "One run used 11 GB and the host started swapping.",
            (
                "bug",
                "performance",
            ),
        ),
        (
            "Move the environment YAML into a template",
            "The production and staging files are 90 percent the same. Use one base and overrides.",
            (
                "chore",
                "enhancement",
            ),
        ),
        (
            "Add an alert for certificate expiry under 21 days",
            "We found out about the last one from a customer.",
            (
                "enhancement",
                "security",
            ),
        ),
        (
            "Staging deploys fail if the replica count is set to 1",
            "The rolling update waits for a second replica that never appears.",
            ("bug",),
        ),
        (
            "Document how to add a new service to environments/production.yaml",
            "Right now you copy another block and hope.",
            ("docs",),
        ),
        (
            "Stop writing application logs to local disk on the web hosts",
            "The disk filled up twice. Ship them out and keep a small local buffer.",
            (
                "bug",
                "chore",
            ),
        ),
        (
            "Use the same time zone setting across all hosts",
            "Some are on UTC and some on local time. Logs are hard to correlate.",
            ("chore",),
        ),
        (
            "Review the autoscaling thresholds for the portal",
            "Scale up at 60 percent CPU and down at 25 is flapping every 10 minutes.",
            ("performance",),
        ),
        (
            "Add a staging copy of the pager integration",
            "We cannot rehearse alert routing changes without paging a real person.",
            ("enhancement",),
        ),
        (
            "Review the IAM roles used by CI",
            "Several have broader access than needed. List what each pipeline actually calls.",
            (
                "security",
                "task",
            ),
        ),
        (
            "Backup retention for the production database should be 35 days",
            "It is 14 in the config. The policy says 35.",
            (
                "bug",
                "security",
            ),
        ),
        (
            "Tag all resources with an owner and cost centre",
            (
                "Finance asked for a cost breakdown by team and about 30 percent of resources have "
                "no tags."
            ),
            (
                "chore",
                "task",
            ),
        ),
        (
            "Roll the shared services to the new base image",
            "Current image has 12 outstanding advisories. Start with staging.",
            (
                "security",
                "chore",
            ),
        ),
        (
            "Make log format consistent between services",
            "Some emit JSON, some plain text. Parsing in the dashboards breaks on the plain ones.",
            ("enhancement",),
        ),
        (
            "Why is the connection pool size 5 for the billing workers?",
            "It looks low for the traffic. Checking whether there was a reason.",
            ("question",),
        ),
        (
            "Add maintenance window to the config for the Postgres hosts",
            "The window is currently set in the console and not in code.",
            ("chore",),
        ),
        (
            "Cleanup of old security groups in us-east-1",
            "Found 22 with no attached resources. List them here before deleting.",
            (
                "chore",
                "security",
            ),
        ),
        (
            "Alert routing for the warehouse load goes to the wrong channel",
            "Update the destination and add the data team rota.",
            ("bug",),
        ),
        (
            "Add rate limits on the portal login endpoint config",
            "Currently relies on the application. Add a limit at the load balancer as well.",
            (
                "security",
                "enhancement",
            ),
        ),
        (
            "Production and staging use different Python minor versions",
            "3.11 in one and 3.12 in the other. Align them.",
            ("chore",),
        ),
        (
            "Rotate the staging database password",
            "It was shared in a thread last quarter. Follow docs/rotating-credentials.md.",
            (
                "security",
                "task",
            ),
        ),
        (
            "Document the rollback process for config changes",
            "A bad change to environments/production.yaml took 40 minutes to revert.",
            (
                "docs",
                "incident",
            ),
        ),
        (
            "Add a dashboard for queue depth on the invoice workers",
            "We look at raw numbers in the console today.",
            ("enhancement",),
        ),
        (
            "Reduce alert noise from the nightly job host",
            "14 alerts last week, 11 were the same disk warning. Deduplicate.",
            ("chore",),
        ),
        (
            "Set up a read replica for reporting queries",
            (
                "The warehouse load and the support tooling compete with production. Estimate cost "
                "first."
            ),
            (
                "needs-decision",
                "performance",
            ),
        ),
        (
            "Enforce encryption at rest on new storage buckets",
            "Add a default in the config and fail the deploy if it is missing.",
            (
                "security",
                "enhancement",
            ),
        ),
        (
            "Shorten the request timeout for the portal upstream",
            "It is 120 seconds. Anything over 30 is already a failure.",
            (
                "performance",
                "bug",
            ),
        ),
        (
            "Add a readme to the environments folder",
            "Explain what each file is for and how changes get applied.",
            (
                "docs",
                "good-first-issue",
            ),
        ),
        (
            "Verify the DNS TTL values before the next migration",
            "Some records have 24 hour TTLs, which will slow the cutover.",
            ("task",),
        ),
    ),
    "customer-portal": (
        (
            "Login page fails with a blank screen on older Safari versions",
            (
                "Reported by three customers this week. The console shows a syntax error from the "
                "bundled script."
            ),
            ("bug",),
        ),
        (
            "Invoice download button does nothing on mobile",
            "Tested on two phones. The request is sent but the file never opens.",
            ("bug",),
        ),
        (
            "Add a way to update the billing email without contacting support",
            "Eleven support requests last month were just this.",
            ("enhancement",),
        ),
        (
            "Account page takes over 6 seconds to load for accounts with many users",
            "The list is loaded without pagination. Accounts with 300 or more users are affected.",
            (
                "performance",
                "bug",
            ),
        ),
        (
            "Improve keyboard navigation on the account settings page",
            "Tab order skips the save button. Raised by an accessibility review.",
            (
                "enhancement",
                "good-first-issue",
            ),
        ),
        (
            "Password reset email arrives after 10 minutes",
            "Customers retry and then use an older link. Check the mail queue.",
            (
                "bug",
                "incident",
            ),
        ),
        (
            "Support request form loses the attachment on validation errors",
            "User fills the form, hits submit with a missing field, the file is gone.",
            ("bug",),
        ),
        (
            "Add a download all invoices as a zip option",
            "Customers with annual history ask for it often. Cap at 12 months.",
            ("enhancement",),
        ),
        (
            "Colour contrast on the status badges fails the accessibility check",
            "Light grey on white. Needs a darker shade.",
            (
                "bug",
                "good-first-issue",
            ),
        ),
        (
            "Session expires after 15 minutes without a warning",
            "Customers lose unsaved changes. Show a notice 2 minutes before.",
            ("enhancement",),
        ),
        (
            "Reduce the size of the main JavaScript bundle",
            "It is 1.8 MB. Split the account pages from the invoices pages.",
            ("performance",),
        ),
        (
            "Show the next invoice date on the dashboard",
            "A number of customers ask when they will be charged next.",
            ("enhancement",),
        ),
        (
            "Why does the portal log users out when they switch tabs?",
            "Seen in one browser only, could be a cookie issue.",
            (
                "question",
                "bug",
            ),
        ),
        (
            "Add two-factor authentication option for customer admins",
            "A few larger accounts require it. Check what the identity provider supports.",
            (
                "enhancement",
                "security",
            ),
        ),
        (
            "Error message on failed login is too generic",
            'It says "something went wrong" for locked accounts and wrong passwords alike.',
            ("bug",),
        ),
        (
            "Add alt text to the invoice icons",
            'Screen reader users hear "image".',
            (
                "bug",
                "good-first-issue",
            ),
        ),
        (
            "Invoice table is not sortable by date",
            "Customers have to scroll through years of history.",
            ("enhancement",),
        ),
        (
            "Page title is the same on every page",
            "Makes browser history and tabs hard to use.",
            (
                "bug",
                "good-first-issue",
            ),
        ),
        (
            "Fix layout of the support form on narrow screens",
            "Labels overlap the inputs below 380 pixels.",
            ("bug",),
        ),
        (
            "Add a link to the status page in the portal footer",
            'Support gets asked "is it down?" a few times a week.',
            ("enhancement",),
        ),
        (
            "Customers are shown prices in the wrong currency after switching language",
            "Currency is tied to locale in one place and to account in another.",
            ("bug",),
        ),
        (
            "Portal returns a 502 for about 30 seconds on every deploy",
            "Health check passes before the app is ready. Look at the readiness settings.",
            (
                "bug",
                "incident",
            ),
        ),
        (
            "Add a confirmation step before closing an account",
            "One customer closed theirs by mistake and we had to restore it.",
            ("enhancement",),
        ),
        (
            "Remove the unused legacy dashboard route",
            "It still renders for anyone who has the old link and shows stale numbers.",
            ("chore",),
        ),
        (
            "Allow customers to add a purchase order number to an invoice",
            "Requested by procurement teams. A free text field is enough.",
            ("enhancement",),
        ),
        (
            "Search in the support history only matches the subject",
            "Customers expect it to look in the message body too.",
            ("enhancement",),
        ),
        (
            "Date format in the account page ignores locale",
            "A customer in the UK sees month first.",
            ("bug",),
        ),
        (
            "Download link for invoices expires after 5 minutes",
            "Customers opening it from an email are told the link is invalid. Extend to 24 hours.",
            ("bug",),
        ),
        (
            "Add loading skeletons to the invoices list",
            "The page looks empty for 2 seconds.",
            (
                "enhancement",
                "good-first-issue",
            ),
        ),
        (
            "Investigate intermittent 429 responses on the account API",
            'A few customers see "too many requests" without doing anything unusual.',
            (
                "bug",
                "performance",
            ),
        ),
        (
            "Update the cookie banner wording",
            "Legal has new text. Change only the copy.",
            (
                "docs",
                "task",
            ),
        ),
        (
            "Make focus visible on all interactive elements",
            "The default outline was removed in the last redesign.",
            (
                "bug",
                "good-first-issue",
            ),
        ),
        (
            (
                "Customer cannot change their plan from the portal on a legacy browser "
                "compatibility mode"
            ),
            "Rare but a couple of enterprise users do this. Decide whether we support it.",
            (
                "needs-decision",
                "question",
            ),
        ),
        (
            "Reduce time to first byte on the login page",
            "It is 1.2 seconds. The session lookup is the main cost.",
            ("performance",),
        ),
        (
            "Add a printable invoice view",
            "Customers print from the browser and lose half the page.",
            ("enhancement",),
        ),
        (
            "Handle special characters in company names on invoices",
            "An ampersand shows as the raw code in the header.",
            ("bug",),
        ),
        (
            "Rate limit the support request endpoint",
            "One account sent 400 requests in an hour from a script.",
            (
                "security",
                "enhancement",
            ),
        ),
        (
            "Document the portal release process in the repository",
            "The README does not say how to deploy or roll back.",
            ("docs",),
        ),
        (
            "Show a clearer message when the account is overdue",
            "Today the page just hides the upgrade button.",
            ("enhancement",),
        ),
        (
            "Language switcher resets to English on every page load",
            "Preference is stored but never read back.",
            ("bug",),
        ),
        (
            "Collapse the invoice details on small screens",
            "Too much scrolling.",
            ("enhancement",),
        ),
        (
            "Check why the portal image uploads fail over 4 MB",
            "Limit seems to be hit before the documented 10 MB.",
            ("bug",),
        ),
    ),
    "ops-scripts": (
        (
            "Is cleanup-old-logs.sh still used?",
            "It was written for the old build server. I cannot find any cron entry that calls it.",
            ("question",),
        ),
        (
            "Can we delete restart-workers.sh?",
            "It restarts a service that was replaced in the summer. Checking before removal.",
            (
                "question",
                "chore",
            ),
        ),
        (
            "Who owns the rotate-backups script?",
            "It still runs on one host and the author left last year.",
            (
                "question",
                "needs-decision",
            ),
        ),
    ),
}

COMMENTS: tuple[str, ...] = (
    "Thanks, picking this up.",
    "I can reproduce this on staging.",
    "Not able to reproduce, can you share the account id?",
    "Looks like the same root cause as the one from last month.",
    "Can we get a rough estimate before the next planning?",
    "I think this is lower priority than the portal work, but happy to be told otherwise.",
    "Moving this to next sprint, we are full this week.",
    "Fixed in the latest release, please confirm on your side.",
    "This should be fixed after Thursday's deploy.",
    "Merged, closing once it has been live for a day.",
    "Added a regression check so it does not come back.",
    "Opened a draft pull request, early feedback welcome.",
    "I left some comments on the pull request.",
    "Needs a bit more detail before I can start. What did the customer actually see?",
    "Linking the discussion from the engineering channel, we went back and forth there.",
    "Discussed in standup: we will take the smaller option first.",
    "Can you add a screenshot or a log line?",
    "+1, I hit this too yesterday.",
    "Is anyone already on this?",
    "I'll take it unless someone else has started.",
    "Not sure this is a bug, it might be working as designed. Checking with product.",
    "I would push back on this a little. It adds a lot of surface for a rare case.",
    "Agree with the proposal, let's go ahead.",
    "Let's park this until the quarter ends.",
    "Please add an owner, otherwise it will sit here.",
    "Updated the description with what we know so far.",
    "Support has three more reports since this was opened.",
    "Bumping this, it came up again on a customer call.",
    "Any update here? A customer is asking.",
    "Waiting on finance to confirm the expected behaviour.",
    "Waiting on a reply from the customer, will check back Monday.",
    "Asked in the platform channel, nobody there owns it.",
    "Tagging the on-call person in case this is still happening.",
    "This looks related to the change we shipped on Tuesday.",
    "Rolled back the config, will look at the cause next.",
    "Workaround for now: re-run it manually from the console.",
    "Workaround documented in the handbook, but it should still be fixed properly.",
    "Tried the obvious fix and it made it worse, reverting.",
    "I think the problem is in the retry logic, not where the stack trace points.",
    "Query plan looks fine, so it is probably the volume rather than the query.",
    "It only happens for accounts created before the migration.",
    "Checked 20 accounts and only two are affected.",
    "The numbers match what I see in the warehouse.",
    "Numbers do not match what I see in the warehouse, sending details in chat.",
    "Could we do this behind a setting first?",
    "Please don't merge before the release is cut.",
    "Sorry for the delay, was out last week.",
    "Short update: still investigating, nothing conclusive yet.",
    "Short update: have a fix, needs review.",
    "Ready for review.",
    "Reviewed, a couple of small things inline.",
    "Approved, one nit but not blocking.",
    "Rebased on main, tests are green again.",
    "Tests are failing on a unrelated job, rerunning.",
    "CI is red on the lint step, fixing.",
    "Thanks for the quick turnaround.",
    "Can someone from support confirm this wording?",
    "Needs a decision from the lead, adding to the agenda for Wednesday.",
    "I wrote up the options in the linked document.",
    "Option two is the cheapest, I would go with that.",
    "We tried that before and it caused trouble with the nightly job.",
    "Do we have any numbers on how often this happens?",
    "About 5 percent of accounts as far as I can tell.",
    "It's low volume but the customers who hit it are annoyed.",
    "Good catch, I missed that.",
    "Closing as a duplicate of the older issue.",
    "Reopening, it came back after the last deploy.",
    "Closing, nobody has hit this in two months.",
    "Could you take another look? I think the description is out of date.",
    "Updated the labels.",
    "Changed the title to be clearer.",
    "Assigning to myself for this week.",
    "Unassigning myself, I will not get to it before the holidays.",
    "Happy to pair on this if useful.",
    "I started on this but got pulled into something else, branch is pushed if anyone wants it.",
    "Docs updated in the same pull request.",
    "Can we add this to the release notes?",
    "This needs a note in the changelog.",
    "Is there a rollback plan if it goes wrong?",
    "Rollback is one command, written down in the runbook.",
    "I checked with security and they are fine with it.",
    "Security wants one more review before this goes out.",
    "Not urgent, but it would be nice to have before the audit.",
    "I'm going to timebox this to two days.",
    "That took longer than expected, the tests were the slow part.",
    "Deployed to staging, looks fine so far.",
    "Deployed to production, watching the dashboards.",
    "Deployed and verified with a real account, all good.",
    "Alert is quiet again after the change.",
    "We have seen it twice more since, same pattern.",
    "Thank you, that explains what we saw.",
    "Please ping me if the customer replies.",
    "I'll send the customer an update this afternoon.",
    "Customer confirmed it is working now.",
    "Customer is still seeing it, sending a screen recording.",
    "Can someone double check my reading of the code? I may be missing something.",
    "I am not convinced this is worth the effort, honestly.",
    "This seems like a good first issue for someone new.",
    "The fix is small, but the tests are going to be bigger.",
    "Opened a follow up for the cleanup so this one stays small.",
    "Fixes in a separate pull request, linking here.",
    "Lets discuss in the retro.",
    "Looks fine to me, nothing else from my side.",
    "Sory, I mixed up the account. Ignore my earlier comment.",
    "Teh problem seems to be in the date handling.",
    "Confirmed on prod as well, same behaviour.",
    "Not touching this until we agree on the approach.",
    "Noted. I'll write up the rest tomorrow morning.",
    "Has anyone talked to the customer about this yet?",
    "I suspect a cache is involved, clearing it fixed it for me.",
    "Started a thread in engineering about this, join in if you have opinions.",
)

CHAT: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "town-square": (
        (
            (
                "Reminder: the office is closed on {day} for the public holiday. Enjoy the long "
                "weekend."
            ),
            (
                (
                    "Thanks! Is the building access system still working for anyone coming in on "
                    "the weekend?"
                ),
                "Should be, security badge works 24/7 for anyone on the list.",
            ),
        ),
        (
            "All hands is moving to {time} on {day}. Calendar invites will update automatically.",
            (
                "Will there be a recording for people in other time zones?",
                "Yes, it goes in the shared drive the same afternoon.",
                "Great, I'll watch it later.",
            ),
        ),
        (
            (
                "Benefits enrolment closes at the end of next week. If you haven't picked a plan "
                "yet, please do it in the HR portal."
            ),
            (
                "Does the dental option change this year?",
                "Slightly, the premium is a bit lower. There's a comparison table on the HR page.",
            ),
        ),
        (
            (
                "Heads up: laptop OS updates are mandatory by {day}. It takes about 20 minutes, "
                "please restart when prompted."
            ),
            (
                "What happens if we miss the deadline?",
                (
                    "IT will nudge you a couple of times and then it forces the update overnight, "
                    "so better to pick your own time."
                ),
            ),
        ),
        (
            (
                "VPN maintenance tonight from 10pm to 11pm. You may be disconnected once, just "
                "reconnect."
            ),
            (
                "Does that include the staging network too?",
                "Yes, everything behind the VPN.",
            ),
        ),
        (
            "Welcome back {person}! Hope the time off was good.",
            (
                "Welcome back!",
                "Good to see you again.",
            ),
        ),
        (
            (
                "Expense reports for last month are due on {day}. Anything after that rolls into "
                "next month."
            ),
            (
                "Is there a template for the mileage claims?",
                'It\'s in the finance folder, "Mileage claim". Takes two minutes.',
            ),
        ),
        (
            (
                "The wifi on the third floor is flaky this morning. IT is looking at it, in the "
                "meantime try the guest network on the second floor."
            ),
            (
                "Seems fine for me now.",
                "Still dropping every few minutes on my side.",
                "Thanks, passing this on to IT.",
            ),
        ),
        (
            "Quick reminder that visitors need to be signed in at the front desk and wear a badge.",
            (),
        ),
        (
            (
                "Please don't prop open the fire door on the ground floor. The alarm has gone off "
                "twice this week."
            ),
            ("Oops, that was me carrying boxes. Sorry!",),
        ),
        (
            "New starters this week: please say hello to {person} who joins the team on {day}.",
            (
                "Welcome {person}!",
                "Welcome aboard, ask anything.",
            ),
        ),
        (
            "Parking permits for next quarter are available at reception.",
            (
                "Is there a waiting list for the underground spaces?",
                "Yes, ask at the front desk and they will add you.",
            ),
        ),
        (
            "The printer on the second floor is out of toner again. Facilities have been told.",
            ("Use the one on the third floor for now, it's got a full cartridge.",),
        ),
        (
            (
                "Annual security training is due by the end of the month. It's about 30 minutes in "
                "the learning portal."
            ),
            (
                "Do contractors need to do it too?",
                "Yes, same deadline.",
            ),
        ),
        (
            (
                "We are switching to a new expense tool in January. There will be a short "
                "walkthrough session before then."
            ),
            (),
        ),
        (
            (
                "Reminder to book desks for next week if you're coming in. The booking page closes "
                "at 6pm on {day}."
            ),
            (
                "Is the booking for the quiet zone separate?",
                "Same page, pick the zone from the dropdown.",
            ),
        ),
        (
            "Payroll runs a day early this month because of the holiday. No action needed.",
            (),
        ),
        (
            (
                "Office plants are being watered by facilities on Fridays. Please stop adding "
                "extra water, we have lost two."
            ),
            ("Ha, guilty.",),
        ),
        (
            (
                "Company holiday calendar for next year is now on the HR page. Please check the "
                "dates before booking travel."
            ),
            ("Thanks, just in time.",),
        ),
        (
            "The lifts are being serviced on {day} from 8am. Expect delays or use the stairs.",
            (),
        ),
        (
            (
                "Reminder: password manager changes. Please enable two-factor on your account "
                "before the end of the week."
            ),
            (
                "Where do I find the setting?",
                "Profile, then security. It takes a minute.",
            ),
        ),
        (
            "Lost and found box is at reception. There are three umbrellas and a scarf.",
            (),
        ),
        (
            (
                "The kitchen fridge gets cleared out on Friday afternoons. Please take your lunch "
                "containers home."
            ),
            (
                "What about the milk?",
                "That goes too if it's past the date.",
            ),
        ),
        (
            (
                "Fire drill planned for {day} around {time}. Please follow the instructions and "
                "head to the car park."
            ),
            (
                "Do remote people need to do anything?",
                "No, just office staff.",
            ),
        ),
        (
            "Good news: the quarterly numbers are in and we hit our target. More at the all hands.",
            (
                "Great work everyone.",
                "Nice, looking forward to the details.",
            ),
        ),
        (
            (
                "We are updating the company chat guidelines. The short version: use threads, keep "
                "channels on topic, be kind."
            ),
            (),
        ),
        (
            (
                "IT will be collecting old laptops on {day} at the front desk. If you have a spare "
                "one at home please bring it."
            ),
            (),
        ),
        (
            "Reminder that the office closes at 6pm on Friday for the cleaners.",
            (),
        ),
        (
            (
                "Please remember to lock your screen when you leave your desk. Security walked the "
                "floor last night and found four unlocked."
            ),
            (
                "Oops.",
                "Win+L is your friend.",
            ),
        ),
        (
            "Open enrolment webinar is today at {time}. A link is in the benefits email.",
            (),
        ),
        (
            "The new coffee supplier starts next week. Let us know what you think.",
            (
                "Is oat milk back?",
                "Yes, ordered a case.",
            ),
        ),
        (
            (
                "Bike storage in the basement is getting full. Please remove any bikes that are no "
                "longer used."
            ),
            (),
        ),
        (
            (
                "We have some desks free after the reshuffle. Anyone interested in moving closer "
                "to their team, tell facilities."
            ),
            (),
        ),
        (
            "Reminder to submit your timesheets before noon on {day}.",
            (),
        ),
        (
            (
                "Please don't use the meeting room by reception for calls longer than an hour, "
                "it's the only one the front desk can book for visitors."
            ),
            (),
        ),
        (
            "Happy {day}! Hope everyone has a nice week.",
            (),
        ),
        (
            (
                "Security notice: we've seen phishing emails pretending to be from the CEO asking "
                "for gift cards. Don't reply, forward to security."
            ),
            (
                "Got one yesterday, forwarded it.",
                "Thanks both, keep them coming.",
            ),
        ),
        (
            "The cafe downstairs is closed for refurbishment until the end of the month.",
            (
                "Where's the nearest alternative?",
                "The place across the street does a decent lunch deal.",
            ),
        ),
        (
            "Winter hours for the building start next Monday. Doors open at 7:30 and lock at 7pm.",
            (),
        ),
        (
            (
                "The sign-up sheet for the mentoring programme is now open. Reach out to HR if you "
                "want to be matched."
            ),
            (),
        ),
        (
            "Engineering will run a lunch and learn on {day} at {time}. Everyone is welcome.",
            (
                "What's the topic?",
                "How we do deploys. Short and non technical.",
            ),
        ),
        (
            "IT reminder: please don't plug personal USB drives into company laptops.",
            (),
        ),
        (
            (
                "The office will be closed between Christmas and New Year. Support cover details "
                "are on the HR page."
            ),
            (
                "Will chat be monitored?",
                "Only the on-call person, for emergencies.",
            ),
        ),
        (
            "Quarterly town hall slides are in the shared drive.",
            (),
        ),
        (
            (
                "Please complete the engagement survey by Friday. It's anonymous and takes about "
                "10 minutes."
            ),
            (
                "Is it really anonymous? Just checking.",
                "Yes, the tool only reports groups of five or more.",
            ),
        ),
        (
            "Meeting room 4 has a broken screen. Use room 5 until it's fixed.",
            (),
        ),
        (
            (
                "Reminder: new joiners get a 30 minute IT setup session at {time} on their first "
                "day. Please help them find the room."
            ),
            (),
        ),
        (
            (
                "Reception will be unstaffed on {day} afternoon. Visitors, please call the number "
                "on the door."
            ),
            (),
        ),
        (
            "There are free flu shots at the office on {day}. Sign up with HR.",
            (
                "Can I bring a partner?",
                "Not this time, employees only.",
            ),
        ),
        (
            (
                "We have a new recycling system on every floor. Labels are on the bins, ask "
                "facilities if unsure."
            ),
            (),
        ),
        (
            "Planned power work on the weekend. Please shut down your desktop machines on Friday.",
            (),
        ),
        (
            (
                "The company directory has been updated with desk locations. Let HR know if yours "
                "is wrong."
            ),
            (),
        ),
        (
            (
                "Facilities will be repainting the second floor on {day}. Please clear your desks "
                "by Friday evening."
            ),
            (
                "Will the desks be wiped down afterwards?",
                "Yes, cleaners come in after the painters.",
            ),
        ),
        (
            "The all hands recording from {day} is now in the shared drive.",
            (),
        ),
        (
            (
                "Welcome to {person}, who joins us on {day}. Please make time for a coffee if "
                "you're in the office."
            ),
            ("Welcome {person}, glad you're here.",),
        ),
        (
            (
                "IT is replacing the old docking stations. Swap yours at the help desk on {day} "
                "between 10 and {time}."
            ),
            (
                "Do I need to bring the cables too?",
                "Just the dock itself, the cables stay.",
            ),
        ),
        (
            "The summer party venue is booked. Details and dietary form coming next week.",
            (
                "Is there a plus one option?",
                "Yes, one guest each.",
            ),
        ),
        (
            (
                "New policy: laptops must be locked in a drawer or taken home overnight. Details "
                "are on the security page."
            ),
            (),
        ),
        (
            "Congratulations to {person} on five years with the company!",
            (
                "Congrats {person}!",
                "Well deserved, thanks for everything.",
            ),
        ),
        (
            (
                "The meeting rooms now have a new booking system. Old bookings were carried over, "
                "but please check yours."
            ),
            (
                "Mine vanished. Re-booking.",
                "Same, I'll tell facilities.",
            ),
        ),
        (
            (
                "A reminder that the kitchen dishwasher is not a recycling bin. Please rinse glass "
                "before putting it in the right bin."
            ),
            (),
        ),
        (
            (
                "Our pension provider is hosting a Q and A on {day} at {time}. Optional but useful "
                "if you're new to the scheme."
            ),
            (),
        ),
        (
            (
                "Reception lost a parcel that was addressed to {person}. If you picked it up by "
                "mistake, please return it."
            ),
            ("Found it, it was in the post room. Delivered.",),
        ),
        (
            (
                "Mandatory password change for the HR portal by {day}. Use the new rules: 14 "
                "characters minimum."
            ),
            (
                "Can we use a passphrase?",
                "Yes, that's the recommended option.",
            ),
        ),
        (
            (
                "Reminder that the office thermostat is set by the building, not by us. Please "
                "bring a jumper."
            ),
            (
                "Cold again on the third floor.",
                "Noted, facilities has been told.",
            ),
        ),
        (
            "Free breakfast on {day} to celebrate the product launch. Come by the kitchen from 9.",
            (
                "Is it vegetarian friendly?",
                "Yes, plus a vegan option.",
            ),
        ),
        (
            (
                "Our travel booking tool is moving to a new provider. Existing bookings are "
                "unaffected."
            ),
            (),
        ),
        (
            (
                "If you're attending the conference next month, please submit the travel form by "
                "{day}."
            ),
            (),
        ),
        (
            (
                "Remote staff: your home office stipend is available again. See the finance page "
                "for how to claim."
            ),
            (
                "What's the cap this year?",
                "Same as last year.",
            ),
        ),
        (
            "Payroll question line is open every {day} between {time} and 4pm. Email is also fine.",
            (),
        ),
        (
            "Cleaning crew found a pair of glasses in meeting room 3. They are at reception.",
            (),
        ),
        (
            "Quarterly goals have been published. Read them before the all hands.",
            (
                "Looks ambitious.",
                "It always does.",
            ),
        ),
        (
            "The company charity drive starts on Monday. Matching donations up to a limit.",
            (),
        ),
        (
            (
                "Building management will run the fire alarm check on {day} at {time}. No need to "
                "evacuate."
            ),
            (),
        ),
        (
            "Stairwell door on the east side is stuck. Facilities is fixing it.",
            (),
        ),
        (
            (
                "There's a delivery of new monitors on {day}. If you've requested one, you'll get "
                "an email."
            ),
            ("Great, mine was failing at the edges.",),
        ),
        (
            "Reminder to update your emergency contact details in the HR portal.",
            (
                "Where's that setting?",
                "Profile, then contacts.",
            ),
        ),
        (
            "Please keep noise down near the quiet room. People are on calls.",
            (),
        ),
        (
            (
                "We are testing a new lunch catering option on {day}. Please sign up by Wednesday "
                "so we can order the right amount."
            ),
            (),
        ),
        (
            "Calendar reminder: public holiday on {day}, office closed. On-call rota is unchanged.",
            (),
        ),
        (
            (
                "IT notice: the old file share will be read only from {day}. Move anything you "
                "still need to the shared drive."
            ),
            (
                "How long do we have until it's deleted?",
                "Three months, we'll send reminders.",
            ),
        ),
        (
            "The sound system in the main meeting room is fixed. Thanks for your patience.",
            (),
        ),
        (
            "Introducing our two summer interns, starting {day}. Say hello if you see them around.",
            (),
        ),
        (
            (
                "Please let reception know if you are expecting a courier. They cannot let people "
                "up without a name."
            ),
            (),
        ),
        (
            "A reminder that tailgating through the barrier is not allowed. Everyone badges in.",
            (
                "Even if we hold the door for someone?",
                "Especially then. Tell them to use the visitor desk.",
            ),
        ),
        (
            "The Q3 survey results are in. Short summary at the next all hands.",
            (),
        ),
        (
            (
                "Printing is moving to the new release-on-badge system. Instructions are taped to "
                "each printer."
            ),
            ("Worked first time for me.",),
        ),
        (
            "Wellness week starts {day}. There are yoga sessions at {time} in room 6.",
            (
                "Do I need to register?",
                "No, just show up.",
            ),
        ),
        (
            "New joiner lunch on {day}. If you joined in the last three months, you're invited.",
            (),
        ),
        (
            "The lost property box has been emptied. Anything unclaimed went to charity.",
            (),
        ),
        (
            "Reminder that guest wifi passwords change every Monday.",
            (),
        ),
        (
            "Mobile phone reimbursements: please attach the bill to your expense report.",
            (),
        ),
        (
            "The company holiday party has a theme this year. More details soon.",
            (
                "Not another costume one.",
                "Don't worry, it's casual.",
            ),
        ),
        (
            "Please sign the updated acceptable use policy in the learning portal by {day}.",
            (),
        ),
        (
            "Reminder that the photocopier on the first floor is for company use only, please.",
            ("Understood, no more wedding invitations.",),
        ),
        (
            "IT will reset the guest wifi on {day} at {time}. Visitors may need to reconnect.",
            (),
        ),
        (
            "Please fill in the 2 minute pulse survey by {day}. We read every comment.",
            ("Finished, thanks for the reminder.",),
        ),
    ),
    "off-topic": (
        (
            "Anyone going for lunch around {time}? Thinking about the noodle place.",
            (
                "I'm in.",
                "Can't today, back to back calls. Save me a dumpling.",
            ),
        ),
        (
            "Weekend plans? I'm finally going to repaint the hallway.",
            (
                "Brave. Send before and after photos.",
                "I'll be hiking if the weather holds.",
            ),
        ),
        (
            (
                "Book club: this month's pick is a mystery novel about a lighthouse. We meet on "
                "{day} at lunch."
            ),
            (
                "Is it a long one?",
                "About 300 pages, quick read.",
                "I'll try to finish it on the train.",
            ),
        ),
        (
            (
                "Running club is meeting at {time} on {day}, easy 5k loop along the river. All "
                "paces welcome."
            ),
            (
                "Count me in if it doesn't rain.",
                "I'll bring spare water bottles.",
            ),
        ),
        (
            "There's birthday cake in the kitchen for {person}. Help yourselves!",
            (
                "Happy birthday {person}!",
                "Thanks for the cake, it's gone already.",
            ),
        ),
        (
            "Just adopted a rescue dog. Name is Biscuit, he's 3, absolutely chaos.",
            (
                "Congratulations! Photos required.",
                "Check the pets channel, I posted one.",
            ),
        ),
        (
            "Did anyone see the match last night? That ending was ridiculous.",
            (
                "I fell asleep before the second half. Spoilers please.",
                "Don't ruin it for me, I recorded it.",
            ),
        ),
        (
            "Found a really good ramen place near the station. Small, cash only, worth it.",
            (
                "What's it called?",
                "Something with a bear in the name. I'll send the street.",
            ),
        ),
        (
            "Anyone have a recommendation for a good podcast on history?",
            (
                "Anything by the long form ones, depends how deep you want to go.",
                "I'll DM a list.",
            ),
        ),
        (
            "Lost: a blue water bottle with stickers on it. Might be in meeting room 2.",
            (
                "Found one in room 3, not sure if it's yours.",
                "That's it! Thanks.",
            ),
        ),
        (
            "Who is up for a board game night on {day}? Someone has a new strategy game.",
            (
                "Yes, I'll bring snacks.",
                "Does it take three hours to explain the rules?",
                "Probably.",
            ),
        ),
        (
            "Tried making sourdough this weekend. It's technically bread.",
            ("Bring some in on Monday, I'll be the judge.",),
        ),
        (
            "Anyone want to join a pub quiz team on {day}? We need two more people.",
            (
                "I'm terrible at sports questions but great at music.",
                "That's exactly what we need.",
            ),
        ),
        (
            "New album from a band I've liked for years dropped today. Thoughts?",
            ("Not my thing, but the single was decent.",),
        ),
        (
            "Looking for tips on a first trip to Lisbon in spring.",
            (
                "Go to the tram routes early in the morning, much quieter.",
                "I'll send my notes.",
            ),
        ),
        (
            (
                "Our cat just walked across my keyboard and sent a half written email to my boss. "
                "Fun times."
            ),
            ("Hope it was a good half.",),
        ),
        (
            "Anyone play tennis? Looking for a hitting partner on weekends.",
            ("I haven't played in years but I'm up for it.",),
        ),
        (
            "It's been raining for six days. Is it still raining where you are?",
            (
                "Yes, and the umbrella broke.",
                "Sunny here, sorry.",
            ),
        ),
        (
            "Just finished a marathon training block. Legs are done.",
            (
                "Congratulations. What's the finish time target?",
                "Sub four, fingers crossed.",
            ),
        ),
        (
            "Please settle this: does pineapple belong on pizza?",
            (
                "Yes.",
                "Absolutely not.",
                "Depends on the cheese, honestly.",
            ),
        ),
        (
            "Sharing the recipe for the lentil soup I brought in last week. It's all in the doc.",
            ("Thanks, that was great.",),
        ),
        (
            "Free tickets to a local film festival if anyone wants them. I can't make it.",
            ("I'll take them! Thanks.",),
        ),
        (
            "The new fiction section at the library is great, if anyone is looking for something.",
            (),
        ),
        (
            "Anyone know a good dentist near the office?",
            ("I go to one two streets over, friendly and fast. DM me.",),
        ),
        (
            "Taking up pottery. First bowl looks like a hat.",
            ("Share a picture!",),
        ),
        (
            "There are fresh cookies in the third floor kitchen. They won't last.",
            ("Too late, I've had four.",),
        ),
        (
            "Photography walk on Saturday morning, anyone interested? Slow pace, lots of stops.",
            (
                "I'd come but my camera is a phone.",
                "That's fine, bring it.",
            ),
        ),
        (
            "Does anyone want a spare monitor stand? It's too tall for my desk at home.",
            ("I'll take it.",),
        ),
        (
            "My neighbour's rooster has decided that 5am is the right time. Send help.",
            (
                "Earplugs.",
                "Move.",
            ),
        ),
        (
            "Which language is everybody learning at the moment? I've got a streak going.",
            (
                "Spanish, three months.",
                "I gave up in week two, respect.",
            ),
        ),
        (
            "The grill on the roof terrace is working again. Come Friday after work.",
            (),
        ),
        (
            "Good luck to everyone running the local 10k on Sunday.",
            (),
        ),
        (
            "Does anyone have a good chili recipe for a crowd?",
            ("Add a square of dark chocolate. Trust me.",),
        ),
        (
            "I saw the best sunrise on the way to work today.",
            (),
        ),
        (
            "Anyone else's kid obsessed with dinosaurs right now?",
            ("Yes. I can name seventeen.",),
        ),
        (
            "Car broke down this morning, working from home today.",
            (
                "Hope it's an easy fix.",
                "Thanks, waiting on the garage.",
            ),
        ),
        (
            "Reorganised my bookshelf by colour. Did it improve anything? No. Do I feel good? Yes.",
            (),
        ),
        (
            "Anyone know where to get a decent coffee grinder?",
            ("Get a burr one, even a cheap one beats a blade.",),
        ),
        (
            "The local team finally won something. It's a good week.",
            ("Don't jinx it.",),
        ),
        (
            "Karaoke night on {day}. Sign up for songs by {time}.",
            ("I'm bringing my own tambourine.",),
        ),
        (
            "Plant swap in the kitchen on Friday. Bring cuttings, take cuttings.",
            (),
        ),
        (
            "Does anyone have a ladder I could borrow this weekend?",
            ("I have a small one, DM me.",),
        ),
        (
            "Just saw a heron by the canal on my walk. Strange to see one in the city.",
            (),
        ),
        (
            "Looking for suggestions for a tabletop game for two players.",
            ("Anything cooperative is fun.",),
        ),
        (
            "Anyone been to the new climbing gym? Is it good for beginners?",
            ("Yes, they do a free intro session.",),
        ),
        (
            "My sourdough starter is called Gerald. Say hello.",
            ("Hello Gerald.",),
        ),
        (
            "Moving flats next month. If you have boxes, I'll gladly take them.",
            ("I have about twenty in the garage.",),
        ),
        (
            "The sandwich shop on the corner now does a vegan option and it's decent.",
            (),
        ),
        (
            "Anyone need tickets for the Saturday market stall? I have two spare.",
            (),
        ),
        (
            "Charity bake sale is on {day}. All proceeds go to the local food bank.",
            (
                "I'll bring brownies.",
                "Count me in for lemon drizzle.",
            ),
        ),
        (
            "Please send me your favourite quiet working music.",
            (
                "Instrumental stuff with no lyrics.",
                "Rain sounds and some jazz.",
            ),
        ),
        (
            "Weekend update: built a shed. It leans slightly but it stands.",
            (),
        ),
        (
            "Anyone watching the new series that everyone is talking about? No spoilers please.",
            (
                "Two episodes in, it's decent.",
                "I'm waiting for the whole season.",
            ),
        ),
        (
            "Trying to decide between two laptops for my parents. Opinions on screen size?",
            ("Bigger text is the main thing. Go for the larger one.",),
        ),
        (
            (
                "{person}, did you finish the book from last month? I need someone to discuss the "
                "ending with."
            ),
            (),
        ),
        (
            "Who has a good recipe for a quick weeknight dinner? I'm bored of pasta.",
            (
                "Sheet pan salmon with vegetables, ten minutes of work.",
                "Fried rice with whatever is in the fridge.",
            ),
        ),
        (
            "My team won the five a side match last night. Not to brag.",
            ("Brag away.",),
        ),
        (
            "Cycling to work today for the first time. It took 25 minutes and I'm still sweating.",
            ("It gets easier after a week.",),
        ),
        (
            "Does anyone have a recommendation for a podcast about money?",
            ("The one with the two hosts who argue is great.",),
        ),
        (
            "Anybody want a spare ticket to the concert on {day}? Can't make it.",
            (
                "I'd love it. What's the price?",
                "Face value, no rush.",
            ),
        ),
        (
            "Just got back from a week in the mountains. Zero signal, absolute bliss.",
            (
                "Photos?",
                "Sharing on the social channel.",
            ),
        ),
        (
            "Taking an informal poll: tea or coffee?",
            (
                "Coffee, always.",
                "Tea, but only in the afternoon.",
                "Both, depending on my mood.",
            ),
        ),
        (
            "Snow forecast for {day}. Who's working from home?",
            ("Me, I don't trust the trains.",),
        ),
        (
            "Check out the sunrise over the river this morning. Totally worth the early start.",
            (),
        ),
        (
            "I'm baking bread for the Friday bake sale. Any requests?",
            ("Cinnamon rolls please.",),
        ),
        (
            "Looking for a good gym near the office. Suggestions?",
            ("The one two blocks away has a student rate. DM me details.",),
        ),
        (
            "Learning to play the ukulele. My neighbours are not fans.",
            ("Keep going, it'll sound great.",),
        ),
        (
            "Anyone up for a lunchtime walk on {day} at {time}? Just 30 minutes around the park.",
            ("I'll join.",),
        ),
        (
            "I found a great second hand bookshop on Elm Street. Dangerous place.",
            (),
        ),
        (
            "Our dog just learned to open the fridge. Help.",
            (
                "Child lock.",
                "Move the cheese.",
            ),
        ),
        (
            "Anyone have experience with sourdough starters going flat?",
            ("Feed more often and keep it warm.",),
        ),
        (
            "Quick poll: best snack in the kitchen?",
            (
                "The nuts.",
                "The dark chocolate ones.",
            ),
        ),
        (
            "Fishing trip planned for the weekend. Anyone know a good spot?",
            (),
        ),
        (
            (
                "The school run was a disaster this morning. Lost a shoe somewhere between the "
                "door and the car."
            ),
            ("Been there.",),
        ),
        (
            "Recommend me a short story collection for the commute.",
            (),
        ),
        (
            "Has anyone tried the new bubble tea place?",
            ("It's nice but the queue is long. Go at 2pm.",),
        ),
        (
            "I'm doing a charity swim next month. Sponsors are welcome, but no pressure.",
            ("Send the link, I'm in.",),
        ),
        (
            'Moving a piano this weekend. Any tips? Other than "don\'t".',
            (),
        ),
        (
            "Just found out our neighbour is a retired pilot. Best stories ever.",
            (),
        ),
        (
            "My tomatoes are finally ripe. Free for anyone who wants some on {day}.",
            ("Count me in.",),
        ),
        (
            "Finished a jigsaw puzzle with a missing piece. I'm upset.",
            (),
        ),
        (
            "Anyone else follow the cooking competition show? The finale was brutal.",
            (),
        ),
        (
            "Will there be chess club this week?",
            ("Yes, {day} at {time} in the small meeting room.",),
        ),
        (
            "Terrible joke of the day: why did the developer go broke? He used up all his cache.",
            ("Groan.",),
        ),
        (
            "Gardening advice: what do I plant in a shady spot?",
            ("Ferns or hostas. Both survive neglect.",),
        ),
        (
            "Trying a no sugar month. Day two. Send encouragement.",
            (
                "You can do it.",
                "Day two is the worst.",
            ),
        ),
        (
            "Does anyone want to start a lunchtime walking group?",
            ("Yes, count me in.",),
        ),
        (
            "I'm travelling to the coast on {day}. Anything I must see?",
            (),
        ),
        (
            "The cafe on the corner has started doing breakfast burritos. Life changed.",
            (),
        ),
        (
            "Taking an evening class in pottery. My mug is lopsided but I love it.",
            (),
        ),
        (
            "Got new headphones, they cancel everything. I missed a fire drill.",
            ("Funny, but please don't do that.",),
        ),
        (
            "Looking for a babysitter recommendation for Saturday evening.",
            (),
        ),
        (
            "I'm training for a half marathon, my knees disagree.",
            (),
        ),
        (
            "New neighbour is a drummer. Pray for me.",
            (),
        ),
        (
            "Anyone going to the market on {day}? I need fresh herbs.",
            (),
        ),
        (
            "Has anyone seen the exhibition at the art museum? Worth the entry fee?",
            ("Yes, go on a weekday.",),
        ),
        (
            "The office ping pong table is back. Who's ready to lose?",
            ("Put my name down.",),
        ),
        (
            "Cooking class tomorrow. Learning to make pasta from scratch.",
            ("Bring leftovers.",),
        ),
        (
            "Watching the sunset from the roof terrace tonight if anyone wants to join.",
            (),
        ),
        (
            (
                "My phone fell in the river. I'm now a person without a phone. Any advice for "
                "survival?"
            ),
            ("Rice trick did nothing for me, sorry.",),
        ),
        (
            "Is there a local choir? I'd like to join something.",
            ("I sing in one on Wednesdays. DM me.",),
        ),
        (
            "Mystery solved: the humming in the kitchen was the old fridge.",
            (),
        ),
        (
            "Found a stray kitten near the car park. Looking for a good home.",
            (),
        ),
        (
            "Can anyone recommend a decent walking route near the office?",
            ("Along the canal, about 40 minutes loop.",),
        ),
        (
            "Does anyone know if the farmers market is open in winter?",
            (),
        ),
        (
            "The pub quiz team needs a name. Suggestions?",
            (
                "The Quizzy Rascals.",
                "Quiz Khalifa.",
            ),
        ),
        (
            "Good luck to {person} on the half marathon this weekend.",
            ("Go {person}!",),
        ),
        (
            "I found my old guitar. Strings all rusty but it still plays.",
            (),
        ),
        (
            "Taking a day to do absolutely nothing on {day}. Highly recommended.",
            (),
        ),
        (
            "Anyone know how to remove a red wine stain from a sofa?",
            ("Salt then cold water. Don't rub.",),
        ),
        (
            "Weekend plan: a long bike ride, a short nap, a long dinner.",
            (),
        ),
    ),
    "engineering": (
        (
            (
                "CI has been slow all morning, builds are sitting in the queue for 10+ minutes. "
                "Anyone else?"
            ),
            (
                "Yes, I've been waiting on the same job for 15 minutes.",
                "Looks like we're down a runner. Platform is checking.",
                "Back to normal now.",
            ),
        ),
        (
            (
                "Proposal: bump Python to 3.12 across all services by the end of the quarter. "
                "Anyone see a blocker?"
            ),
            (
                "The reporting scripts use an old library that might not support it.",
                "I'll check what it needs and post here.",
            ),
        ),
        (
            (
                "Postgres 16 upgrade is scheduled for next month. Please read the migration notes "
                "before you touch any queries."
            ),
            (
                "Does it affect the extensions we use?",
                "Both are supported, I double checked.",
            ),
        ),
        (
            (
                "Can we agree on a line length for the linter? Half the repos have 88 and half "
                "have 100."
            ),
            (
                "100 please, 88 wraps too much.",
                "No strong opinion, just pick one and enforce it in CI.",
                "Going with 100 then.",
            ),
        ),
        (
            (
                "Flaky job alert: the invoice export check fails about one run in ten. I'm going "
                "to quarantine it until someone has time to look."
            ),
            ("Which one? I'll take a look this afternoon.",),
        ),
        (
            "Design doc for the new retry service is up for review. Comments by {day} please.",
            (
                "Left a few questions inline.",
                "Thanks, will answer today.",
            ),
        ),
        (
            (
                "Tech talk on {day} at {time}: how we cache account lookups in the portal. Room 5, "
                "with recording."
            ),
            (
                "Will the slides be shared?",
                "Yes, afterwards.",
            ),
        ),
        (
            "Reminder: pull requests over 500 lines are hard to review. Where possible split them.",
            ("Agree. Even better if each commit is self contained.",),
        ),
        (
            (
                "Does anyone know why our dependency scanner has started flagging the HTTP client "
                "library?"
            ),
            ("There's a new advisory, patch is out. I'll bump it.",),
        ),
        (
            (
                "We should stop pinning to exact patch versions on internal libraries. It causes "
                "constant churn."
            ),
            (
                "But it protects us from silent breakage.",
                "Compromise: pin minor, let patch float, run the scheduled upgrade job.",
            ),
        ),
        (
            "Is there a standard for logging request ids? I keep seeing three different headers.",
            (
                "We said we'd use one header but nobody enforced it.",
                "I'll write a small middleware and open a pull request.",
            ),
        ),
        (
            "Who owns the shared utilities package? There's a bug in the date helper.",
            ("Platform, but anyone can send a fix.",),
        ),
        (
            (
                "Build cache is now enabled for the Python services. First builds should drop by "
                "about half."
            ),
            ("Confirming, my build went from 6 minutes to 3.",),
        ),
        (
            "Please add type hints to any new function. We're slowly turning on the strict checks.",
            (
                "What about tests?",
                "Not required for tests, but welcome.",
            ),
        ),
        (
            (
                "Anyone tried the new profiler on the nightly job? Curious whether it's worth the "
                "setup."
            ),
            ("Yes, found a hot loop in 10 minutes. Worth it.",),
        ),
        (
            (
                "Review norms: aim to respond within one working day. If you can't, say so and "
                "reassign."
            ),
            (
                "Seems fair.",
                "Can we add a bot reminder at 24 hours?",
            ),
        ),
        (
            (
                "We have three different ways to read secrets in the services. Let's standardise "
                "on the secrets manager helper."
            ),
            (
                "Is there a doc for the helper?",
                'It\'s in the platform handbook, search "secrets".',
            ),
        ),
        (
            (
                "Heads up: I'm merging the base image update this afternoon. Rebuild your branches "
                "if you see odd failures."
            ),
            (),
        ),
        (
            "Has anyone looked at moving from cron to a proper scheduler for the periodic jobs?",
            (
                "Evaluated it last year, we ran out of time.",
                "I'd back this, especially for alerting on missed runs.",
            ),
        ),
        (
            "Is it OK to use f-strings for log messages or do we want lazy formatting?",
            (
                "Lazy formatting avoids building strings for disabled levels. Use it.",
                "Not a hill I'll die on.",
            ),
        ),
        (
            "New rule in the linter: no bare except. It will fail CI starting Monday.",
            (
                "Thank goodness.",
                "There are two in old scripts. I'll fix those.",
            ),
        ),
        (
            (
                "Question about the testing pyramid: do we want more integration tests or more "
                "unit tests for the billing code?"
            ),
            ("Both, but fewer slow ones. Integration only for the money paths.",),
        ),
        (
            "Can we make the staging database refresh less disruptive? Mine got wiped mid-debug.",
            ("It runs Sunday at 2am. Set a reminder to export what you need.",),
        ),
        (
            "Postgres connection limits are getting close in staging. We need a pooler.",
            (
                "Already on the platform backlog.",
                "Meanwhile, close your connections in scripts please.",
            ),
        ),
        (
            (
                "I am going to remove the old branch protection exceptions at the end of the week. "
                "If you rely on one, tell me now."
            ),
            (),
        ),
        (
            (
                "Looking for a second reviewer for a change to the shared retry code. It's about "
                "80 lines."
            ),
            ("I can look this afternoon.",),
        ),
        (
            (
                "Let's try keeping feature flags short lived. Anything over three months old "
                "should be removed."
            ),
            ("I'll generate a list of the old ones.",),
        ),
        (
            "The wiki for architecture diagrams is out of date. Who wants to own it?",
            ("Proposal: each team owns its own page and we review quarterly.",),
        ),
        (
            (
                "CI now fails if the changelog isn't updated. If you're doing a chore, add \"no "
                'changelog" to the commit message.'
            ),
            (
                "Is that documented?",
                "Added a paragraph to the contributing page.",
            ),
        ),
        (
            "Quick vote: should we adopt a formatter for SQL migrations?",
            (
                "Yes, as long as it doesn't rewrite old files.",
                "Only new ones then.",
            ),
        ),
        (
            (
                "I noticed the nightly job host has 92 percent disk. Not an incident yet but let's "
                "tidy up."
            ),
            ("Old export files, probably. I'll clean them.",),
        ),
        (
            "Interesting read on connection pool sizing, link in the doc folder. Worth a skim.",
            (),
        ),
        (
            (
                "Python upgrade update: five services done, three to go. Notes on the gotchas are "
                "in the doc."
            ),
            ("Thanks, the datetime change bit me too.",),
        ),
        (
            "Is anyone using the old build server for anything? We want to switch it off.",
            (
                "Nope.",
                "I have an old job that might, let me check.",
            ),
        ),
        (
            "Do we want a weekly dependency update pull request?",
            ("Yes, but only auto merge patch versions.",),
        ),
        (
            "Our pull request template is too long. People tick boxes without reading.",
            ("Cut it to three questions: what, why, how to verify.",),
        ),
        (
            "Reminder that unit tests should not call the network. A couple in the portal do.",
            ("Found two, will fix.",),
        ),
        (
            "Could we get a dashboard for CI duration by repo?",
            ("I'll build one from the existing data.",),
        ),
        (
            (
                "Interviewing: we need two more engineers to help with the technical interviews "
                "next week."
            ),
            ("I can do Tuesday afternoon.",),
        ),
        (
            (
                "The new linting rules are catching a lot of unused imports. Thanks everyone for "
                "fixing them."
            ),
            (),
        ),
        (
            "Anyone know how to run the integration tests locally against a clean database?",
            ("There's a script in the repo root. I'll add the steps to the README.",),
        ),
        (
            (
                "Heads up, a vulnerability was published for a library in the portal. I'm checking "
                "if we use the affected function."
            ),
            (
                "Let me know if you need hands.",
                "We don't call it. Bumping the version anyway.",
            ),
        ),
        (
            (
                "Code review request: small refactor of the invoice number generator. Would "
                "appreciate a look before {day}."
            ),
            (),
        ),
        (
            "Should we add a staging smoke check to the deploy pipeline?",
            ("Yes please. Even a single request would catch the config mistakes.",),
        ),
        (
            "The shared fixtures for our unit tests are a mess. Can we split them by domain?",
            ("Plus one, I'll make a proposal next week.",),
        ),
        (
            "What's the right way to handle timezones in the scheduler? I see three conventions.",
            ("Store in UTC, convert at the edge. That's it.",),
        ),
        (
            "Is there a reason we don't use a connection pooler on the warehouse side?",
            ("It was never needed until recently, but the load is growing.",),
        ),
        (
            "Planning a short brown-bag on debugging with logs and traces. Interested?",
            ("Yes, make it practical.",),
        ),
        (
            (
                "The latest release of the web framework changes the default cookie settings. "
                "Please read the notes."
            ),
            (),
        ),
        (
            (
                "If you have a long running branch, rebase soon. The main branch has changed a lot "
                "this week."
            ),
            (),
        ),
        (
            "Can someone explain the retry policy for outbound calls? I'm seeing mixed behaviour.",
            (
                "Three attempts with backoff, except the email sender. That one's custom.",
                "Which we should probably fix.",
            ),
        ),
        (
            "Docs build is failing on main. Probably a broken link.",
            ("Fixed in a pull request, waiting for green.",),
        ),
        (
            "New engineer question: where do I find the on-call runbooks?",
            ("Handbook repository, docs folder. I'll send the link.",),
        ),
        (
            "Do we have a policy on third-party libraries with a single maintainer?",
            ("Not formally. Let's write one.",),
        ),
        (
            (
                "CI minutes this month are 30 percent above budget. Please avoid running full "
                "pipelines for docs-only changes."
            ),
            (
                "Is there a path filter we can use?",
                "Yes, I'll add it.",
            ),
        ),
        (
            "The retry service design doc is approved. Thanks to everyone who commented.",
            (),
        ),
        (
            (
                "Cleaning up stale branches tonight. Anything older than 6 months with no activity "
                "goes."
            ),
            (),
        ),
        (
            (
                "Python type checker is now at version 1.3. I've updated the config, tell me if "
                "you see new warnings."
            ),
            (),
        ),
        (
            "Can someone review the {repo} dependency bump? It's mostly lockfile noise.",
            (
                "Looking now.",
                "Approved, nothing odd in the diff.",
            ),
        ),
        (
            "{person}, are you still on {issue}? I'd like to build on top of it.",
            ("Yes, pushing a branch this afternoon.",),
        ),
        (
            "Heads up: {repo} CI is slower since the new lint step. Median build is now 7 minutes.",
            (
                "Can we run lint in parallel with the unit tests?",
                "Doing that, will push shortly.",
            ),
        ),
        (
            "Does {repo} still need the old compatibility shim?",
            (
                "I think nothing calls it. Grepping.",
                "Confirmed unused, removing.",
            ),
        ),
        (
            "Reminder that {issue} blocks the Python upgrade for {repo}. Anyone with spare hours?",
            ("I'll take a look tomorrow.",),
        ),
        (
            (
                "Raising {issue_title} in the design review on {day}. Please add your thoughts to "
                "the doc first."
            ),
            (),
        ),
        (
            "The merge queue for {repo} is stuck, a job has been running for two hours.",
            ("Cancelled it, should move now.",),
        ),
        (
            "We've had three flaky failures in {repo} this week, all in the date handling code.",
            ("Time zone dependent, I'll pin the zone in the check.",),
        ),
        (
            "{person} wrote a nice summary of how retries work in {repo}. Worth a read.",
            ("Thanks for sharing. Bookmarking.",),
        ),
        (
            (
                "Could we split {repo} into two packages? The reporting code has nothing to do "
                "with the rest."
            ),
            ("Maybe, but not this quarter.",),
        ),
        (
            "Who can approve a change to the CI config for {repo}? I only have write access.",
            ("Platform team. I'll add you to the reviewers.",),
        ),
        (
            "Seeing connection resets in {repo} against the replica. Anyone else?",
            ("Not today. Could be the pooler setting.",),
        ),
        (
            "Code review nit: please don't leave commented out code in {repo}. We have history.",
            (),
        ),
        (
            (
                "I'm adding a pre-commit config to {repo}. It runs the formatter and a quick type "
                "check."
            ),
            (
                "Will it slow down commits?",
                "About two seconds.",
            ),
        ),
        (
            "{issue} is a good candidate for a pairing session. Any takers?",
            ("I can do {day} at {time}.",),
        ),
        (
            "Quick poll: should {repo} keep supporting the old API version?",
            (
                "Customers are still on it. Keep it until next quarter.",
                "Agreed.",
            ),
        ),
        (
            "Anyone know why the {repo} build pulls the same image twice?",
            ("Probably the cache key. I'll check.",),
        ),
        (
            (
                "The type checker found 14 new issues in {repo} after the upgrade. Fixing them in "
                "small pull requests."
            ),
            (),
        ),
        (
            "Please avoid force pushes to shared branches in {repo}. It broke {person}'s checkout.",
            ("Sorry about that, noted.",),
        ),
        (
            "For {issue}, do we want to fix the root cause or add a guard?",
            (
                "Guard first, root cause after the release.",
                "Works for me.",
            ),
        ),
        (
            "CI cache for {repo} was cleared by accident. First build will be slow, sorry.",
            (),
        ),
        (
            "The docs generator for {repo} is failing on a missing heading. Fix in review.",
            (),
        ),
        (
            "Has anyone looked at memory usage in {repo}? It grows slowly over a day.",
            ("Opened a profile on staging, will share the result.",),
        ),
        (
            "Looking for opinions on adding a new linter rule for unused arguments.",
            ("Fine as warnings first.",),
        ),
        (
            "{person}, can you hand over context on {issue}? I'm picking it up while you are out.",
            ("Writing notes in the issue now.",),
        ),
        (
            "Merged a big refactor in {repo}. Please rebase before opening new pull requests.",
            (),
        ),
        (
            "Is the {repo} staging database in sync with production schema?",
            ("One migration behind. Applying it now.",),
        ),
        (
            'Pull request template update: add a "how I verified this" section. Thoughts?',
            ("Yes please, that helps reviewers.",),
        ),
        (
            "The Python 3.12 runtime image is ready. {repo} is first in line.",
            ("Switching it this week.",),
        ),
        (
            "Short thread: how do we deal with secrets in local dev for {repo}?",
            ("Use the shared dev secrets manager path, and never commit anything.",),
        ),
        (
            "I'm adding structured logging to {repo}. It will change the log format on {day}.",
            ("Dashboards will need updating. I'll do that.",),
        ),
        (
            (
                "There is a slow unit check in {repo} that takes 90 seconds on its own. Anyone "
                "know why?"
            ),
            ("It builds a large fixture. I'll shrink it.",),
        ),
        (
            "How do you all handle database migrations that lock tables?",
            (
                "Run them in a quiet window and keep them short.",
                "Use a concurrent index where possible.",
            ),
        ),
        (
            "Can we get CODEOWNERS in {repo}? Reviews keep going to the wrong people.",
            ("Adding it, give me a few minutes.",),
        ),
        (
            "{issue_title} turned out to be a config issue, not a bug. Closing {issue}.",
            (),
        ),
        (
            (
                "The new API client in {repo} retries on timeouts. Please check it doesn't double "
                "charge."
            ),
            ("It uses an idempotency key, I checked.",),
        ),
        (
            "Reminder that release branches for {repo} are cut on {day}.",
            (),
        ),
        (
            "Reviewing {issue} now. Will have comments by {time}.",
            (),
        ),
        (
            "I've been getting flaky DNS lookups in CI. Anyone else?",
            (
                "Yes, a few retries in the logs.",
                "Platform is looking.",
            ),
        ),
        (
            (
                "Benchmarks for the new serializer in {repo}: about 30 percent faster on large "
                "payloads."
            ),
            (
                "Nice. Is it a drop in replacement?",
                "Mostly. One edge case with dates.",
            ),
        ),
        (
            "Switching {repo} to the new runner config on {day}. The change is small.",
            (),
        ),
        (
            "Our log volume doubled last week. I suspect {repo} debug output.",
            ("Found it. Turning it off.",),
        ),
        (
            "Someone left a TODO in {repo} from 2022. Asking before I delete it.",
            ("Delete it.",),
        ),
        (
            "Review request for {issue}, 40 lines, no behaviour change.",
            ("Approved.",),
        ),
        (
            "Does the main branch of {repo} deploy automatically or manually?",
            ("Manually, every Tuesday and Thursday.",),
        ),
        (
            "Do we want to make {issue} a team goal for the quarter?",
            ("Worth discussing at planning.",),
        ),
        (
            "We need an owner for the build scripts in {repo}. They keep breaking.",
            ("I'll volunteer.",),
        ),
        (
            "We upgraded the database client library in {repo}. If you see new warnings, tell me.",
            ("None so far.",),
        ),
        (
            (
                "{person} found a typo in a log message that has been there for years. Fixed in "
                "{repo}."
            ),
            (),
        ),
        (
            "Looking for a volunteer to give a short talk about the retry service on {day}.",
            ("I can do it.",),
        ),
        (
            "Is there a pre-approved list of open source licences?",
            ("Yes, security keeps it. Link is in the handbook.",),
        ),
        (
            (
                "Lunch and learn topic ideas: observability basics, database indexing, writing "
                "readable SQL."
            ),
            (
                "Indexing please.",
                "Readable SQL.",
            ),
        ),
        (
            "Is anyone using the feature flag called new_invoice_flow in {repo}? It looks stale.",
            ("Can be removed, we shipped it in June.",),
        ),
        (
            "Why does {repo} import the whole utility library for one function?",
            ("Historical. Replace with a local helper.",),
        ),
        (
            "Pull request {issue} adds a rate limiter. Please check the numbers.",
            ("Limit looks low for peak. Raise to 200.",),
        ),
        (
            "Do we have a policy for how long to keep old container images?",
            ("Thirty days, except for tagged releases.",),
        ),
        (
            "Please remember to update the changelog for {repo} before cutting a release.",
            ("Will do.",),
        ),
        (
            "Moving the shared types out of {repo} into a small internal package. Objections?",
            ("None. Please version it.",),
        ),
        (
            "Is the staging queue for {repo} healthy? Jobs seem stuck.",
            ("Restarted the worker, working now.",),
        ),
        (
            "Reading about circuit breakers for the outbound calls in {repo}. Anyone used them?",
            ("Yes, on the processor client. Works fine.",),
        ),
        (
            "I'd like to stop supporting Python 3.10 in internal libraries after the next release.",
            ("Fine by me. Announce it widely.",),
        ),
        (
            (
                "Quick tip: add a trace id header to logs in {repo} to follow a request across "
                "services."
            ),
            (),
        ),
        (
            "Who owns the cron entries on the old host? I found one for {repo}.",
            ("Platform. Moving it to the scheduler.",),
        ),
        (
            "Do we need an architecture review for {issue}?",
            ("Yes, since it touches billing and the portal.",),
        ),
        (
            "Mutation testing found weak spots in {repo}. Writing better checks for them.",
            (),
        ),
        (
            "The retry service pull request is ready for a third review. Please look when you can.",
            (),
        ),
        (
            "Checking in on dependency health for {repo}: 4 outdated, 1 with an advisory.",
            ("Advisory first.",),
        ),
        (
            (
                "Static analysis flagged a possible null dereference in {repo}. False positive, I "
                "think."
            ),
            (
                "Check again. The branch where it's set is not obvious.",
                "You're right, it can be null. Thanks.",
            ),
        ),
        (
            "Who has context on how {repo} deals with leap years?",
            ("{person} wrote it. Ask them.",),
        ),
        (
            "My local environment for {repo} stopped working after the update. Anyone seen this?",
            ("Rebuild the image, it needs the new base.",),
        ),
        (
            "Shall we put the architecture decision records in each repo or one central one?",
            ("Each repo, near the code.",),
        ),
        (
            "Can someone from platform explain what changed in the build pipeline last week?",
            ("We moved to the new runner image. Notes in the platform channel.",),
        ),
        (
            "New tool suggestion: a dependency graph viewer for our services.",
            ("Nice idea. Does it work offline?",),
        ),
        (
            "Weekly reminder: close stale pull requests on {repo} before Friday.",
            (),
        ),
        (
            "Please review {issue} before Thursday, it blocks the release.",
            (),
        ),
        (
            "The unit checks for {repo} fail on my machine only. Locale difference?",
            ("Probably. Set LANG to en_US and rerun.",),
        ),
        (
            "Tip of the week: use git bisect when you cannot tell which change broke something.",
            (),
        ),
        (
            "Data team asked for a read replica credential for {repo} reporting. Who approves it?",
            ("Platform handles it. Raise a request.",),
        ),
        (
            "Should we use a new library for retries in {repo}? The old one is unmaintained.",
            ("Yes, but keep the interface stable.",),
        ),
        (
            "Some pull requests wait three days for review. Can we do better?",
            (
                "We could pick a reviewer of the day.",
                "Trying that next week.",
            ),
        ),
        (
            "We should write down our rules about breaking changes to the internal APIs.",
            ("Add them to the contributing guide.",),
        ),
        (
            "Rollout plan for {issue} is in the doc. Feedback by {day}.",
            (),
        ),
        (
            "We have two logging libraries in {repo}. Can we drop one?",
            ("Keep the structured one, I'll migrate the rest.",),
        ),
        (
            "Does {issue} need a database migration or just a code change?",
            ("Just code. No schema changes.",),
        ),
        (
            "Brown-bag on {day} at {time}: lessons from the {repo} outage drill. Everyone welcome.",
            (),
        ),
        (
            "Anyone using a different editor setup for {repo}? Trying to document the common ones.",
            ("I use the default plus the type checker plugin.",),
        ),
        (
            "What's the policy on squash merging for {repo}?",
            ("Squash for feature branches, merge commit for release branches.",),
        ),
    ),
    "team": (
        (
            "Standup notes: finishing the {repo} changes today, review on Thursday. No blockers.",
            ("Thanks, I'll pick up the review first thing.",),
        ),
        (
            "Could someone review {issue}? It's small, mostly renaming.",
            (
                "On it.",
                "Left two comments.",
                "Fixed, please check again.",
            ),
        ),
        (
            "Blocked on {issue}, waiting for the credentials from platform.",
            ("I'll ping them, they usually answer by lunch.",),
        ),
        (
            "Deploying {repo} at {time} today. Please hold merges until it's done.",
            ("Ack.",),
        ),
        (
            "Pairing on {issue_title} at {time}? I have a draft but I want a second pair of eyes.",
            ("Yes, send a meeting link.",),
        ),
        (
            (
                "On-call handover: quiet week, two pages, both false alarms. The dashboard link is "
                "in the doc."
            ),
            ("Thanks, I'll skim the doc tonight.",),
        ),
        (
            "Sprint planning is tomorrow at {time}. Please update your tickets beforehand.",
            ("Updated mine.",),
        ),
        (
            "Retro is on {day}. Add anything you'd like to talk about to the board.",
            (
                "What format are we using?",
                "Start, stop, continue, same as last time.",
            ),
        ),
        (
            "I'm out on {day}. {person} will cover any reviews.",
            ("Have a good one.",),
        ),
        (
            "{person}, can you take {issue}? I'm stuck on something else.",
            ("Sure, I'll start after lunch.",),
        ),
        (
            "Pull request for {issue} is up. It adds the missing checks and a regression check.",
            (
                "Looks good. One question about the naming.",
                "Renamed. Merging after CI.",
            ),
        ),
        (
            "Anyone seen this error in staging? Looks like a timeout talking to the database.",
            (
                "It started after the refresh on Sunday.",
                "Restarting the service fixed it for me.",
            ),
        ),
        (
            (
                "Quick heads up, I'll be on a customer call from {time}. Ping me in chat if it's "
                "urgent."
            ),
            (),
        ),
        (
            "Our team goal for the quarter is down to four items. Updated in the doc.",
            (),
        ),
        (
            "Can we move standup to {time} tomorrow? I've got a dentist appointment.",
            (
                "Works for me. Thanks.",
                "Same.",
            ),
        ),
        (
            "Release for {repo} is cut. Notes are in the channel, starting rollout at {time}.",
            ("Thanks. I'll watch the dashboards.",),
        ),
        (
            "Looking for someone to pair on the new reconcile script. It's mostly SQL.",
            ("I'm free after {time}.",),
        ),
        (
            "{issue_title} is taking longer than I thought. Adding a day to the estimate.",
            (
                "Understood. Do you need help?",
                "Not yet, I'll shout.",
            ),
        ),
        (
            "Reminder to update the on-call rota in the pager tool before the weekend.",
            (),
        ),
        (
            "Anyone free for a quick call about {issue}? I want to confirm the expected behaviour.",
            ("Give me 10 minutes.",),
        ),
        (
            "I closed {issue}. It was already fixed by the previous change.",
            (),
        ),
        (
            (
                "I'm going to refactor the settings loader this week. If you have open branches "
                "touching config, tell me."
            ),
            ("I have one but only a few lines.",),
        ),
        (
            "Team lunch on {day}, my treat. Pick a place in the thread.",
            (
                "Pizza?",
                "Anything with a vegetarian option.",
            ),
        ),
        (
            "Rolled back {repo} after the deploy because of a config error. Fix is on its way.",
            ("Thanks for acting fast.",),
        ),
        (
            "Does anyone know how the discount rules are meant to stack? I need it for a bug.",
            (
                "Finance wrote it down in the old wiki. I'll find it.",
                "Found it, sending a screenshot.",
            ),
        ),
        (
            "Review requested on {repo}. It's a one line fix, hotfix label.",
            ("Approved. Thanks.",),
        ),
        (
            "Planning poker for the next two tickets after standup. Short session.",
            ("I'll join. Thanks.",),
        ),
        (
            "Saw the alert about disk usage on the reporting host. I've started cleaning up.",
            (),
        ),
        (
            "Can I get a second opinion on whether to split {issue} into two tickets?",
            ("Split it, the bug and the cleanup are separate.",),
        ),
        (
            (
                "Design review for the new credit note flow is on {day} at {time}. Please skim the "
                "doc first."
            ),
            ("Will do. Thanks.",),
        ),
        (
            (
                "Merged the first part of {issue}. The second part depends on a schema change, so "
                "waiting on that."
            ),
            (),
        ),
        (
            "Working from home on {day}. Reachable in chat as usual.",
            (),
        ),
        (
            (
                "Please don't merge anything to {repo} between {time} and 5pm, we're cutting the "
                "release."
            ),
            (),
        ),
        (
            "Anybody know if the staging data has been refreshed this week?",
            ("Not yet, it's scheduled for Sunday.",),
        ),
        (
            "Added notes to {issue} with what I found. Not sure about the next step, thoughts?",
            ("Let's talk about it at standup.",),
        ),
        (
            (
                "Our backlog is getting long. Let's use the next 30 minutes to close what's no "
                "longer relevant."
            ),
            (
                "Good idea. I'll start from the bottom.",
                "Closed seven.",
            ),
        ),
        (
            "Anybody mind if I take {issue} and {issue_title} together? They touch the same file.",
            ("Makes sense, go ahead.",),
        ),
        (
            "Thanks {person} for the quick review on {repo}.",
            (),
        ),
        (
            (
                "Heads up, the staging database is about to be restored from a snapshot. Save any "
                "work you need."
            ),
            (),
        ),
        (
            "Quick question: do we still need the weekly sync with data team?",
            ("I'd keep it, but make it 15 minutes.",),
        ),
        (
            "Stuck on a failing check in {repo}. It passes locally. Anyone have a minute?",
            (
                "Probably the timezone. Try setting it to UTC.",
                "That was it. Thanks!",
            ),
        ),
        (
            "Reminder that the on-call phone is with {person} this week.",
            (),
        ),
        (
            "Customer asked about {issue}. Do we have a rough date for a fix?",
            ("Not yet. Let's discuss after standup.",),
        ),
        (
            "Tomorrow's pairing session is cancelled, will reschedule for {day}.",
            (),
        ),
        (
            (
                "I'm about to cut over the scheduler for {repo}. If anything weird happens with "
                "retries, ping me."
            ),
            (),
        ),
        (
            "Reminder to log your time before the end of the month.",
            (),
        ),
        (
            "First draft of the quarterly plan is in the doc. Feedback welcome.",
            ("Can we move the cleanup item up?",),
        ),
        (
            "Sorry, I'll be late to standup, train delay.",
            (),
        ),
        (
            "Is anyone working on the changelog for {repo}? I can take it.",
            ("Yes please.",),
        ),
        (
            "Tests for {issue} are now in. They're slow, I'll speed them up in a follow up.",
            (),
        ),
        (
            "Please add a short description to your pull requests. It helps the reviewer.",
            ("Agreed. Template says what, why, how to check.",),
        ),
        (
            "Planning to start {issue} on {day}. Does that clash with anyone's work?",
            ("No clash on my side.",),
        ),
        (
            "The deploy finished but I see warnings in the logs. Investigating.",
            (
                "Which service?",
                "{repo}. It's the same one as last week.",
            ),
        ),
        (
            "I've rewritten the failing check in {repo}. Waiting for review.",
            (),
        ),
        (
            "Can we add the on-call phone number to the team channel header?",
            ("Done.",),
        ),
        (
            "Who wants to show their work at the end of the sprint? Slots are 5 minutes each.",
            ("I'll show the new credit note screen.",),
        ),
        (
            "Shout if you're blocked on anything today.",
            (),
        ),
        (
            "Updating the runbook after yesterday's page. If you were on call, check my notes.",
            ("Looks right. Added one missing step.",),
        ),
        (
            "Taking half a day tomorrow. Back at {time} on {day}.",
            (),
        ),
        (
            "Kickoff for the next project is {day} at {time}. Everyone please read the brief.",
            (),
        ),
        (
            "I'm done with {issue}. Handing the cleanup to {person}.",
            ("Got it, thanks.",),
        ),
        (
            "Standup in 5 minutes. Notes from yesterday are in the doc.",
            (),
        ),
        (
            "Good morning. Looking at {issue_title} first thing today.",
            (),
        ),
        (
            "Anyone want to share the load testing results for {repo}? I need the numbers.",
            ("Posted them in the doc.",),
        ),
        (
            "Did the backfill for {repo} finish? I saw it still running at {time}.",
            ("Finished a bit after. Row counts match.",),
        ),
        (
            (
                "Please take a look at the alert thresholds I proposed for {repo}. I'd like to "
                "change them before {day}."
            ),
            (
                "Looks sensible, but the disk one seems too low.",
                "Raised it to 80.",
            ),
        ),
        (
            "Our team calendar is a mess, can we agree on one place for out of office dates?",
            ("Shared calendar, everyone adds their own.",),
        ),
        (
            (
                "Heads up, I'll be on the pager from {day}. If you need to ship something risky, "
                "tell me beforehand."
            ),
            (),
        ),
        (
            (
                "I'll write the summary for the sprint review. Send me one line each about what "
                "you shipped."
            ),
            (
                "Sent mine.",
                "Mine's in the doc.",
            ),
        ),
        (
            "Anybody remember why we have the extra column on the invoices table in {repo}?",
            (
                "Legacy from the old reconciliation. I think we can drop it.",
                "Let's confirm with finance first.",
            ),
        ),
        (
            (
                "Starting {issue} today. Plan is to add the missing validation and a couple of "
                "unit tests."
            ),
            ("Sounds good. Ping me when the draft is up.",),
        ),
        (
            "Pull request for {repo} is ready. It's about 60 lines, mostly deletions.",
            (
                "Reviewing.",
                "ok, approved.",
            ),
        ),
        (
            "Out of office on {day}. {person} has my reviews.",
            (),
        ),
        (
            "Reminder that the {repo} release branch is cut at {time} today.",
            ("Got it, merging my last change now.",),
        ),
        (
            "Anyone free to look at a failing check in {repo}? I can't see why.",
            (
                "Send the link, I'll look.",
                "Race condition in the setup. Pushing a fix.",
            ),
        ),
        (
            (
                "Planning for next sprint: we have room for about 12 points. Please bring your top "
                "two issues."
            ),
            ("Mine are {issue} and the cleanup.",),
        ),
        (
            (
                "Retro actions from last time: shorter standups, one review per day, a Friday "
                "showcase. How are we doing?"
            ),
            ("Standups are better. Reviews are still slow.",),
        ),
        (
            "{person}, thanks for covering the on-call weekend.",
            ("Anytime. It was quiet.",),
        ),
        (
            "Switching to async standup this week. Post your update in the thread before 10.",
            (
                "Posted mine.",
                "Mine's up.",
            ),
        ),
        (
            "I'm picking up {issue_title}. If anyone has context, let me know.",
            ("{person} did the first investigation. Their notes are in the issue.",),
        ),
        (
            "Heads up, the staging database is going down for maintenance at {time}.",
            (),
        ),
        (
            "Pairing on {issue} was very productive. We found three more edge cases.",
            ("Add them as tasks.",),
        ),
        (
            "Can we talk about the on-call schedule? Some people are getting two weeks in a row.",
            (
                "Yes, let's fix it in the pager tool this afternoon.",
                "Done, updated.",
            ),
        ),
        (
            "New runbook draft for {repo} is in the handbook. Please check the steps.",
            ("Step 4 is out of date, the command changed.",),
        ),
        (
            "Anyone know who changed the default timeout in {repo}?",
            ("It was in the last release. Reasoning is in {issue}.",),
        ),
        (
            "I can't reproduce {issue} locally. Maybe data specific.",
            ("Try account ids ending in 7, they behave oddly.",),
        ),
        (
            "Starting the {repo} rollout to production at {time}. Staging was fine all week.",
            (
                "Watching the dashboards.",
                "All green so far.",
            ),
        ),
        (
            "Draft design for {issue_title} is in the doc. Rough, but I'd like your gut reaction.",
            ("Looks sensible. One concern about backfills.",),
        ),
        (
            "Morning all. I'll be pairing with {person} on {repo} until lunch.",
            (),
        ),
        (
            "Production alert about {repo} resolved itself. Looking at logs now.",
            (),
        ),
        (
            "Quick request: please link the issue in every pull request description.",
            ("Done, I'll add it to the template.",),
        ),
        (
            "Stuck on a merge conflict in {repo}. Anyone good at untangling these?",
            ("Share your branch.",),
        ),
        (
            "Closing the sprint on {day}. Anything unfinished moves over automatically.",
            (),
        ),
        (
            "Backlog grooming at {time} on {day}. We'll walk through the top 20.",
            (),
        ),
        (
            (
                "Can someone double check the rollout order for {issue}? I want to be sure "
                "migrations go first."
            ),
            ("Yes, migration then app then worker.",),
        ),
        (
            "Who's taking the on-call phone this week?",
            ("{person}.",),
        ),
        (
            "Thanks for the quick fix on {issue}, saved us a lot of trouble.",
            (),
        ),
        (
            "Team offsite ideas: bowling, escape room, a long lunch.",
            ("Long lunch wins.",),
        ),
        (
            "I added a README to {repo} that explains how to run it locally.",
            ("Tried it, worked on the first go.",),
        ),
        (
            "Release notes for the sprint are in the doc. Please add your items.",
            (),
        ),
        (
            (
                "I'm having trouble with the VPN today, working from the cafe next door. Back "
                "online around {time}."
            ),
            (),
        ),
        (
            "Any objections to renaming the main branch of {repo}? It would match the others.",
            ("No objections.",),
        ),
        (
            "Reminder to update your tickets before standup. Stale statuses confuse the board.",
            (),
        ),
        (
            "{person}, could you walk us through the new flow on {day}? You know it best.",
            ("Happy to.",),
        ),
        (
            (
                "I need an hour of focus time tomorrow morning. Please avoid pinging unless it's "
                "urgent."
            ),
            ("Understood.",),
        ),
        (
            "Update on {issue}: the fix is merged, waiting for the next release.",
            (),
        ),
        (
            (
                "Postmortem notes for last week's missed job are in the doc. Mostly small process "
                "changes."
            ),
            ("Read it. Good clear write up.",),
        ),
        (
            "Does anyone have the account id of the affected customer in {issue}?",
            ("DM'd you.",),
        ),
        (
            "Sprint showcase is at {time} on {day}. Five minutes per person, no slides needed.",
            (),
        ),
        (
            "Please put your review requests in the channel so they don't get lost.",
            ("ok, will do.",),
        ),
        (
            "I found a nicer way to batch the retries in {repo}. Writing it up.",
            (),
        ),
        (
            "Alert noise from the nightly job again. Could we mute it until {issue} is fixed?",
            ("Mute the warning, keep the failure.",),
        ),
        (
            "First week on call. Any tips?",
            ("Read the last three handovers and have the runbooks open.",),
        ),
        (
            "Is the {repo} dashboard being updated automatically or manually?",
            ("Automatically at midnight.",),
        ),
        (
            "Added a regression check for {issue}. It fails before the fix, passes after.",
            (),
        ),
        (
            "Please assign yourself to issues you work on, otherwise I can't plan.",
            ("Fixed mine.",),
        ),
        (
            "I'm going to deploy a small config change to {repo} at {time}. No downtime expected.",
            (),
        ),
        (
            "Retro was good. The three actions are on the board.",
            (),
        ),
        (
            "Good news: {issue} is closed. Customer confirmed the fix.",
            (),
        ),
        (
            "Who wants the {day} slot for the platform sync?",
            ("I'll go.",),
        ),
        (
            "The handover notes from {person} are very thorough. Thanks.",
            (),
        ),
        (
            "I merged {issue_title} before the review finished by mistake. Reverting now.",
            ("No harm done, thanks for telling us.",),
        ),
        (
            "Estimates for {issue}: two days for me, one if someone pairs.",
            ("I'll pair on {day}.",),
        ),
        (
            "Please don't deploy {repo} on Fridays after {time}.",
            ("Agreed. Thanks.",),
        ),
        (
            "Hey team, I'm starting a weekly doc on what we learned. Add anything.",
            (),
        ),
        (
            (
                "Reviewing {issue} now. First impression: good, but needs a short explanation in "
                "the code."
            ),
            (),
        ),
        (
            "Reminder to check the shared inbox for billing questions.",
            (),
        ),
        (
            "Could we add a quick diagram for {repo} to the handbook?",
            ("I'll sketch one this week.",),
        ),
        (
            "I'm about to restart the worker for {repo}. Expect a brief gap in processing.",
            (),
        ),
        (
            "Does {issue} depend on the schema change?",
            ("Yes. Please wait for it.",),
        ),
        (
            "Looking at the on-call dashboard: 4 alerts overnight, all related to {repo}.",
            ("I'll check the logs.",),
        ),
        (
            "We're done with the migration for {repo}. Cleanup issue created.",
            (),
        ),
        (
            "Kickoff meeting for the credit note work at {time} on {day}. Bring questions.",
            (),
        ),
        (
            "Waiting for finance to confirm the rounding rules for {issue}. Chasing.",
            (),
        ),
        (
            "Any volunteers for documentation day on {day}?",
            ("I'll write up the {repo} runbook.",),
        ),
        (
            "Please review the diff for the schema change carefully. It's irreversible.",
            ("Reviewed twice. Looks right.",),
        ),
        (
            "Just rebased {repo} on main. Tests pass, ready for a final look.",
            (),
        ),
        (
            "Heads up that the staging queue is full. Delay of about 20 minutes on jobs.",
            ("Draining it now.",),
        ),
        (
            "{person} is on holiday next week, so {issue} will wait.",
            (),
        ),
        (
            "I added a few bad inputs to the checks for {repo}. Found two bugs.",
            (),
        ),
        (
            (
                "Cutting the {repo} release now. If you have anything you want in, say so in the "
                "next five minutes."
            ),
            (),
        ),
        (
            "Quiet day. Anyone want to pair on {issue}?",
            (),
        ),
        (
            "Morning! Spent yesterday on {issue_title}, still not finished.",
            ("Want help?",),
        ),
        (
            "My laptop is being replaced today, I'll be offline from {time}.",
            (),
        ),
        (
            "Please remember daylight saving ends this weekend. Check any scheduled jobs.",
            ("Our nightly load handles it, I checked.",),
        ),
        (
            "Final reminder: sprint planning is at {time} in room 4.",
            (),
        ),
        (
            "I'm updating the pager rota so weekends are shared more fairly. Check the new draft.",
            ("Looks fair.",),
        ),
        (
            "The backup for {repo} data completed. Checked a restore on staging. All good.",
            (),
        ),
        (
            "Is it OK to push a hotfix for {issue} without the full review?",
            ("Get one quick review, then yes.",),
        ),
        (
            "Testing the new alert rules for {repo} in staging tonight.",
            (),
        ),
        (
            "Reminder to document anything you do by hand in production.",
            (),
        ),
        (
            "Does anyone have the staging credentials for the portal? Mine expired.",
            ("Rotated last week. Check the secrets manager.",),
        ),
        (
            "Thanks {person} for tidying the old branches in {repo}. It was needed.",
            (),
        ),
        (
            "Draft of the quarterly review is up. Please add your highlights by {day}.",
            (),
        ),
        (
            "Can someone sit in on a customer call about {issue}? I need an engineer.",
            ("ok, i'll join.",),
        ),
        (
            "Our weekly backlog is down to 31 from 44. Nice progress.",
            (),
        ),
        (
            "I'm leaving a note in {issue} on how to run the reconciliation by hand.",
            (),
        ),
        (
            "Pull request for {repo} needs a second review. Anyone?",
            ("I'll review after lunch.",),
        ),
        (
            "Please update the board when you move a ticket. People rely on it.",
            (),
        ),
        (
            "I'll draft the customer message for {issue}. Support can edit it.",
            ("Send it over when ready.",),
        ),
        (
            "We shipped {repo} on time. Thanks everyone.",
            (),
        ),
        (
            "Backup plan if {issue} slips: we ship it behind a flag.",
            (),
        ),
        (
            "Proposal: no meetings on {day} afternoons so we can focus. Thoughts?",
            (
                "Yes please. Thanks.",
                "Fine by me.",
            ),
        ),
        (
            "Deploy window for {repo} changed to {time}. Please plan merges around it.",
            (),
        ),
        (
            "Please check your pull requests, three have been open over a week.",
            (),
        ),
        (
            "I'm creating a doc for the team's working agreements. Please add yours.",
            (),
        ),
        (
            "The failed check in {repo} was an expired token. Renewed it.",
            (),
        ),
        (
            "I'll be on the customer call about {issue_title} from {time} to 3pm.",
            (),
        ),
        (
            "Notes from the planning meeting are in the doc.",
            ("Thanks for writing them up.",),
        ),
        (
            "I'm looking at why the nightly job for {repo} uses so much memory.",
            ("Might be the batch size. Try halving it.",),
        ),
        (
            "Next standup is at {time} tomorrow because of the all hands.",
            (),
        ),
        (
            "Need someone to cover the billing question inbox for 30 minutes.",
            ("I've got it.",),
        ),
        (
            "Docs for {repo} have a broken link. Fixing.",
            (),
        ),
        (
            "Reminder that {person} is leading the retro this time.",
            (),
        ),
        (
            "My review of {issue} is done. Two small changes requested.",
            ("Updated.",),
        ),
        (
            "Looks like {issue} also affects the portal. Opening a linked ticket there.",
            (),
        ),
        (
            "Merged the cleanup for {repo}. Removed about 400 lines.",
            ("Love it.",),
        ),
        (
            "Reminder to book your holiday ahead of the freeze.",
            (),
        ),
        (
            "Starting a spike on {issue_title}, timeboxed to one day.",
            ("Report back with what you find.",),
        ),
        (
            "Kudos to {person} for catching the bug in the migration before it ran.",
            ("Thanks, it was a lucky catch.",),
        ),
        (
            "Standup note: still working on {issue}, hoping to wrap up by {day}.",
            ("Thanks, flag it if it slips.",),
        ),
        (
            "The {repo} deploy went fine. Notes are in the release thread.",
            (),
        ),
        (
            "Do we need to reach out to the customer about {issue}?",
            (
                "Support has it covered.",
                "I'll check with them on {day}.",
            ),
        ),
        (
            "Can I get a second reviewer on {issue}? It touches money handling.",
            (
                "I'll take a look.",
                "On it, back by {time}.",
            ),
        ),
        (
            "I'll be leaving at {time} today for an appointment.",
            (),
        ),
        (
            "Heads up: the {repo} job is running long today. Might hold up the {time} deploy.",
            ("Okay, let's push the deploy by an hour.",),
        ),
        (
            (
                "Added a new section to the {repo} README about local setup. Please check I got it "
                "right."
            ),
            ("Followed it from scratch, worked fine.",),
        ),
        (
            "Reminder: {person} is demoing the new reconciliation view on {day}.",
            (),
        ),
        (
            "Do we want to cancel the Friday sync? Not much to talk about.",
            (
                "Cancel it.",
                "Keep it short instead.",
            ),
        ),
        (
            "Anyone know why {issue_title} was reopened?",
            (
                "Customer said it's back.",
                "Reopened by me, sorry, should have commented.",
            ),
        ),
        (
            "Looking for a volunteer to shadow the on-call this week.",
            (
                "I'm interested.",
                "Great, I'll add you.",
            ),
        ),
        (
            "I rewrote the failing job in {repo}. It's now much faster.",
            (
                "Nice, how much?",
                "From 12 minutes to 4.",
            ),
        ),
        (
            "The issue board is messy. Can we do a quick cleanup session on {day}?",
            ("Yes, 30 minutes.",),
        ),
        (
            "Heads up, I'm changing the retry count in {repo} from 3 to 5.",
            (
                "Make sure it doesn't hit rate limits.",
                "Checked, we are well within them.",
            ),
        ),
        (
            "Team photo on {day} at {time} in the lobby. Smile.",
            (),
        ),
        (
            "Welcome {person} to the team channel!",
            ("Hi everyone, happy to be here.",),
        ),
        (
            "Final sprint review slides are in the doc. Add your screenshots.",
            (),
        ),
        (
            "Anyone seen the build fail with a certificate error in {repo}?",
            ("Yes, the base image is old. Rebuilding.",),
        ),
        (
            "Could you add {issue} to the sprint? Customer is waiting.",
            ("Added, top priority.",),
        ),
        (
            "I'll write the release notes for {repo} unless someone else wants to.",
            ("All yours.",),
        ),
    ),
    "support": (
        (
            (
                "A customer on the annual plan says they can't log in after resetting their "
                "password. Anyone seen this?"
            ),
            (
                (
                    "Yes, it's the same as {issue}. The reset link works only once, the second "
                    "click fails."
                ),
                "Can you send them a fresh link? Meanwhile we'll look into it.",
            ),
        ),
        (
            (
                "Invoice dispute: a customer says they were charged twice this month. Looking at "
                "the account now."
            ),
            (
                (
                    "Two invoices on the same day. Looks like the duplicate from the first of the "
                    "month."
                ),
                "Credit the second one and send the customer a note, I'll confirm with billing.",
            ),
        ),
        (
            (
                "Refund request for an account in the EU. They cancelled within 14 days. Do we "
                "just approve?"
            ),
            ("Yes, that falls under the cooling off rule. Approve and log the reason.",),
        ),
        (
            (
                "Queue is at 42 open tickets, average first response is 3 hours. Could use help on "
                "the afternoon shift."
            ),
            (
                "I can take the portal tickets after {time}.",
                "Thanks, I'll pick up billing.",
            ),
        ),
        (
            (
                "New macro for failed payments is live. It links to the portal page where the "
                "customer can update their card."
            ),
            ("Nice, much shorter than the old one.",),
        ),
        (
            (
                "Customer reports the invoice PDF shows the wrong company address. They updated it "
                "last week."
            ),
            (
                "That's {issue}. The PDF uses a cached address. Engineering is working on it.",
                "Told the customer we'll resend once it's fixed.",
            ),
        ),
        (
            (
                "An account is asking for a copy of all invoices from last year. Is there a bulk "
                "export?"
            ),
            ("Not yet. I pull them one by one. It's on the wishlist.",),
        ),
        (
            (
                "A customer wants to change their billing email but can't find the setting in the "
                "portal."
            ),
            ("It isn't there yet, we do it manually. Send me the account id.",),
        ),
        (
            (
                "Heads up: three tickets today about the portal login page being blank on an older "
                "browser."
            ),
            (
                "That's {issue_title}, engineering has it.",
                "Workaround: ask them to try another browser for now.",
            ),
        ),
        (
            (
                "Escalation: customer is threatening to cancel over a late fee they say they "
                "shouldn't have received."
            ),
            (
                "Check the grace period setting on their plan first.",
                "It was set to zero. I've corrected it and refunded the fee.",
            ),
        ),
        (
            (
                "Please don't promise dates for bug fixes unless engineering confirms. Say \"we're "
                'working on it" instead.'
            ),
            ("Understood. Thanks.",),
        ),
        (
            (
                "We got a ticket from a customer in the UK asking for a VAT invoice. Can billing "
                "do that?"
            ),
            ("Yes, they need to add their tax number in the account first.",),
        ),
        (
            "Customer asks why their invoice total changed after they had previewed it.",
            ("Known issue with rounding, see {issue}. Difference should be a cent or two.",),
        ),
        (
            "Daily summary: 118 tickets received, 104 solved. Backlog is down slightly.",
            ("Good job team.",),
        ),
        (
            (
                "A customer has been locked out for 24 hours after too many failed logins. They "
                "are asking for an unlock."
            ),
            ("Verify identity first, then I'll unlock from the admin tool.",),
        ),
        (
            "We have a customer who wants a credit note rather than a refund. Is that possible?",
            ("Not through the portal, billing can create one. Send the request.",),
        ),
        (
            "Reminder to tag tickets with a product area. The reports are useless without it.",
            ("I'll add a mandatory field.",),
        ),
        (
            "The weekend queue was quiet. Only 8 tickets, mostly password resets.",
            (),
        ),
        (
            "A customer is unhappy with our response time. They waited two days.",
            ("Checked, the ticket was assigned to someone on leave. Reassigned.",),
        ),
        (
            "Customer asks whether we support paying by bank transfer. I said yes, am I right?",
            ("Yes for annual plans only.",),
        ),
        (
            (
                "Customer wants to know when the next price change is. I don't have anything in "
                "the docs."
            ),
            ("Nothing announced. Tell them we'll email 30 days ahead.",),
        ),
        (
            "Do we have a template for explaining proration?",
            ('Yes, "Plan change explained". It has a worked calculation.',),
        ),
        (
            "A customer's support request attachment disappeared. They filled the form twice.",
            ("Sounds like {issue}. Ask them to email the file for now.",),
        ),
        (
            "Account in the EU is asking about data deletion. Who handles this?",
            ("Legal. Forward the request, don't promise anything.",),
        ),
        (
            "New starter in support this week. Please be patient with questions.",
            (),
        ),
        (
            "A customer says the invoice email goes to spam. Anyone else heard that?",
            ("Two other accounts. I'll check with the platform team about the sending setup.",),
        ),
        (
            (
                "I answered a billing question wrongly yesterday, the customer was charged a late "
                "fee. Fixing it now."
            ),
            ("Thanks for flagging, let's refund and send an apology.",),
        ),
        (
            "Customer asks for a phone call. We don't do phone support, right?",
            ("Only for the enterprise tier. Check the account type first.",),
        ),
        (
            "Report from a customer: the portal times them out while filling in the support form.",
            ("Session expiry again. Link to {issue}.",),
        ),
        (
            (
                "Customer wants a refund on a plan they have used for 8 months. Policy says no, "
                "but they're an important account."
            ),
            (
                "Escalate to the account manager. Don't promise.",
                "Done, they will call them today.",
            ),
        ),
        (
            "A new account is confused about how to add users. Do we have a help page?",
            ('Yes, "Inviting teammates". I\'ll add it to the macro.',),
        ),
        (
            "Queue update: we're back under 20 tickets. Thanks everyone.",
            (),
        ),
        (
            (
                "Customer's credit card was declined three times. They say the bank approved it. "
                "What can we check?"
            ),
            (
                "Look at the processor logs for the decline code. I can pull them.",
                "It was a fraud check on their bank's side. Customer called the bank.",
            ),
        ),
        (
            "We keep getting asked for invoice copies. Can we put a link in the welcome email?",
            ("Good idea, I'll draft the wording.",),
        ),
        (
            (
                "A customer reports seeing another account's name on their invoice. This could be "
                "serious."
            ),
            (
                (
                    "Escalating to engineering immediately and tagging security. Please don't "
                    "reply to the customer yet."
                ),
                "Confirmed it was a typo in their own company field. No data leak.",
            ),
        ),
        (
            (
                "Customers keep asking about two-factor login for the portal. I'll add it to the "
                "product feedback list."
            ),
            (),
        ),
        (
            "We have a spike of tickets about a late fee. Likely related to the grace period bug.",
            ("That's {issue}. Billing is on it.",),
        ),
        (
            "The satisfaction score for last week is 94 percent.",
            ("Nice.",),
        ),
        (
            (
                "A customer asks if we can change the invoice currency. They moved their business "
                "abroad."
            ),
            ("Needs a manual change on the account. I'll ask billing.",),
        ),
        (
            (
                "Please remember to check the account status before issuing refunds. Two went to "
                "closed accounts this week."
            ),
            (),
        ),
        (
            "Customer has sent a long feature request. Where should I log it?",
            ('Product feedback board, tag "billing".',),
        ),
        (
            "Reminder: do not send invoice copies to anyone but the account owner.",
            (),
        ),
        (
            "Customer says their discount code didn't apply. Code was typed in lowercase.",
            ("That is {issue}. Apply the discount by hand and let them know.",),
        ),
        (
            "Customer wants to cancel the annual plan mid term. Prorated refund?",
            ("Per policy, no refund after 30 days. But we can offer to downgrade.",),
        ),
        (
            "Anyone able to cover the queue on {day}? I have an appointment.",
            ("I can.",),
        ),
        (
            "Can someone check why the escalation form is not creating tickets?",
            (
                "Looking now. Thanks.",
                "Fixed, it was a permissions change on the form.",
            ),
        ),
        (
            (
                "Customer on the monthly plan can't download the latest invoice. Is {issue} the "
                "same thing?"
            ),
            ("Looks like it. I'll add the account to the issue.",),
        ),
        (
            "{person}, can you take the angry email from the account in the EU? I'm on the phone.",
            ("On it. Thanks.",),
        ),
        (
            "Customer asks why they were billed for an extra user. Checking the plan history.",
            ("Seat count went up on the 3rd, probably when they invited someone.",),
        ),
        (
            "I linked three tickets to {issue}. Engineering says they are on it.",
            ("Thanks. I'll update the macro.",),
        ),
        (
            "Someone asked for a refund on a duplicate charge. Is it the same as {issue_title}?",
            ("Yes. Refund and apologise, billing has the fix queued.",),
        ),
        (
            "{person} is on leave, can someone watch the billing inbox?",
            ("I'll check hourly.",),
        ),
        (
            "Customer reports the portal shows an old invoice balance. Cached view?",
            ("Probably. Ask them to refresh, and tell me if it persists.",),
        ),
        (
            (
                "A customer wants to know what happens to their data if they cancel. Do we have "
                "standard wording?"
            ),
            ('Yes, "Data after cancellation". Legal approved it.',),
        ),
        (
            "The macro for password resets has a typo. Fixing it now.",
            (),
        ),
        (
            "Customer upgraded and wasn't charged proration. Related to {issue}?",
            ("Same bug. Billing will correct on the next run.",),
        ),
        (
            "{person}, did you reply to the customer about {issue}? They sent another message.",
            ("Replying now.",),
        ),
        (
            (
                "Customer says the support form won't submit. I could reproduce with a large "
                "attachment."
            ),
            ("Known. Ask them to email it instead.",),
        ),
        (
            "A new customer asks for a quote for 50 seats. Who handles that?",
            ("Sales. Forward to the sales inbox.",),
        ),
        (
            "An account has been charged in the wrong currency. Checking if {issue} applies.",
            ("Different issue, opening a new one.",),
        ),
        (
            "Overnight queue was busy, mostly password resets. Clear now.",
            (),
        ),
        (
            (
                "Customer asks to move their invoices to a new billing email. I can't do it from "
                "my view."
            ),
            ("Account owner needs to confirm. I'll do it after that.",),
        ),
        (
            (
                "I need a second opinion on whether this is a refund case. Account used the "
                "product for 5 weeks, then asked."
            ),
            ("Policy says up to 30 days. Decline, offer a downgrade.",),
        ),
        (
            "Customer complaining about slow page loads on the account page. See {issue}.",
            ("Add them to the list, and tell them it's known.",),
        ),
        (
            "{person} wrote a great reply to a hard billing case. I saved it as a macro.",
            (),
        ),
        (
            "Does anyone know why a customer received two reminder emails? {issue} maybe?",
            ("Likely. Billing is looking into duplicates.",),
        ),
        (
            "Customer needs an invoice in a different language. Do we offer that?",
            ("Not yet. English only for now.",),
        ),
        (
            "Escalation: a large account is locked out. Their admin left the company.",
            ("Verify via the contract contact, then I'll reset.",),
        ),
        (
            "Please don't forward customer emails to personal addresses. Use the shared inbox.",
            (),
        ),
        (
            "A customer wants to pay by invoice rather than card. Eligibility?",
            ("Annual plan only. Send the form.",),
        ),
        (
            "Heads up, two tickets about {issue_title}. Same account?",
            ("Different accounts. Linking both.",),
        ),
        (
            "Our CSAT dropped two points this week. Mostly because of slow replies on {day}.",
            ("We were short staffed. Back to normal.",),
        ),
        (
            "Someone asked how to export their data. Is there a self service option?",
            ("Not yet, we run it for them. Send me the account id.",),
        ),
        (
            "Customer with two accounts wants them merged. We can't do that automatically.",
            ("Open a request with billing, they do it by hand.",),
        ),
        (
            "Weekly reminder: update the status of tickets that are waiting on the customer.",
            (),
        ),
        (
            "A customer thanked us for the fast response. Making my day.",
            ("Nice. Share it in the channel.",),
        ),
        (
            "Customer got the wrong tax rate. They are based in the EU.",
            ("Check their tax ID. If missing, ask them to add it.",),
        ),
        (
            "I'd like to propose a macro for {issue}. Draft in the doc.",
            ("Looks good. Add a line about timing.",),
        ),
        (
            "Customer says the portal logged them out three times. Related to {issue}?",
            ("Probably. Ask which browser.",),
        ),
        (
            "{person}, can you review my refund before I send it? It's large.",
            ("Looks right. Send it.",),
        ),
        (
            "A customer asks about the status of {issue}. What do I tell them?",
            ("\"We're working on it, we'll update you when it ships.\"",),
        ),
        (
            "Customer has been charged after cancelling. Verified the cancellation date.",
            ("Refund the charge and add a note.",),
        ),
        (
            "Did we change the invoice email template? Customers say it looks different.",
            ("Yes, with the last release. It's intentional.",),
        ),
        (
            "A customer sent a very long list of requests. Priority?",
            ("Triage into bugs and features, respond with one message.",),
        ),
        (
            "Our knowledge base article on proration is outdated. I'll fix it.",
            ("Thanks. Link {issue_title} if it's still relevant.",),
        ),
        (
            "Please remember to tag escalations with the priority label.",
            (),
        ),
        (
            "New hire shadowing today. Be patient if I'm slow answering.",
            (),
        ),
        (
            "A customer's account was suspended after multiple failed payments. They want it back.",
            ("Take the payment first, then I'll reactivate.",),
        ),
        (
            "Someone asked about the refund timeline. How long does it take?",
            ("Five to ten business days depending on their bank.",),
        ),
        (
            "The customer in {issue} replied: fix confirmed.",
            ("Closing the loop.",),
        ),
        (
            "Two customers say the discount code field is missing. Seen it?",
            ("Hidden on narrow screens. It's in {issue}.",),
        ),
        (
            "We got a bunch of positive feedback on the new invoice layout. Sharing in the thread.",
            (),
        ),
        (
            "A customer asked for a one page summary of fees. Do we have one?",
            ("Pricing page has it. I'll send them the link.",),
        ),
        (
            (
                "Can someone confirm a customer's plan renewal date? I'm looking at two different "
                "values."
            ),
            ("The billing admin view is correct. The portal date is wrong, see {issue}.",),
        ),
        (
            "Customer reports the invoice shows a different company name than they entered.",
            ("Likely the old name on the account. Update it for them.",),
        ),
        (
            "We had 12 refund requests today. That's high.",
            ("Mostly the duplicate charge bug.",),
        ),
        (
            "The queue for {day} is covered by {person} and me.",
            (),
        ),
        (
            "Does anyone have a good template for a delayed fix apology?",
            ('Check the macros, "Delay apology".',),
        ),
        (
            (
                "Customer asks whether we are certified for a security standard. I'm not sure what "
                "to say."
            ),
            ("Send to security, they have the standard answer.",),
        ),
        (
            "An account admin accidentally deleted a user. Can we restore it?",
            ("Within 30 days yes. I'll do it.",),
        ),
        (
            "The new onboarding email is live. Early replies are positive.",
            (),
        ),
        (
            "A customer is confused about the invoice due date. I explained, but it needs UI work.",
            ("Add it to {issue_title} as a comment.",),
        ),
        (
            (
                "Customer said they were charged tax when they are exempt. I need to check their "
                "certificate."
            ),
            ("It expired last month. Ask them to upload a new one.",),
        ),
        (
            "Support hours changed for the holidays. Check the rota.",
            (),
        ),
        (
            "Customer asked to speak to someone senior. Account manager notified.",
            (),
        ),
        (
            "Looking for a volunteer to tag older tickets for the quarterly report.",
            ("I'll do the ones from last month.",),
        ),
        (
            "I answered a ticket in the wrong language. Apologies sent.",
            (),
        ),
        (
            "Customer is asking about API access to invoices. Who do I ask?",
            ("Engineering, via {issue}.",),
        ),
        (
            (
                "Customers keep asking the same thing about annual plan renewals. Maybe a help "
                "article?"
            ),
            ("Good idea. I'll draft one.",),
        ),
        (
            "Waiting on a reply from engineering for {issue}. The customer is chasing.",
            ("I'll nudge them.",),
        ),
        (
            "{person}, please check the unassigned tickets before you go.",
            ("Will do. Cheers.",),
        ),
        (
            "Automation question: can we auto close tickets that haven't had a reply in 7 days?",
            ("Yes, but send a reminder at day 5.",),
        ),
        (
            "A customer wants to know why their invoice has a different number format.",
            ("We changed to a continuous counter in the spring.",),
        ),
        (
            "Billing question for finance: how do we treat a partial refund after a plan change?",
            ("I'll ask and report back.",),
        ),
        (
            "Customer says they never received the welcome email. Checked: bounced.",
            ("Ask for another address.",),
        ),
        (
            "{person}, nice work on clearing the old backlog.",
            (),
        ),
    ),
    "incidents": (
        (
            (
                "Alert fired for high CPU on a billing worker, cleared after 5 minutes. No "
                "customer impact that I can see."
            ),
            ("Probably the invoice run. Nothing to do.",),
        ),
        (
            (
                "Slow query in the portal: the account list is taking 4 seconds. Looking at the "
                "plan now."
            ),
            (
                "Missing index on the users table? Last time it was that.",
                "Yes, adding it tonight after the backup.",
            ),
        ),
        (
            "TLS certificate for the portal expires in 18 days. Renewal is on the platform list.",
            ("Renewed. Rollout tomorrow.",),
        ),
        (
            "Disk on the nightly job host is at 85 percent. Cleaning up old export files.",
            ("Down to 61 percent.",),
        ),
        (
            (
                "Third-party card processor is showing degraded performance on their status page. "
                "We'll watch our payment error rate."
            ),
            (
                "Error rate looks normal so far.",
                "Still normal. Processor says resolved.",
            ),
        ),
        (
            "Last night's warehouse load failed at step 4. I re-ran it and it finished at 3:40am.",
            (
                "Thanks. Root cause?",
                "A timeout from the replica. Added a retry.",
            ),
        ),
        (
            (
                "Pager went off at 2am for a failed health check on staging. It was a restart, no "
                "action needed."
            ),
            (
                "Can we make staging alerts non-paging?",
                "Yes, I'll change the routing.",
            ),
        ),
        (
            "A queue depth alert for invoice workers fired, drained in 10 minutes.",
            (),
        ),
        (
            "Memory on the reporting workers is climbing again. Will restart them in the morning.",
            ("Opened an issue to find the leak.",),
        ),
        (
            (
                "We saw a spike of 500 errors from the portal between {time} and {time}. It "
                "stopped on its own."
            ),
            ("Looks like a deploy in progress. Not an incident.",),
        ),
        (
            "Database connections hit 90 percent of the limit briefly. We're watching.",
            ("It was the month-end report run. We should schedule it differently.",),
        ),
        (
            "Alert flapping on the disk space check for the web hosts. I'll raise the threshold.",
            (),
        ),
        (
            "Mail provider is reporting delays, our invoice emails are queued. About 300 pending.",
            ("Delivered by 4pm.",),
        ),
        (
            "Backups completed with warnings. Looking at the log.",
            ("Nothing serious, one file was in use. Rerunning it.",),
        ),
        (
            "The nightly job for customer events was skipped because of maintenance. Intentional.",
            (),
        ),
        (
            "Latency on the portal API is up to 800ms for a few minutes. Back to normal.",
            (),
        ),
        (
            (
                "Security scan found an outdated package on one host. Not exploitable, patching "
                "this week."
            ),
            (),
        ),
        (
            "Warning from the pager tool: license seats nearly full. Platform will buy more.",
            (),
        ),
        (
            (
                "Staging environment is down. Probably a bad config change from this morning, "
                "rolling back."
            ),
            ("Back up.",),
        ),
        (
            "One of the CI runners ran out of disk. Cleared the cache.",
            (),
        ),
        (
            "Rate limit alerts on the payment API. We hit the limit twice this hour, then fine.",
            ("Spread out the retries, that's {issue}.",),
        ),
        (
            (
                "The status page for the cloud provider reports an issue in us-east-1, but we see "
                "no effect."
            ),
            ("Same for me. Keeping an eye.",),
        ),
        (
            (
                "SSL handshake errors from an old client at a customer. Not our side, informing "
                "support."
            ),
            (),
        ),
        (
            "Reminder to review the 5 flapping alerts we silenced last week.",
            (),
        ),
        (
            "Cron job for log rotation failed on one host. I ran it by hand.",
            (),
        ),
        (
            "Replica lag spiked to 40 seconds for two minutes. Cleared.",
            ("Probably the long running report query.",),
        ),
        (
            "Scheduled maintenance by the VPN vendor tonight, connections may drop briefly.",
            (),
        ),
        (
            (
                "Alert about invoice export duration, it took 25 minutes instead of 12. Not "
                "urgent, let's look tomorrow."
            ),
            (),
        ),
        (
            "A node was replaced automatically overnight. Nothing for us to do but good to know.",
            (),
        ),
        (
            (
                "Disk usage on the staging database host is at 78 percent. Going to prune old "
                "snapshots."
            ),
            (),
        ),
        (
            "Quiet night. Only one page and it self resolved.",
            (),
        ),
        (
            "Alert for elevated errors on {repo}, cleared after two minutes. Nothing for us to do?",
            ("Probably a deploy. I'll check the timeline.",),
        ),
        (
            "Slow queries on {repo} at {time}. Looking at the plan.",
            ("I added an index last week. Maybe it didn't apply on the replica.",),
        ),
        (
            "Disk usage warning on the {repo} host, 82 percent. Will clean up old logs.",
            ("Done, now 54 percent.",),
        ),
        (
            "{repo} health check failed once and recovered. Keeping an eye.",
            (),
        ),
        (
            "Certificate for the {repo} endpoint expires in 21 days. Added to the renewal list.",
            ("Renewed already.",),
        ),
        (
            "{repo} worker queue is long this morning, about 2,000 jobs. Draining slowly.",
            ("It's the month-end run. Should clear by noon.",),
        ),
        (
            "Memory climbing on {repo} workers. I'll restart after the next deploy.",
            ("Opened {issue}.",),
        ),
        (
            "Third-party status page shows a degraded email provider. {repo} sends are delayed.",
            ("Queue will drain when they recover.",),
        ),
        (
            "Replica lag for {repo} reached 30 seconds, now fine.",
            (),
        ),
        (
            "Alert fired for {repo} error rate. It was a single bad input, fixed by retry.",
            (),
        ),
        (
            "Lots of 404s from a bot hitting {repo}. Blocking by user agent.",
            ("Fine for now, but let's add a rate limit.",),
        ),
        (
            "Nightly job for {repo} took 80 minutes instead of 50. No failure, just slow.",
            ("Probably the data volume. Let's watch for a week.",),
        ),
        (
            "Deploy of {repo} caused a short spike in latency. Back to normal at {time}.",
            (),
        ),
        (
            "Pager noise: the {repo} CPU alert fired 4 times overnight.",
            ("Raise the threshold slightly. I'll do it.",),
        ),
        (
            "{repo} nightly job did not run last night. Checking the scheduler.",
            ("Rescheduled and running now.",),
        ),
        (
            "A health probe on the {repo} staging host failed. Restarted the container.",
            (),
        ),
        (
            "I'm seeing timeouts calling the payment processor from {repo}.",
            (
                "Their status page says it's an issue on their side.",
                "Resolved after about 20 minutes.",
            ),
        ),
        (
            "Backup of the {repo} database finished with a warning. Investigating.",
            ("Warning is about a skipped temp file. Harmless.",),
        ),
        (
            "Config reload on {repo} failed silently on one host. Redeployed.",
            (),
        ),
        (
            "Elevated 502s on the portal for 90 seconds at {time}. Cleared.",
            (),
        ),
        (
            "The queue depth alert for {repo} is firing but the queue is draining.",
            (),
        ),
        (
            "Connection pool for {repo} reached 95 percent. Increased the limit.",
            (),
        ),
        (
            "Log volume from {repo} is up 3x since yesterday. Looks like debug is on.",
            ("Turning it off.",),
        ),
        (
            "Disk on the CI runners is almost full. Clearing caches.",
            (),
        ),
        (
            "Upstream DNS issue caused a handful of failures from {repo}. Already recovered.",
            (),
        ),
        (
            "The dashboard for {repo} shows a gap between {time} and 4pm. Metrics agent restart.",
            (),
        ),
        (
            "A cron job on the reporting host overlapped with the previous run. Added a lock.",
            ("Good catch.",),
        ),
        (
            "Paging policy question: should a failed backup on staging page someone?",
            ("No, a message in the channel is enough.",),
        ),
        (
            "Long running query on the {repo} replica. I killed it after 40 minutes.",
            ("Who ran it? It might be a report.",),
        ),
        (
            "Rotating a certificate on {repo} tonight. Brief reconnect possible.",
            (),
        ),
        (
            "A security scan flagged an old library in {repo}. Patching on {day}.",
            (),
        ),
        (
            "Increased error budget burn for {repo}. Within limits.",
            (),
        ),
        (
            "Warehouse load was a bit slow last night, still finished before 6.",
            (),
        ),
        (
            "Unusual traffic to the {repo} login endpoint from one IP. Rate limited.",
            ("Looks like a customer's script gone wrong.",),
        ),
        (
            "Retry storm on {repo} after the processor blip. Backoff helped.",
            (),
        ),
        (
            "Alert on missing heartbeat from {repo}. It turned out to be a clock skew on the host.",
            ("Synced it.",),
        ),
        (
            "Short blip in the VPN at {time}, a few people reconnected.",
            (),
        ),
        (
            "Autoscaler added two replicas for {repo} at {time}. Normal for the day.",
            (),
        ),
    ),
    "direct": (
        (
            "Hey, got a minute for a quick question about {repo}?",
            ("Sure, call me.",),
        ),
        (
            "Can you look at {issue} when you get a chance? No rush, before {day} would be great.",
            ("Will do. I'll have an answer by {time} tomorrow.",),
        ),
        (
            "Are you free for a 1:1 on {day} at {time}?",
            ("Yes. Booked.",),
        ),
        (
            "Can you cover my on-call on {day}? I have a family thing.",
            (
                "Sure. Swap me back in two weeks?",
                "Deal.",
            ),
        ),
        (
            "Coffee at {time}?",
            ("Give me ten minutes, finishing a thing.",),
        ),
        (
            "Sharing the design doc with you. Would love your thoughts on section three.",
            ("Reading now.",),
        ),
        (
            "Thanks for the review earlier, that was helpful.",
            (),
        ),
        (
            "Did you see {person}'s message in the channel? I wasn't sure how to reply.",
            ("Yes, I'd just thank them and say you'll check.",),
        ),
        (
            "Could you add me to the {repo} repository? I'm starting to work on it.",
            ("Done, you should have write access now.",),
        ),
        (
            "Are you coming to the offsite?",
            ("I think so, still waiting on the dates.",),
        ),
        (
            "Do you remember how we configured the timeout for {repo}? I can't find it.",
            ("It's in the config file under the retries section.",),
        ),
        (
            "Hey {person}, do you have time to pair on {issue_title} this afternoon?",
            ("After {time}, that works.",),
        ),
        (
            "Quick one: is it fine to merge on Fridays?",
            ("Rule of thumb is no, unless it's small and reversible.",),
        ),
        (
            "Sorry I missed your message yesterday, got buried in meetings.",
            ("No worries.",),
        ),
        (
            "Can you send me the link for the expense tool?",
            ("Sent by email.",),
        ),
        (
            "I'll be late to our {time} meeting, five minutes.",
            (),
        ),
        (
            "Do you have the notes from last week's planning?",
            ("Yes, I'll send them over.",),
        ),
        (
            "Lunch today?",
            (
                "Sure, usual place at noon.",
                "Perfect.",
            ),
        ),
        (
            (
                "Heads up, I changed the config for {repo} in staging. Let me know if you see "
                "anything weird."
            ),
            (),
        ),
        (
            "Can you take a look at my pull request when you have time?",
            ("Looking at it now.",),
        ),
        (
            "Could you give me a second opinion on this schema change?",
            (
                "Sure. Is there a doc?",
                "Linking it now.",
            ),
        ),
        (
            "Do you know who to ask about a laptop replacement?",
            ("IT service desk, they have a form on the intranet.",),
        ),
        (
            "Congrats on the promotion!",
            ("Thank you, that means a lot.",),
        ),
        (
            "Happy birthday!",
            ("Thanks! Cake in the kitchen at {time}.",),
        ),
        (
            "I'm out sick today, can you cover my {time} meeting?",
            ("Yes, feel better.",),
        ),
        (
            "Did you manage to try the new profiler?",
            ("Not yet, this week.",),
        ),
        (
            "I'm moving to the third floor, near the kitchen. You are welcome to visit.",
            ("Dangerous for my snack budget.",),
        ),
        (
            "Hey, can you remind me what the process is for production access?",
            ("Request in the handbook form, manager approves, platform grants. About a day.",),
        ),
        (
            "Can I borrow your charger?",
            ("On my desk, take it.",),
        ),
        (
            "Are you going to the tech talk on {day}?",
            ("Planning to. Save me a seat.",),
        ),
        (
            "Do you want to catch up before the sprint planning?",
            ("Yes, let's do 15 minutes at {time}.",),
        ),
        (
            "Did the customer reply about {issue}?",
            ("Not yet. I'll chase them tomorrow.",),
        ),
        (
            "Can you introduce me to {person}? I have a question about the reports.",
            ("Of course, I'll copy you both in an email.",),
        ),
        (
            "Have you seen the latest numbers from the warehouse? Something looks wrong.",
            ("I saw it. Probably the late load. Check again in an hour.",),
        ),
        (
            "I'm leaving a bit early today. Message me if anything comes up.",
            (),
        ),
        (
            "Do you have a template for a design doc?",
            ("Yes, I'll share it.",),
        ),
        (
            "Is it okay if I move our 1:1 to {day}?",
            ("Fine with me.",),
        ),
        (
            "Can you cover standup for me tomorrow? I'm on a train.",
            ("Sure.",),
        ),
        (
            "Heads up, the meeting room is double booked at {time}.",
            ("I'll move to room 5.",),
        ),
        (
            "Did you get my email about the offsite budget?",
            ("Yes, I'll reply by {day}.",),
        ),
        (
            "What do you think about the new standing desks?",
            ("Love them. Back pain is gone.",),
        ),
        (
            (
                "I need an extra pair of eyes on a query. It returns different results on staging "
                "and production."
            ),
            ("Send it over. Which environment is correct?",),
        ),
        (
            "Could you recommend a book on distributed systems?",
            ("Start with one that's practical. I'll send the title.",),
        ),
        (
            "Thanks for taking over {issue}. Let me know if you need context.",
            ("Appreciate it. I'll pick up on {day}.",),
        ),
        (
            "Could you check if the VPN works for you? Mine keeps disconnecting.",
            ("Works fine for me, try updating the client.",),
        ),
        (
            "Who's the best person to ask about timezone handling in the scheduler?",
            ("{person} wrote most of it.",),
        ),
        (
            "Hi, I'm new, could you show me where the runbooks are?",
            ("Welcome. They're in the handbook repository, docs folder.",),
        ),
        (
            "Do you want to present the sprint review together?",
            ("Yes, I'll do the first half.",),
        ),
        (
            "Late reply, sorry. I'll look at {issue_title} today.",
            (),
        ),
        (
            "Can you send me the slides from yesterday?",
            ("Yes, in the shared drive.",),
        ),
        (
            "Did you see the email from finance about the budget?",
            ("Yes. Nothing urgent.",),
        ),
        (
            "Are you around next week? I want to run something by you.",
            ("Yes, Monday and Wednesday are good.",),
        ),
        (
            "I fixed that bug in {repo}, it was a one line change.",
            ("Nice, thanks.",),
        ),
        (
            "Quick sync at {time}?",
            ("Joining.",),
        ),
        (
            "I'll be offline for the next hour while I debug.",
            (),
        ),
        (
            "Could you restart the staging job? I don't have access.",
            ("Done, you should be able to see it now.",),
        ),
        (
            "Want to grab a coffee and talk about career stuff?",
            ("Always. {day} afternoon?",),
        ),
        (
            "Could you review my draft for the on-call handover?",
            ("Sure, send it.",),
        ),
        (
            "Could you share your notes on the migration for {repo}? Mine are incomplete.",
            ("Pasting them in the doc and sending the link.",),
        ),
        (
            "Do you have ten minutes to walk me through {issue}? I'm picking it up tomorrow.",
            ("Sure, call me after {time}.",),
        ),
        (
            "Can you look at {issue} before {day}? It's blocking me a bit.",
            ("Yes, I'll do it this afternoon.",),
        ),
        (
            "Hey {person}, have you got time for a quick call at {time}?",
            ("Sure, call me. Thanks.",),
        ),
        (
            "Do you remember where we documented the rollback for {repo}?",
            ("In the handbook, under releases.",),
        ),
        (
            "I'll be 10 minutes late to our 1:1 on {day}.",
            ("No problem.",),
        ),
        (
            "Could you share your notes from the {repo} review?",
            ("Sending them now.",),
        ),
        (
            "Free for a quick chat about {issue_title}?",
            ("In 15 minutes.",),
        ),
        (
            "Thanks for picking up {issue}. I'll send you what I have.",
            (),
        ),
        (
            "Can you check my pull request on {repo}? It's tiny.",
            ("ok, on it.",),
        ),
        (
            "I need to reschedule our {time} catch up. Is {day} OK?",
            ("Works.",),
        ),
        (
            "Sorry for the late reply on {issue}. I'll get to it tomorrow.",
            (),
        ),
        (
            "Quick heads up, I changed the settings on {repo} in staging.",
            ("Thanks, I'll watch for odd behaviour.",),
        ),
        (
            "Could you take over {issue} while I'm away next week?",
            ("Sure, write down where you are.",),
        ),
        (
            "Who is the right person for questions about the warehouse?",
            ("{person}. They know it best.",),
        ),
        (
            "Are you in the office on {day}? I'd like to sit together for an hour.",
            ("Yes, see you at {time}.",),
        ),
        (
            "Do you want to split {issue}? You take the migration, I take the code.",
            ("Deal. Thanks.",),
        ),
        (
            "Hey, quick question about {repo}. What does the retry setting do?",
            ("It controls how many times a failed charge is retried. Default is three.",),
        ),
        (
            "Can I borrow your notes on onboarding? Planning a session.",
            ("Sure, sharing now.",),
        ),
        (
            "I owe you a coffee for helping with {issue}.",
            ("I'll hold you to it.",),
        ),
        (
            "Can we do the 1:1 as a walk on {day}?",
            ("Love it. Thanks.",),
        ),
        (
            "Do you have a minute? I'd like to show you something in {repo}.",
            ("Come over.",),
        ),
        (
            "I'm stuck on the same thing as yesterday. Could you pair for 20 minutes?",
            ("Joining you in a moment.",),
        ),
        (
            "{person} mentioned you worked on the date handling. Could I ask a few questions?",
            ("Happy to help.",),
        ),
        (
            "Did you get my message about the access request?",
            ("Yes, approved this morning.",),
        ),
        (
            "Can you review my notes before I send them to the team?",
            ("Reading now. Thanks.",),
        ),
        (
            "I'll cover your {time} standup on {day}.",
            ("Thank you!",),
        ),
        (
            "Hi, do you know if the pager rota is final for next month?",
            ("Not yet, I'll ping you when it is.",),
        ),
        (
            "Running late, start without me.",
            (),
        ),
        (
            "Quick sanity check: is the production deploy for {repo} today or tomorrow?",
            ("Today, around {time}.",),
        ),
        (
            "Are you free to talk through the design for {issue_title}?",
            ("Yes, send a time.",),
        ),
        (
            "Can you remind me of the staging password rotation steps?",
            ("Handbook, rotating credentials page.",),
        ),
        (
            "Do you want to join the interview panel on {day}?",
            ("Sure, send details.",),
        ),
        (
            "Do you still have the old spreadsheet with the account mappings?",
            ("Let me dig it out.",),
        ),
        (
            "I saw your comment on {issue}. Good point, I'll update the description.",
            (),
        ),
        (
            "I think I broke the staging build for {repo}. Looking.",
            ("No worries, just revert.",),
        ),
        (
            "Hey {person}, congrats on the launch.",
            ("Thank you, it was a team effort.",),
        ),
        (
            "Are you using the shared meeting room at {time}? I need it for a call.",
            ("No, it's yours.",),
        ),
        (
            "I'm struggling to find the right person to ask about expenses.",
            ("Finance has a helpdesk channel.",),
        ),
        (
            "Did you manage to look at the logs for {repo}?",
            ("Yes, nothing unusual. I'll write it up.",),
        ),
        (
            "Thanks for explaining the retry logic. It made sense.",
            (),
        ),
        (
            "Can you recommend a good reading list for new joiners?",
            ("I'll send mine.",),
        ),
        (
            "I can't join the {time} meeting. Could you take notes?",
            ("Sure. Thanks.",),
        ),
        (
            "Quick question: do I need approval to change the alert thresholds for {repo}?",
            ("Just tell the team in the channel.",),
        ),
        (
            "Mind if I use your sketch from the handbook in my talk?",
            ("Go for it.",),
        ),
        (
            "I merged your change in {repo}. Please keep an eye on it after deploy.",
            (),
        ),
        (
            "Did you hear about the reorg? I'm confused about who reports where.",
            ("Not yet. Wait for the announcement.",),
        ),
        (
            "Can you add me to the {repo} team in the pager tool?",
            ("Done. Thanks.",),
        ),
        (
            "Let's pair on {issue} after lunch.",
            ("Perfect. Thanks.",),
        ),
        (
            "Do you have the contact for the processor support team?",
            ("It's in the contacts doc.",),
        ),
        (
            "Is it okay if I take {day} off? I'll have everything handed over.",
            ("Yes, enjoy.",),
        ),
        (
            "Which room is the workshop in on {day}?",
            ("Room 6, starts at {time}.",),
        ),
        (
            "What do you think about moving the standup to the afternoon?",
            ("I prefer mornings, but could try it.",),
        ),
        (
            "Please review the doc I shared. I'd value a skeptical eye.",
            ("Reading carefully. Comments soon.",),
        ),
        (
            "Do we have an owner for {issue}? I'd like to help.",
            ("Not yet. Take it.",),
        ),
        (
            "Sorry, wrong channel. Please ignore.",
            (),
        ),
        (
            "Do you have thoughts on whether we should split {repo}?",
            ("Not now. Let's wait until after the quarter.",),
        ),
        (
            "Hey, how's the first week going?",
            ("Good, just a lot to learn.",),
        ),
        (
            "How did the customer call go?",
            ("Fine. They want {issue} fixed soon.",),
        ),
        (
            "Can you introduce me to the person who owns the invoices export?",
            ("That's {person}. I'll introduce you.",),
        ),
        (
            "Could you give me a hand moving desks on {day}?",
            ("Sure, what time?",),
        ),
        (
            "Thanks for covering the on-call last night.",
            ("No problem. Thanks.",),
        ),
        (
            "I'll need your sign off on the access request by {day}.",
            ("Signed.",),
        ),
        (
            "Do you remember what we decided about the rollback policy?",
            ("Roll back first, investigate after.",),
        ),
        (
            "Free to chat about career growth next week?",
            ("Yes, book something.",),
        ),
        (
            "Any chance you could cover standup on {day}? I have a train.",
            ("Yes. Thanks.",),
        ),
        (
            "Sorry, I ran out of battery. Can we move to {time}?",
            ("Fine.",),
        ),
        (
            "Hey {person}, can you share the link to the dashboard?",
            ("Sent by email. Thanks.",),
        ),
        (
            "Do you know how to turn off the pager notification sounds?",
            ("Settings, notifications, tick quiet hours.",),
        ),
        (
            "I'm working from the library today, back in the office on {day}.",
            (),
        ),
        (
            "Are you going to the all hands? Want to share a table afterwards?",
            ("Yes, let's.",),
        ),
        (
            "Can you help me understand {issue_title}? I don't have the background.",
            ("Sure. Short version: it only breaks for annual plans.",),
        ),
        (
            "What did you think of the design review?",
            ("Good. A few concerns about migration timing.",),
        ),
        (
            "I'm leaving at {time} today.",
            (),
        ),
        (
            "Do you have a minute to look at an odd query result?",
            ("Sure, send it. Thanks.",),
        ),
        (
            "I wanted to say thanks for the help with the release.",
            (),
        ),
        (
            "Do you need anything from me before {day}?",
            ("No, we're good.",),
        ),
        (
            "Do you have notes from the {repo} architecture meeting?",
            ("Saved in the shared folder.",),
        ),
        (
            "Could we skip our 1:1 this week? Nothing new to talk about.",
            ("Fine with me. Thanks.",),
        ),
        (
            "I'll send you the invoice for the conference.",
            ("Thanks, I'll forward it to finance.",),
        ),
        (
            "I'm swamped. Can you take the {repo} review?",
            ("I'll do it.",),
        ),
        (
            "Remember to update the rota before {day}.",
            (),
        ),
        (
            "I saw your lightning talk. Great job.",
            (),
        ),
        (
            "What time is the sprint review?",
            ("{time} on {day}.",),
        ),
        (
            "Hey, got a second? Wondering about the release plan.",
            (),
        ),
        (
            "Is {person} off today? I can't reach them.",
            ("Out until {day}.",),
        ),
        (
            "Do you want to share a taxi to the offsite?",
            ("Yes, I'll book it.",),
        ),
        (
            "Could you resend the meeting link?",
            ("Sent.",),
        ),
        (
            "Do you still use the old build tool? I'd like to remove it.",
            ("No, go ahead.",),
        ),
        (
            "Can I ask a dumb question about {repo}?",
            ("There are no dumb questions. Ask away.",),
        ),
        (
            "I put together a draft of the postmortem. Can you check it?",
            ("ok, sure.",),
        ),
        (
            "My calendar says we have a meeting but I can't find the invite.",
            ("Sending again.",),
        ),
        (
            "Thanks for the intro to {person}. We had a great chat.",
            (),
        ),
        (
            "Do you want to run the sprint planning next time?",
            ("Sure, I'd like that.",),
        ),
        (
            "Can you remind me what {issue} is about?",
            ("Credit notes for partial refunds, I think.",),
        ),
        (
            "What's your take on the new linting rules?",
            ("Fine, just a little noisy at first.",),
        ),
        (
            "I lost my notebook. Have you seen a black one?",
            ("Check meeting room 4.",),
        ),
        (
            "Are you going to the meetup on {day}?",
            ("I might, depends on traffic.",),
        ),
        (
            "I reviewed your design doc. Notes are in the doc, nothing blocking.",
            (),
        ),
        (
            "Just a note that I'll be on a call from {time}. Don't be alarmed if I'm quiet.",
            (),
        ),
        (
            "Could you rerun the failing job in {repo}? I don't have permissions.",
            ("ok, done.",),
        ),
        (
            "How do you want to handle the handover for {issue}?",
            ("A short doc plus a 15 minute call.",),
        ),
        (
            "Do you need a hand with the migration on {day}?",
            ("It would help to have a second set of eyes.",),
        ),
        (
            "Quick favour: could you check the typo in the {repo} README?",
            ("Fixed.",),
        ),
        (
            "Heard you're moving to a new team. Congrats.",
            ("Thanks, I'll still be around.",),
        ),
        (
            "Your walkthrough of {repo} was brilliant.",
            ("Thanks, glad it helped.",),
        ),
        (
            "Is lunch on? I'm starving.",
            ("Yes, give me five.",),
        ),
        (
            "Late reply but yes, I'm in for the quiz night.",
            (),
        ),
        (
            "Could you help me find the on-call history for {repo}?",
            ("It's in the pager tool, under incidents.",),
        ),
        (
            "I need to cancel our {time} slot. Something came up.",
            ("No worries. Thanks.",),
        ),
        (
            "Can you remind me of your preferred pronouns? I want to get it right.",
            ("She and her. Thanks for asking.",),
        ),
        (
            "Do you know a good place for a team dinner?",
            ("The Italian place near the station is nice.",),
        ),
        (
            "Please let me know if you need anything for {issue}.",
            (),
        ),
        (
            "I'm taking {day} off, but I can be reached if urgent.",
            (),
        ),
        (
            "Sending you the deck for review.",
            ("Got it.",),
        ),
        (
            "Quick vote: Thursday or Friday for the team lunch?",
            ("Thursday.",),
        ),
        (
            "Sorry I snapped in the meeting. It was a long week.",
            ("It's fine. Thanks for saying.",),
        ),
        (
            "Can you give me access to the {repo} dashboards?",
            ("Sent the invite.",),
        ),
        (
            "I forgot to say, I closed {issue}. It was a duplicate.",
            (),
        ),
        (
            "Do you have a spare adapter?",
            ("Check the drawer on my desk.",),
        ),
        (
            "Are the slides ready for {day}?",
            ("Almost. Done by {time}.",),
        ),
        (
            "Can you send me the link to the planning doc?",
            ("Here you go.",),
        ),
        (
            "Hey {person}, can you cover the {time} sync? I have a call.",
            ("Sure. Cheers.",),
        ),
        (
            "I'm late, traffic. Start the review without me.",
            (),
        ),
        (
            "Do you want to look at {issue} together tomorrow?",
            ("Yes, morning is best.",),
        ),
        (
            "Thanks for the heads up about the deploy window for {repo}.",
            (),
        ),
        (
            "Quick one: which environment is {repo} pointing at for you?",
            ("Staging. Check the config.",),
        ),
        (
            "I'll send you the contract notes after lunch.",
            ("Thanks.",),
        ),
        (
            "Are you okay with me presenting your slides on {day}?",
            ("Absolutely.",),
        ),
        (
            "Did you see what {person} wrote in the channel?",
            ("Yes, I'll reply later.",),
        ),
        (
            "Do you know whether {issue} is still planned for this sprint?",
            ("I think so. Check the board.",),
        ),
        (
            "Please remind me about the {day} dentist thing, I'll forget.",
            ("Ha, will do.",),
        ),
        (
            "Do you have time to talk about the new process for approving expenses?",
            ("Yes, after {time}.",),
        ),
    ),
}

RELEASE_NOTES_INTRO: tuple[str, ...] = (
    "{repo} {version} is out.",
    "Just shipped {repo} {version}.",
    "{repo} {version} released, changes below.",
    "New release of {repo}: {version}.",
    "{repo} {version} went out this morning.",
    "Release notes for {repo} {version}.",
    "We cut {repo} {version} today, here is what is in it.",
    "{repo} {version} is live in production.",
    "Heads up, {repo} {version} is now deployed.",
    "{repo} {version} is available. Fixes in this one:",
    "Tagged {repo} {version}. Included in this release:",
    "Out now: {repo} {version}.",
)

INCIDENT_REPLIES: tuple[str, ...] = (
    "I can take a look if nobody has it yet.",
    "Seeing the same thing on my side.",
    "Checking the dashboards now.",
    "Is this affecting customers or just the internal side?",
    "Might be related to the deploy earlier today.",
    "I'll check the logs and report back.",
    "Looks like it cleared on its own, but I'll keep watching.",
    "Can you share the alert link?",
    "Nothing in the provider status page yet.",
    "I can reproduce it on staging as well.",
    "Did anything change in the config recently?",
    "I'm free, want me to join a call?",
    "Adding it to the on-call notes.",
    "That host had a similar blip last week.",
    "Graph shows a spike and then back to normal.",
    "I'll open an issue so we don't forget it.",
    "Restarting the worker usually helps with this one.",
    "Looking at the slow query log.",
    "Can someone from platform confirm?",
    "I'm on it, will update in this thread.",
)

DEPLOY_NOTES: tuple[str, ...] = (
    "deploying {repo} to production now",
    "Deploying {repo} to staging first, production in about an hour.",
    "{repo} deploy starting, will post when it is done.",
    "{repo} is deployed, dashboards look normal.",
    "rolling out {repo} now, give it ten minutes",
    "Starting the {repo} deploy. Shout if you see anything odd.",
    "{repo} deploy finished, no alerts so far.",
    "pushing {repo} to production, back shortly",
    "Small {repo} deploy going out, config change only.",
    "{repo} is going out now. Please hold merges until it finishes.",
    "{repo} deploy paused, waiting on a migration to finish.",
    "Resuming the {repo} deploy.",
    "{repo} rolled back to the previous version, looking into why.",
    "Done: {repo} is live on production.",
    "deploy of {repo} complete, smoke check passed",
)
