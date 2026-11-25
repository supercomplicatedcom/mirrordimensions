// SPDX-FileCopyrightText: 2026 Supercomplicated LLC
// SPDX-License-Identifier: Apache-2.0
// One test per screen: it shows the project's data, it can be used by keyboard, and an
// automated accessibility check finds no serious or critical issues.

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const TOKEN = "test-token";
const FINISHED = "r_fixture0001";

async function signIn(page: Page) {
  await page.goto(`/?token=${TOKEN}`);
  await expect(page).toHaveURL(/\/environment$/);
}

async function accessible(page: Page) {
  const found = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const serious = found.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  expect(
    serious.map(
      (v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
    ),
  ).toEqual([]);
}

test.beforeEach(async ({ page }) => {
  await signIn(page);
});

test("Environment: the map, its table view and the detail panel", async ({
  page,
}) => {
  await expect(
    page.getByRole("heading", { name: "Environment", level: 1 }),
  ).toBeVisible();
  const map = page.getByRole("region", { name: "Environment map" });
  await expect(map.getByRole("button", { name: /Code hosting/ })).toBeVisible();
  await expect(map.getByRole("button", { name: /Gateway/ })).toBeVisible();
  // Keyboard: a system can be reached and chosen without a mouse.
  await map.getByRole("button", { name: /Code hosting/ }).focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("complementary", { name: "Selected" }),
  ).toContainText("Hostname the agent sees");
  await accessible(page);
  await page.getByRole("button", { name: "Show as a table" }).click();
  await expect(
    page.getByRole("rowheader", { name: "Code hosting" }),
  ).toBeVisible();
  await page.getByLabel("Overlay a run").selectOption(FINISHED);
  await expect(
    page.getByRole("columnheader", { name: "Touched in the run" }),
  ).toBeVisible();
  await accessible(page);
});

test("Agents: registered agents with the person each acts as and the last result", async ({
  page,
}) => {
  await page.getByRole("link", { name: "Agents" }).click();
  await expect(
    page.getByRole("heading", { name: "Agents", level: 1 }),
  ).toBeVisible();
  const rogue = page.getByRole("row", { name: /scripted-rogue/ });
  await expect(rogue).toContainText("Hosted container");
  await expect(rogue).toContainText("Failed");
  await expect(page.getByRole("row", { name: /scripted-good/ })).toContainText(
    "Running",
  ); // its run in progress
  await accessible(page);
});

test("Permissions: grants set against the last run", async ({ page }) => {
  await page.goto("/permissions/scripted-rogue");
  await expect(
    page.getByRole("heading", { name: "What scripted-rogue can reach" }),
  ).toBeVisible();
  await expect(page.getByText(`set against its last run`)).toBeVisible();
  await expect(
    page.getByRole("row", { name: /billing-service/ }),
  ).toContainText("Matches the job");
  await page.getByLabel("Agent").selectOption("scripted-good");
  await expect(page.getByText("grants only")).toBeVisible();
  await accessible(page);
});

test("Company: people, projects and planted secrets", async ({ page }) => {
  await page.getByRole("link", { name: "Company" }).click();
  await expect(page.getByRole("heading", { name: "People" })).toBeVisible();
  const before = await page.getByRole("row").count();
  await page.getByLabel("Search").fill("engineer");
  await expect
    .poll(async () => page.getByRole("row").count())
    .toBeLessThan(before);
  await page.getByRole("button", { name: "Planted secrets" }).click();
  await expect(
    page.getByRole("heading", { name: "Planted secrets" }),
  ).toBeVisible();
  await accessible(page);
});

test("Scenarios: built-in scenarios with how the work arrives", async ({
  page,
}) => {
  await page.getByRole("link", { name: "Scenarios" }).click();
  const row = page.getByRole("row", { name: /rotate-leaked-token/ }).first();
  await expect(row).toContainText("An assigned issue");
  await page.getByLabel("Kind").selectOption("injection");
  await expect(
    page.getByRole("row", { name: /rotate-leaked-token/ }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("row", { name: /bump-dependency/ }).first(),
  ).toBeVisible();
  await accessible(page);
});

test("Runs: every run with its result in words", async ({ page }) => {
  await page.getByRole("link", { name: "Runs" }).click();
  await expect(
    page.getByRole("row", { name: new RegExp(FINISHED) }),
  ).toContainText("Failed");
  await expect(page.getByRole("row", { name: /r_fixture0002/ })).toContainText(
    "Running",
  );
  await accessible(page);
});

test("Run detail: a broken forbidden check opens the request that broke it", async ({
  page,
}) => {
  await page.goto(`/runs/${FINISHED}`);
  const broke = page.getByRole("note").filter({ hasText: "BROKE" });
  await expect(broke).toContainText("mattermost.message_contains");
  await expect(broke).toBeInViewport(); // visible without scrolling
  await broke
    .getByRole("button", { name: /Open the request that broke it/ })
    .click();
  const row = page
    .getByRole("row", { name: /POST/ })
    .filter({ hasText: "Forbidden check broke here" });
  await expect(row).toHaveAttribute("aria-selected", "true");
  const detail = page.getByRole("complementary").filter({ hasText: "Event 7" });
  await expect(detail).toContainText("pk_live_planted"); // the stored request body
  // The timeline pages: 609 events, 500 at a time.
  await expect(page.getByText("Events 1 to 500 of 609")).toBeVisible();
  await page.getByRole("button", { name: "Later events" }).click();
  await expect(page.getByText("Events 501 to 609 of 609")).toBeVisible();
  await accessible(page);
});

test("Health: project, engine and snapshots, and checks that can be run", async ({
  page,
}) => {
  await page.getByRole("link", { name: "Health" }).click();
  await expect(
    page.getByRole("heading", { name: "Health", level: 1 }),
  ).toBeVisible();
  await expect(
    page.getByText("The isolation checks have not run yet."),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Run all checks" }),
  ).toBeVisible();
  await accessible(page);
});

test("Every screen can be reached from the keyboard", async ({ page }) => {
  for (const name of [
    "Agents",
    "Permissions",
    "Company",
    "Scenarios",
    "Runs",
    "Health",
    "Environment",
  ]) {
    await page.getByRole("link", { name, exact: true }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("link", { name, exact: true })).toHaveAttribute(
      "aria-current",
      "page",
    );
  }
});

test("Live view: a finished run replays step by step, a live one follows", async ({
  page,
}) => {
  await page.goto(`/runs/${FINISHED}`);
  await page.getByRole("link", { name: "Replay it step by step" }).click();
  await expect(
    page.getByRole("heading", { name: "Watching scripted-rogue work" }),
  ).toBeVisible();
  const now = page.getByRole("region", { name: "Now" });
  // A finished run opens paused at the first step.
  await expect(now).toContainText("Work arrives");
  await expect(page.getByText("Step 1 of 6")).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(now).toContainText("Searches issues");
  await expect(now).toContainText("Code hosting");
  // Jump: the step that broke a rule says so in words, not color alone.
  await page.getByRole("slider", { name: "Jump to a step" }).fill("3");
  await expect(now).toContainText("Posts in #incidents");
  await expect(now).toContainText("rule broken");
  await expect(
    page.getByRole("img", {
      name: /scripted-rogue is at Team chat, #incidents/,
    }),
  ).toBeVisible();
  await expect(page.getByText("1 rules broken")).toBeVisible();
  await accessible(page);
  // Play moves on by itself; Back steps back.
  await page.getByRole("button", { name: "Play" }).click();
  await expect(now).toContainText("Thinks", { timeout: 4000 });
  await page.getByRole("button", { name: "Pause" }).click();
  await page.getByRole("button", { name: "Back" }).click();
  await expect(now).toContainText("Posts in #incidents");
  // The raw events stay one click away.
  await page
    .getByRole("link", { name: "Its 2 events in the timeline" })
    .click();
  await expect(
    page.getByRole("row", { name: /POST.*api\/v4\/posts/ }).first(),
  ).toBeVisible();
  // A run in progress follows its stream.
  await page.goto("/runs/r_fixture0002/live");
  await expect(page.getByText("Live", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Stop the run" }),
  ).toBeVisible();
  await accessible(page);
});

test("Live view: with reduced motion the marker jumps instead of gliding", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(`/runs/${FINISHED}/live`);
  await expect(page.getByRole("region", { name: "Now" })).toContainText(
    "Work arrives",
  );
  const glide = await page
    .locator(".marker")
    .first()
    .evaluate((el) => getComputedStyle(el).transitionDuration);
  expect(glide).toBe("0s");
});

// Edits change the fixture project, so each test below puts back what it changed.

test("Environment: changing a system's visibility saves it and shows it as pending", async ({
  page,
}) => {
  await page.goto("/environment");
  const map = page.getByRole("region", { name: "Environment map" });
  await map.getByRole("button", { name: /Team chat/ }).click();
  const panel = page.getByRole("complementary", { name: "Selected" });
  await panel.getByRole("radio", { name: /Denied/ }).check();
  await expect(panel.getByRole("status")).toContainText(
    "takes effect at the next run",
  );
  const pending = page.getByRole("region", { name: /not in effect yet/ });
  await expect(pending).toContainText(
    "Team chat: visibility granted to denied",
  );
  await expect(pending).toContainText("Next run");
  await expect(map.getByRole("button", { name: /Team chat/ })).toContainText(
    "Denied",
  );
  await accessible(page);
  await panel.getByRole("radio", { name: /Granted/ }).check();
  await expect(pending).toBeHidden();
});

test("Permissions: a grant is edited and saved to the agent file", async ({
  page,
}) => {
  await page.goto("/permissions/scripted-good");
  const grant = page.getByLabel("Grant on infra-config");
  await expect(grant).toHaveValue("none");
  await grant.selectOption("read");
  await expect(
    page.getByRole("status").filter({ hasText: "Saved to the agent file" }),
  ).toContainText("code/infra-config none to read");
  await expect(page.getByLabel("Grant on infra-config")).toHaveValue("read");
  await expect(page.getByLabel("Grant on #incidents")).toHaveValue("member");
  await accessible(page);
  await page.getByLabel("Grant on infra-config").selectOption("none");
  await expect(page.getByLabel("Grant on infra-config")).toHaveValue("none");
});

test("System: every endpoint with its input and output, and a rule saved from the form", async ({
  page,
}) => {
  await page.goto("/environment");
  await page
    .getByRole("region", { name: "Environment map" })
    .getByRole("button", { name: /Code hosting/ })
    .click();
  await page
    .getByRole("link", { name: "Inputs and outputs of Code hosting" })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Code hosting: inputs and outputs",
      level: 1,
    }),
  ).toBeVisible();
  const row = page.getByRole("row", { name: /GET \/api\/v1\/repos\/search/ });
  await expect(row).toContainText("A list of repositories");
  await expect(row).toContainText("Preconfigured");
  await row.getByRole("button").click();
  const form = page.getByRole("complementary", { name: "Selected endpoint" });
  await form.getByLabel("Added delay from, ms").fill("800");
  await form.getByLabel("to, ms").fill("2500");
  await form.getByRole("button", { name: "Save rule" }).click();
  await expect(form.getByRole("status").first()).toContainText(
    "rule repo-search added",
  );
  await expect(
    page.getByRole("row", { name: /GET \/api\/v1\/repos\/search/ }),
  ).toContainText("Customized: slow, 0.8 s to 2.5 s");
  await expect(
    page.getByRole("region", { name: /not in effect yet/ }),
  ).toContainText("Code hosting: rule repo-search added");
  await accessible(page);
  await form.getByRole("button", { name: "Remove rule repo-search" }).click();
  await expect(
    page.getByRole("row", { name: /GET \/api\/v1\/repos\/search/ }),
  ).toContainText("Preconfigured");
});

test("World wizard: six steps write mirror.yaml as they go, as the command line would", async ({
  page,
}) => {
  await page.goto("/environment");
  await page.getByRole("link", { name: "Switch or define a world" }).click();
  await expect(
    page.getByRole("heading", { name: "Worlds", level: 1 }),
  ).toBeVisible();
  await expect(page.getByRole("row", { name: /northfield-ops/ })).toContainText(
    "Served now",
  );
  await accessible(page);
  await page.getByRole("link", { name: "Define a new world" }).click();
  await page.getByLabel(/Folder/).fill("acme-ops");
  await page.getByRole("button", { name: "Start" }).click();
  await expect(
    page.getByRole("heading", { name: "How do you want to start?" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(
    page.getByRole("heading", { name: "The company" }),
  ).toBeVisible();
  const yaml = page.getByRole("complementary", { name: /mirror.yaml/ });
  await expect(yaml).toContainText("status: draft");
  await page.getByLabel("Company name").fill("Halvorsen Freight");
  await page.getByLabel(/Domain/).fill("halvorsen-freight.com");
  await page.getByLabel("People").fill("40");
  await page.getByRole("radio", { name: "Messy" }).check();
  await accessible(page);
  await page.getByRole("button", { name: "Next" }).click();
  await expect(
    page.getByRole("heading", { name: "The systems attached to it" }),
  ).toBeVisible();
  await expect(page.getByRole("row", { name: /code hosting/i })).toContainText(
    "git.halvorsen-freight.com",
  );
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByLabel("Issues", { exact: true }).fill("90");
  await page.getByLabel(/announced in a chat channel/).uncheck();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(
    page.getByRole("heading", { name: "Review what will be created" }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Halvorsen Freight (halvorsen-freight.com), 40 people, 180 days of history, messy data",
    ),
  ).toBeVisible();
  await expect(yaml).toContainText("issues: 90");
  await expect(yaml).toContainText("--no-announce");
  await page.getByRole("button", { name: "Looks right" }).click();
  await expect(
    page.getByRole("button", { name: "Create world" }),
  ).toBeVisible(); // not pressed: it would build a real world
  await accessible(page);
  // The draft is listed, and resumes where it was left.
  await page.goto("/worlds");
  await page.getByRole("link", { name: "Continue defining acme-ops" }).click();
  await expect(
    page.getByRole("heading", { name: /Review|Create/ }).first(),
  ).toBeVisible();
});

test("Onboarding: a remote agent, with the reduced guarantees shown and accepted", async ({
  page,
}) => {
  await page.goto("/agents/new");
  await page.getByLabel(/Name/).fill("vendor-helper");
  await page.getByRole("button", { name: "Start" }).click();
  await page.getByRole("radio", { name: /Remote gateway/ }).check();
  const notice = page.getByRole("note", { name: "Reduced guarantees" });
  await expect(notice).toContainText("detected but not blocked");
  await expect(page.getByLabel(/Container image/)).toBeHidden();
  const next = page.getByRole("button", { name: "Next" });
  await expect(next).toBeDisabled(); // until accepted
  await page.getByLabel(/I accept these reduced guarantees/).check();
  await accessible(page);
  await next.click();
  await expect(
    page.getByText(/On its vendor's platform. No route is configured/),
  ).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(
    page.getByRole("heading", { name: "What can it reach?" }),
  ).toBeVisible();
  // The MCP server is its way in: its tools start granted.
  await expect(page.getByLabel("Grant on search_issues")).toHaveValue(
    "allowed",
  );
  await page.getByLabel("Grant on close_issue").selectOption("none");
  await accessible(page);
  await page.getByRole("button", { name: "Next" }).click();
  await expect(
    page.getByText(/Through its vendor's own trigger/),
  ).toBeVisible();
  await page.getByRole("button", { name: "Check and finish" }).click();
  await expect(
    page.getByRole("heading", { name: "Is it ready?" }),
  ).toBeVisible();
  const file = page.getByRole("complementary", {
    name: /agents\/vendor-helper.yaml/,
  });
  await expect(file).toContainText("mode: remote");
  await expect(file).toContainText("reduced_guarantees: accepted");
  await expect(file).toContainText("search_issues");
  await expect(file).not.toContainText("close_issue");
  await expect(file).not.toContainText("image");
  await page.getByRole("link", { name: "Save and close" }).click();
  await expect(page.getByRole("row", { name: /vendor-helper/ })).toContainText(
    "Ready",
  );
  page.once("dialog", (d) => void d.accept());
  await page.getByRole("button", { name: "Remove vendor-helper" }).click();
  await expect(page.getByRole("row", { name: /vendor-helper/ })).toBeHidden();
});

test("Onboarding: an agent in six steps, from the role's usual access", async ({
  page,
}) => {
  await page.goto("/agents");
  await page.getByRole("link", { name: "Onboard an agent" }).click();
  await page.getByLabel(/Name/).fill("ops-helper");
  await page.getByRole("button", { name: "Start" }).click();
  await expect(
    page.getByRole("heading", { name: "How does the agent connect?" }),
  ).toBeVisible();
  await page.getByLabel(/Container image/).fill("ops-helper:1.0");
  await accessible(page);
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("radio", { name: /No model/ }).check();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(
    page.getByRole("heading", { name: "Who does it act as?" }),
  ).toBeVisible();
  await expect(page.getByRole("status")).toContainText("An account is issued");
  await page.getByRole("button", { name: "Next" }).click();
  await expect(
    page.getByRole("heading", { name: "What can it reach?" }),
  ).toBeVisible();
  // The role's usual access is filled in: some repository is granted already.
  const grants = page.locator('select[aria-label^="Grant on"]');
  await expect(grants.first()).toBeVisible();
  const levels = await grants.evaluateAll((all) =>
    all.map((el) => (el as HTMLSelectElement).value),
  );
  expect(levels.some((v) => v !== "none")).toBe(true);
  await page.getByLabel("Grant on #incidents").selectOption("member");
  await accessible(page);
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByLabel("Command to run").fill("python /opt/helper/run.py");
  const file = page.getByRole("complementary", {
    name: /agents\/ops-helper.yaml/,
  });
  await page.getByRole("button", { name: "Check and finish" }).click();
  await expect(
    page.getByRole("heading", { name: "Is it ready?" }),
  ).toBeVisible();
  await expect(file).toContainText("python");
  await expect(file).not.toContainText("status: draft");
  await accessible(page);
  await page.getByRole("link", { name: "Save and close" }).click();
  await expect(page.getByRole("row", { name: /ops-helper/ })).toContainText(
    "Ready",
  );
  // Leave the fixture as it was.
  page.once("dialog", (d) => void d.accept());
  await page.getByRole("button", { name: "Remove ops-helper" }).click();
  await expect(page.getByRole("row", { name: /ops-helper/ })).toBeHidden();
});
