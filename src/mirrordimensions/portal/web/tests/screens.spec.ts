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
  const found = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const serious = found.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
}

test.beforeEach(async ({ page }) => {
  await signIn(page);
});

test("Environment: the map, its table view and the detail panel", async ({ page }) => {
  await expect(page.getByRole("heading", { name: "Environment", level: 1 })).toBeVisible();
  const map = page.getByRole("region", { name: "Environment map" });
  await expect(map.getByRole("button", { name: /Code hosting/ })).toBeVisible();
  await expect(map.getByRole("button", { name: /Gateway/ })).toBeVisible();
  // Keyboard: a system can be reached and chosen without a mouse.
  await map.getByRole("button", { name: /Code hosting/ }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("complementary", { name: "Selected" })).toContainText("Hostname the agent sees");
  await accessible(page);
  await page.getByRole("button", { name: "Show as a table" }).click();
  await expect(page.getByRole("rowheader", { name: "Code hosting" })).toBeVisible();
  await page.getByLabel("Overlay a run").selectOption(FINISHED);
  await expect(page.getByRole("columnheader", { name: "Touched in the run" })).toBeVisible();
  await accessible(page);
});

test("Agents: registered agents with the person each acts as and the last result", async ({ page }) => {
  await page.getByRole("link", { name: "Agents" }).click();
  await expect(page.getByRole("heading", { name: "Agents", level: 1 })).toBeVisible();
  const rogue = page.getByRole("row", { name: /scripted-rogue/ });
  await expect(rogue).toContainText("Hosted container");
  await expect(rogue).toContainText("Failed");
  await expect(page.getByRole("row", { name: /scripted-good/ })).toContainText("Running"); // its run in progress
  await accessible(page);
});

test("Permissions: grants set against the last run", async ({ page }) => {
  await page.goto("/permissions/scripted-rogue");
  await expect(page.getByRole("heading", { name: "What scripted-rogue can reach" })).toBeVisible();
  await expect(page.getByText(`set against its last run`)).toBeVisible();
  await expect(page.getByRole("row", { name: /billing-service/ })).toContainText("Matches the job");
  await page.getByLabel("Agent").selectOption("scripted-good");
  await expect(page.getByText("grants only")).toBeVisible();
  await accessible(page);
});

test("Company: people, projects and planted secrets", async ({ page }) => {
  await page.getByRole("link", { name: "Company" }).click();
  await expect(page.getByRole("heading", { name: "People" })).toBeVisible();
  const before = await page.getByRole("row").count();
  await page.getByLabel("Search").fill("engineer");
  await expect.poll(async () => page.getByRole("row").count()).toBeLessThan(before);
  await page.getByRole("button", { name: "Planted secrets" }).click();
  await expect(page.getByRole("heading", { name: "Planted secrets" })).toBeVisible();
  await accessible(page);
});

test("Scenarios: built-in scenarios with how the work arrives", async ({ page }) => {
  await page.getByRole("link", { name: "Scenarios" }).click();
  const row = page.getByRole("row", { name: /rotate-leaked-token/ }).first();
  await expect(row).toContainText("An assigned issue");
  await page.getByLabel("Kind").selectOption("injection");
  await expect(page.getByRole("row", { name: /rotate-leaked-token/ })).toHaveCount(0);
  await expect(page.getByRole("row", { name: /bump-dependency/ }).first()).toBeVisible();
  await accessible(page);
});

test("Runs: every run with its result in words", async ({ page }) => {
  await page.getByRole("link", { name: "Runs" }).click();
  await expect(page.getByRole("row", { name: new RegExp(FINISHED) })).toContainText("Failed");
  await expect(page.getByRole("row", { name: /r_fixture0002/ })).toContainText("Running");
  await accessible(page);
});

test("Run detail: a broken forbidden check opens the request that broke it", async ({ page }) => {
  await page.goto(`/runs/${FINISHED}`);
  const broke = page.getByRole("note").filter({ hasText: "BROKE" });
  await expect(broke).toContainText("mattermost.message_contains");
  await expect(broke).toBeInViewport(); // visible without scrolling
  await broke.getByRole("button", { name: /Open the request that broke it/ }).click();
  const row = page.getByRole("row", { name: /POST/ }).filter({ hasText: "Forbidden check broke here" });
  await expect(row).toHaveAttribute("aria-selected", "true");
  const detail = page.getByRole("complementary").filter({ hasText: "Event 7" });
  await expect(detail).toContainText("pk_live_planted"); // the stored request body
  // The timeline pages: 609 events, 500 at a time.
  await expect(page.getByText("Events 1 to 500 of 609")).toBeVisible();
  await page.getByRole("button", { name: "Later events" }).click();
  await expect(page.getByText("Events 501 to 609 of 609")).toBeVisible();
  await accessible(page);
});

test("Health: project, engine and snapshots, and checks that can be run", async ({ page }) => {
  await page.getByRole("link", { name: "Health" }).click();
  await expect(page.getByRole("heading", { name: "Health", level: 1 })).toBeVisible();
  await expect(page.getByText("The isolation checks have not run yet.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Run all checks" })).toBeVisible();
  await accessible(page);
});

test("Every screen can be reached from the keyboard", async ({ page }) => {
  for (const name of ["Agents", "Permissions", "Company", "Scenarios", "Runs", "Health", "Environment"]) {
    await page.getByRole("link", { name, exact: true }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("link", { name, exact: true })).toHaveAttribute("aria-current", "page");
  }
});

test("Live view: a finished run replays step by step, a live one follows", async ({ page }) => {
  await page.goto(`/runs/${FINISHED}`);
  await page.getByRole("link", { name: "Replay it step by step" }).click();
  await expect(page.getByRole("heading", { name: "Watching scripted-rogue work" })).toBeVisible();
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
  await expect(page.getByRole("img", { name: /scripted-rogue is at Team chat, #incidents/ })).toBeVisible();
  await expect(page.getByText("1 rules broken")).toBeVisible();
  await accessible(page);
  // Play moves on by itself; Back steps back.
  await page.getByRole("button", { name: "Play" }).click();
  await expect(now).toContainText("Thinks", { timeout: 4000 });
  await page.getByRole("button", { name: "Pause" }).click();
  await page.getByRole("button", { name: "Back" }).click();
  await expect(now).toContainText("Posts in #incidents");
  // The raw events stay one click away.
  await page.getByRole("link", { name: "Its 2 events in the timeline" }).click();
  await expect(page.getByRole("row", { name: /POST.*api\/v4\/posts/ }).first()).toBeVisible();
  // A run in progress follows its stream.
  await page.goto("/runs/r_fixture0002/live");
  await expect(page.getByText("Live", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Stop the run" })).toBeVisible();
  await accessible(page);
});

test("Live view: with reduced motion the marker jumps instead of gliding", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(`/runs/${FINISHED}/live`);
  await expect(page.getByRole("region", { name: "Now" })).toContainText("Work arrives");
  const glide = await page.locator(".marker").first().evaluate((el) => getComputedStyle(el).transitionDuration);
  expect(glide).toBe("0s");
});
