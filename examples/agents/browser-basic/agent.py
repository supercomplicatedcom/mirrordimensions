# SPDX-License-Identifier: Apache-2.0
"""Sign in to the code host in the shared browser and acknowledge the first open issue
assigned to me with a comment. Settings come from the environment."""

from __future__ import annotations

import os
import re
import sys

from playwright.sync_api import sync_playwright

GIT = os.environ["GITEA_URL"].rstrip("/")
USER = os.environ["GITEA_USERNAME"]
PASSWORD = os.environ["GITEA_PASSWORD"]
CDP = os.environ["BROWSER_CDP_URL"]
NOTE = "Picked this up. I'll look into it today and post what I find here."
ISSUE_LINK = re.compile(r"^/[^/]+/[^/]+/issues/\d+$")


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
        page.goto(f"{GIT}/user/login")
        page.fill("#user_name", USER)
        page.fill("#password", PASSWORD)
        page.locator("form[action='/user/login'] button.primary").click()
        page.wait_for_load_state()
        if "/user/login" in page.url:
            print("sign-in failed", file=sys.stderr)
            return 1
        page.goto(f"{GIT}/issues?type=assigned&state=open")
        links = [
            href
            for href in page.locator("a[href*='/issues/']").evaluate_all(
                "els => els.map(e => e.getAttribute('href'))"
            )
            if href and ISSUE_LINK.match(href)
        ]
        if not links:
            print("nothing assigned to me", file=sys.stderr)
            return 0
        issue = sorted(set(links))[0]
        page.goto(GIT + issue)
        form = page.locator("#comment-form")
        form.locator("textarea[name='content']").fill(NOTE)
        form.locator("#comment-button").click()
        page.wait_for_selector(f"text={NOTE}")
        print(f"commented on {issue}")
        page.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
