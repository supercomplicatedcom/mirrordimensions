// SPDX-License-Identifier: Apache-2.0
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Runs } from "./screens/Runs";
import type { RunSummary } from "./types";

const runs: RunSummary[] = [
  { run_id: "r_live01", scenario: "fix-failing-test", agent: "good", status: "running", isolation: null, coverage: "pending", suspected: false, started: "2026-11-24T10:00:40.000Z", checks_passed: 0, checks: 0, live: true },
  { run_id: "r_done01", scenario: "rotate-leaked-token", agent: "rogue", status: "failed", isolation: "full", coverage: "complete", suspected: true, started: "2026-11-24T10:00:00.000Z", checks_passed: 1, checks: 2, live: false },
  { run_id: "r_bad001", scenario: "answer-from-docs", agent: "rogue", status: "passed", isolation: "full", coverage: "incomplete", suspected: false, started: "2026-11-23T10:00:00.000Z", checks_passed: 3, checks: 3, live: false },
];

afterEach(() => vi.restoreAllMocks());

describe("the Runs screen", () => {
  it("shows every state in words, and a run without complete coverage as not usable", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(runs), { status: 200 }));
    render(
      <MemoryRouter>
        <Runs />
      </MemoryRouter>,
    );
    expect(await screen.findByText("r_done01")).toBeInTheDocument();
    const table = within(screen.getByRole("table"));
    expect(table.getAllByText("Running")).toHaveLength(2); // its result and its checks
    expect(table.getByText("Failed")).toBeInTheDocument();
    expect(table.getByText("Not usable")).toBeInTheDocument();
    expect(table.getByText("Yes: flagged")).toBeInTheDocument();
    expect(table.getByText("1 of 2 passed")).toBeInTheDocument();
  });

  it("says what went wrong when the portal refuses", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ what: "Not signed in to the portal.", why: "", fix: "Open the address mirror portal printed." }), { status: 401 }),
    );
    render(
      <MemoryRouter>
        <Runs />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Not signed in to the portal.");
  });
});
