// SPDX-FileCopyrightText: 2026 Supercomplicated LLC
// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { checkEvent } from "./screens/RunDetail";
import { layout } from "./screens/Environment";
import type { Graph } from "./types";

const graph: Graph = {
  project: "p",
  nodes: [
    { id: "agent:a", kind: "agent", label: "a", detail: "", hostname: null, product: null, visibility: null, built_as: null, granted_to: [], column: 0, row: 0 },
    { id: "gateway", kind: "gateway", label: "Gateway", detail: "", hostname: null, product: null, visibility: null, built_as: null, granted_to: [], column: 1, row: 0 },
    { id: "system:code", kind: "system", label: "Code", detail: "", hostname: "git.x.com", product: "gitea", visibility: "granted", built_as: "real software", granted_to: ["a"], column: 2, row: 0 },
    { id: "system:chat", kind: "system", label: "Chat", detail: "", hostname: "chat.x.com", product: "mattermost", visibility: "absent", built_as: "real software", granted_to: [], column: 2, row: 1 },
  ],
  edges: [],
};

describe("the environment map's layout", () => {
  it("is computed left to right and is the same every time", () => {
    const first = layout(graph);
    expect(layout(graph)).toEqual(first);
    const x = Object.fromEntries(first.placed.map((n) => [n.id, n.x]));
    expect(x["agent:a"]).toBeLessThan(x["gateway"]!);
    expect(x["gateway"]).toBeLessThan(x["system:code"]!);
    const code = first.placed.find((n) => n.id === "system:code")!;
    const chat = first.placed.find((n) => n.id === "system:chat")!;
    expect(chat.y).toBeGreaterThan(code.y);
    // The one agent is centred against the two systems.
    const agent = first.placed.find((n) => n.id === "agent:a")!;
    expect(agent.y).toBeCloseTo((code.y + chat.y) / 2);
  });
});

describe("a check's event", () => {
  it("comes from the check, or from the event its evidence names", () => {
    expect(checkEvent({ check: "c", kind: "forbidden", passed: false, event: 96 })).toBe(96);
    expect(checkEvent({ check: "c", kind: "forbidden", passed: false, evidence: "event 52: GET /x (200)" })).toBe(52);
    expect(checkEvent({ check: "c", kind: "success", passed: true, evidence: "fine" })).toBeUndefined();
  });
});
