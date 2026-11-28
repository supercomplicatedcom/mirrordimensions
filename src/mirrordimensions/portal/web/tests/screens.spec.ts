// SPDX-License-Identifier: Apache-2.0
// One test per screen: it shows the project's data, it can be used by keyboard, and an
// automated accessibility check finds no serious or critical issues.

import fs from "node:fs";
import path from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const TOKEN = "test-token";
const FINISHED = "r_fixture0001";

// The fixture world names its repositories and channels its own way (decision 0029).
function names(): Record<string, string> {
  const file = path.join(
    "test-results",
    "fixture",
    "northfield-ops",
    ".mirror",
    "world.json",
  );
  return JSON.parse(fs.readFileSync(file, "utf-8")).names ?? {};
}
const repo = (usual: string) => names()[`repo:${usual}`] ?? usual;
const channel = (usual: string) => names()[`channel:${usual}`] ?? usual;
const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

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
    page.getByRole("row", { name: new RegExp(escape(repo("billing-service"))) }),
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
  // Physical consequences: what a safety-critical command would cause, and whether it was asked for.
  const physical = page.getByRole("region", { name: "Physical consequences" });
  await expect(physical).toContainText("hold_open on server-room-door");
  await expect(physical).toContainText("stays unlocked and open");
  await expect(physical).toContainText("No: nothing in the job asked for it");
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
  await expect(now).toContainText(`Posts in #${channel("incidents")}`);
  await expect(now).toContainText("rule broken");
  await expect(
    page.getByRole("img", {
      name: new RegExp(
        `scripted-rogue is at Team chat, #${escape(channel("incidents"))}`,
      ),
    }),
  ).toBeVisible();
  await expect(page.getByText("1 rules broken")).toBeVisible();
  await accessible(page);
  // Play moves on by itself; Back steps back.
  await page.getByRole("button", { name: "Play" }).click();
  await expect(now).toContainText("Thinks", { timeout: 4000 });
  await page.getByRole("button", { name: "Pause" }).click();
  await page.getByRole("button", { name: "Back" }).click();
  await expect(now).toContainText(`Posts in #${channel("incidents")}`);
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
  const grant = page.getByLabel(`Grant on ${repo("infra-config")}`);
  await expect(grant).toHaveValue("none");
  await grant.selectOption("read");
  await expect(
    page.getByRole("status").filter({ hasText: "Saved to the agent file" }),
  ).toContainText(`code/${repo("infra-config")} none to read`);
  await expect(page.getByLabel(`Grant on ${repo("infra-config")}`)).toHaveValue("read");
  await expect(page.getByLabel(`Grant on #${channel("incidents")}`)).toHaveValue("member");
  await accessible(page);
  await page.getByLabel(`Grant on ${repo("infra-config")}`).selectOption("none");
  await expect(page.getByLabel(`Grant on ${repo("infra-config")}`)).toHaveValue("none");
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

test("World wizard: a seed folder of test data, read in place, with personal data accepted first", async ({
  page,
}, testInfo) => {
  // A synthetic folder from the repository's fixtures, read where it is (decision 0030).
  const seed = path.resolve(process.cwd(), "../../../../tests/fixtures/seed");
  const folder = testInfo.retry
    ? `halden-seeded-${testInfo.retry}`
    : "halden-seeded";
  await page.goto("/worlds/new");
  await page.getByLabel(/Folder/).fill(folder);
  await page.getByRole("button", { name: "Start" }).click();
  await expect(
    page.getByRole("heading", { name: "How do you want to start?" }),
  ).toBeVisible();
  for (const next of [
    "The company",
    "The systems attached to it",
    "How the systems connect, and how much they hold",
  ]) {
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByRole("heading", { name: next })).toBeVisible();
  }
  const panel = page.getByRole("region", {
    name: "Your own test data (optional)",
  });
  await panel.getByLabel(/Seed folder/).fill(seed);
  await panel.getByRole("button", { name: "Read the folder" }).click();
  await expect(
    panel.getByRole("table", { name: "What each file becomes" }),
  ).toContainText("people.csv");
  // The phone number is listed by file and line; nothing is used until it is accepted.
  const personal = panel.getByRole("note", { name: "Personal data" });
  await expect(personal).toContainText("runbooks/claims-backlog.md:5");
  await expect(personal).toContainText("Nothing from the folder is used");
  const yaml = page.getByRole("complementary", { name: /mirror.yaml/ });
  await expect(yaml).toContainText("--seed-folder");
  await expect(yaml).not.toContainText("--accept-personal-data");
  await accessible(page);
  const accept = panel.getByRole("button", { name: "Accept and use it" });
  await expect(accept).toBeDisabled();
  await panel.getByLabel(/This is test data/).check();
  await accept.click();
  await expect(personal).toContainText("You accepted it as test data");
  await expect(yaml).toContainText("--accept-personal-data");
  await page.getByRole("button", { name: "Next" }).click();
  await expect(
    page.getByRole("heading", { name: "Review what will be created" }),
  ).toBeVisible();
  await expect(
    page.getByText(/files from .*seed; the rest is generated/),
  ).toBeVisible();
  // Stopping goes back to an all-generated world.
  await page.getByRole("button", { name: "Back" }).click();
  await panel.getByRole("button", { name: "Stop using it" }).click();
  await expect(
    panel.getByRole("button", { name: "Read the folder" }),
  ).toBeVisible();
  await expect(yaml).not.toContainText("--seed-folder");
});

test("World import: the wizard's import step and the review, from files on this computer", async ({
  page,
}, testInfo) => {
  // Synthetic files from the repository's fixtures, read where they are (decision 0025).
  const fixtures = path.resolve(process.cwd(), "../../../../tests/fixtures/import");
  const files = ["mcp.json", "eng-tools.tools.json", "payments-api.yaml", "gitea-api.json", "terraform.json"];
  const folder = testInfo.retry ? `northfield-import-${testInfo.retry}` : "northfield-import";
  await page.goto("/worlds/new");
  await page.getByLabel(/Folder/).fill(folder);
  await page.getByRole("button", { name: "Start" }).click();
  await expect(page.getByRole("heading", { name: "How do you want to start?" })).toBeVisible();
  await page.getByRole("radio", { name: /Import a description/ }).check();
  await page.getByRole("link", { name: "Choose the files" }).click();
  await expect(page.getByRole("heading", { name: "Import a description", level: 1 })).toBeVisible();
  await page.getByLabel(/Files on this computer/).fill(files.map((f) => path.join(fixtures, f)).join("\n"));
  await page.getByRole("button", { name: "Read the files" }).click();
  await expect(page.getByRole("heading", { name: "Review what was understood", level: 1 })).toBeVisible();
  await expect(page.getByLabel("Totals")).toContainText("8things found");
  await expect(page.getByLabel("Totals")).toContainText("1disagreement to settle");
  // What was read says what was skipped; no secret or person is shown.
  const read = page.getByRole("region", { name: "What was read" });
  await expect(read).toContainText("secret values skipped, none stored");
  await expect(page.locator("body")).not.toContainText("Priya");
  // The disagreement sits above the findings, and apply waits for it.
  const apply = page.getByRole("button", { name: "Apply to the definition" });
  await expect(apply).toBeDisabled();
  await expect(page.getByText("Two sources disagree on the hostname for Gitea.")).toBeVisible();
  // The choice is shown once the draft has it, as the command line would see it.
  const choice = page.getByRole("radio", { name: /git\.northfield-logistics\.com/ });
  await choice.click();
  await expect(choice).toBeChecked();
  await expect(page.getByText(/Settled: Two sources disagree/)).toBeVisible();
  // Tools no system serves are shown as unavailable.
  const server = page.getByRole("row", { name: /eng-tools/ });
  await expect(server).toContainText("Unavailable: search_wiki");
  await page.getByLabel("Decision for shipment-events").selectOption("leave-out");
  await expect(page.getByLabel("Decision for shipment-events")).toHaveValue("leave-out");
  await accessible(page);
  await apply.click();
  // Back in the wizard: the company the import proposes, then the imported systems.
  await expect(page.getByRole("heading", { name: "The company" })).toBeVisible();
  await expect(page.getByLabel(/Domain/)).toHaveValue("northfield-logistics.com");
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByRole("heading", { name: "The systems attached to it" })).toBeVisible();
  const systems = page.getByRole("table");
  await expect(systems).toContainText("mcp.northfield-logistics.com");
  await expect(systems).toContainText("No twin yet");
  const yaml = page.getByRole("complementary", { name: /mirror.yaml/ }).locator("pre");
  await expect(yaml).toContainText("payments-api");
  await expect(yaml).not.toContainText("shipment-events"); // left out on review
  await expect(page.getByText(/The list comes from the import/)).toBeVisible();
  await accessible(page);
});

test("Onboarding: a remote agent, with the reduced protections shown and accepted", async ({
  page,
}, testInfo) => {
  // A retry gets its own name: a failed attempt can leave its draft behind.
  const name = testInfo.retry
    ? `vendor-helper-${testInfo.retry}`
    : "vendor-helper";
  const step = (title: string) =>
    expect(page.getByRole("heading", { name: title })).toBeVisible();
  await page.goto("/agents/new");
  await page.getByLabel(/Name/).fill(name);
  await page.getByRole("button", { name: "Start" }).click();
  await step("How does the agent connect?");
  await page.getByRole("radio", { name: /Remote gateway/ }).check();
  const notice = page.getByRole("note", { name: "Reduced protections" });
  await expect(notice).toContainText("detected but not blocked");
  await expect(page.getByLabel(/Container image/)).toBeHidden();
  const next = page.getByRole("button", { name: "Next" });
  await expect(next).toBeDisabled(); // until accepted
  await page.getByLabel(/I accept these reduced protections/).check();
  await accessible(page);
  await next.click();
  // Each step is waited for: a click while the next one loads would be lost.
  await step("Where does its model run?");
  await expect(
    page.getByText(/On its vendor's platform. No route is configured/),
  ).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await step("Who does it act as?");
  await page.getByRole("button", { name: "Next" }).click();
  await step("What can it reach?");
  // The MCP server is its way in: its tools start granted.
  await expect(page.getByLabel("Grant on search_issues")).toHaveValue(
    "allowed",
  );
  await page.getByLabel("Grant on close_issue").selectOption("none");
  await accessible(page);
  await page.getByRole("button", { name: "Next" }).click();
  await step("How does work reach it?");
  await expect(
    page.getByText(/Through its vendor's own trigger/),
  ).toBeVisible();
  await page.getByRole("button", { name: "Check and finish" }).click();
  await step("Is it ready?");
  const file = page.getByRole("complementary", {
    name: `agents/${name}.yaml, written as you go`,
  });
  await expect(file).toContainText("mode: remote");
  await expect(file).toContainText("reduced_guarantees: accepted");
  await expect(file).toContainText("search_issues");
  await expect(file).not.toContainText("close_issue");
  await expect(file).not.toContainText("image");
  await page.getByRole("link", { name: "Save and close" }).click();
  const row = page.getByRole("row", { name: new RegExp(`^${name}\\b`) });
  await expect(row).toContainText("Ready");
  page.once("dialog", (d) => void d.accept());
  await page.getByRole("button", { name: `Remove ${name}` }).click();
  await expect(row).toBeHidden();
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
  await page.getByLabel(`Grant on #${channel("incidents")}`).selectOption("member");
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
