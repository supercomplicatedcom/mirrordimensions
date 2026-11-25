// SPDX-FileCopyrightText: 2026 Supercomplicated LLC
// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { layout, markers, merge, spotOf, totals, trail, withTouched } from "./live";
import type { Place, Step, StepKind } from "./types";

const places: Place[] = [
  {
    system: "code",
    label: "Code hosting",
    kind: "system",
    resources: [
      { place: "repo:elmstead/billing-service", label: "billing-service", granted: true },
      { place: "repo:elmstead/platform-docs", label: "platform-docs", granted: true },
    ],
  },
  { system: "chat", label: "Team chat", kind: "system", resources: [{ place: "channel:incidents", label: "#incidents", granted: true }] },
];

function step(index: number, kind: StepKind, system: string, place: string | null = null, requests = 1, agent = "ops"): Step {
  return {
    index,
    start: "",
    end: "",
    at: `00:0${index}.0`,
    agent,
    location: { system, resource: place, place, label: system },
    kind,
    sentence: `step ${index}`,
    detail: "",
    events: [index + 1],
    requests,
  };
}

const run: Step[] = [
  step(0, "info", "agent", null, 0),
  step(1, "request", "code", "repo:elmstead/billing-service", 3),
  step(2, "think", "model", null, 0),
  step(3, "blocked", "outside", null, 0),
  step(4, "violation", "chat", "channel:incidents", 1),
  step(5, "end", "agent", null, 0),
];

describe("the live view's map", () => {
  it("draws every granted resource, plus the model and the outside, the same way every time", () => {
    const l = layout(places, "ops");
    expect(l.chips.map((c) => c.label)).toEqual(["billing-service", "platform-docs", "#incidents"]);
    expect(l.boxes.map((b) => b.kind)).toEqual(["system", "system", "agent", "model", "outside"]);
    expect(layout(places, "ops")).toEqual(l);
    // Nothing overlaps: each system box starts below the one before it.
    const [code, chat] = l.boxes;
    expect(chat!.y).toBeGreaterThanOrEqual(code!.y + code!.h);
  });

  it("adds a resource the agent reached that no grant named, marked as not granted", () => {
    const more = withTouched(places, [step(0, "request", "code", "repo:elmstead/payroll-exports")]);
    const code = more.find((p) => p.system === "code")!;
    expect(code.resources.at(-1)).toEqual({ place: "repo:elmstead/payroll-exports", label: "payroll-exports", granted: false });
    expect(places[0]!.resources).toHaveLength(2); // the input is left alone
  });

  it("puts the marker on the resource, else on its system, else at home", () => {
    const l = layout(places, "ops");
    expect(spotOf(l, run[1])).toEqual(l.spots["code|repo:elmstead/billing-service"]);
    expect(spotOf(l, step(9, "request", "code", "repo:elmstead/unknown"))).toEqual(l.spots.code);
    expect(spotOf(l, run[0])).toEqual(l.spots.agent);
    expect(spotOf(l, undefined)).toEqual(l.spots.agent);
  });
});

describe("the trail and the totals", () => {
  it("draws one segment per move, marks blocked and broken ones, and the latest strongest", () => {
    const l = layout(places, "ops");
    const segments = trail(l, run, 4, "ops");
    expect(segments).toHaveLength(4);
    expect(segments.map((s) => s.bad)).toEqual([false, false, true, true]);
    expect(segments.map((s) => s.latest)).toEqual([false, false, false, true]);
    expect(trail(l, run, 0, "ops")).toEqual([]);
  });

  it("counts up to the current step only", () => {
    expect(totals(run, 2)).toEqual({ requests: 3, thoughts: 1, blocked: 0, violations: 0 });
    expect(totals(run, 5)).toEqual({ requests: 4, thoughts: 1, blocked: 1, violations: 1 });
  });

  it("replaces a step sent again, and adds a new one", () => {
    const changed = { ...run[1]!, kind: "violation" as const };
    expect(merge(run, changed)[1]!.kind).toBe("violation");
    expect(merge(run, changed)).toHaveLength(run.length);
    expect(merge(run, step(6, "info", "agent"))).toHaveLength(run.length + 1);
  });

  it("keeps one marker per agent, each at its own latest step", () => {
    const two = [...run.slice(0, 2), step(2, "request", "chat", "channel:incidents", 1, "helper")];
    expect(markers(two, 2, ["ops", "helper"]).map((m) => m.step?.index)).toEqual([1, 2]);
    expect(markers(two, 1, ["ops", "helper"]).map((m) => m.step?.index)).toEqual([1, undefined]);
  });
});
