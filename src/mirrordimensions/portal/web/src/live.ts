// SPDX-License-Identifier: Apache-2.0
// The live view's logic, kept apart from drawing so it can be tested: where each place sits
// on the map, where a step puts the agent's marker, the trail behind it, and the totals.

import type { Place, Step } from "./types";

export const MAP_WIDTH = 760;
const HOME = { x: 24, y: 0, w: 176, h: 72 };
const SYSTEMS_X = 300;
const SYSTEM_W = 436;
const HEAD_H = 44;
const CHIP_H = 40;
const CHIP_W = 196;
const GAP = 20;
const BOTTOM_H = 64;

export interface Box {
  id: string;
  label: string;
  meta: string;
  kind: "agent" | "system" | "model" | "outside";
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Chip {
  id: string;
  label: string;
  granted: boolean;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Layout {
  height: number;
  boxes: Box[];
  chips: Chip[];
  spots: Record<string, [number, number]>;
}

export const spotKey = (system: string, place?: string | null) => (place ? `${system}|${place}` : system);

/** Places the steps reached that the map did not list yet (a resource outside the grants). */
export function withTouched(places: Place[], steps: Step[]): Place[] {
  const out = places.map((p) => ({ ...p, resources: [...p.resources] }));
  for (const s of steps) {
    const { system, place } = s.location;
    if (system === "agent") continue;
    let found = out.find((p) => p.system === system);
    if (!found) {
      const kind = system === "model" ? "model" : system === "outside" ? "outside" : "system";
      found = { system, label: s.location.label.split(", ")[0] ?? system, kind, resources: [] };
      out.push(found);
    }
    if (place && !found.resources.some((r) => r.place === place)) {
      const label = place.startsWith("channel:") ? `#${place.slice(8)}` : (place.split("/").pop() ?? place);
      found.resources.push({ place, label, granted: false });
    }
  }
  return out;
}

/** The map: the agent on the left, its systems on the right with their resources as chips,
 * and the model and the outside along the bottom. The model and the outside are always drawn,
 * so a blocked attempt has somewhere to point. */
export function layout(places: Place[], agent: string): Layout {
  const boxes: Box[] = [];
  const chips: Chip[] = [];
  const spots: Record<string, [number, number]> = {};
  let y = 0;
  for (const p of places.filter((x) => x.kind === "system")) {
    const rows = Math.ceil(p.resources.length / 2);
    const h = HEAD_H + rows * (CHIP_H + 8) + (rows ? 8 : 0);
    boxes.push({ id: p.system, label: p.label, meta: p.resources.length ? "" : "no resources named", kind: "system", x: SYSTEMS_X, y, w: SYSTEM_W, h });
    spots[spotKey(p.system)] = [SYSTEMS_X, y + HEAD_H / 2]; // on its left edge, clear of the name
    p.resources.forEach((r, i) => {
      const cx = SYSTEMS_X + 12 + (i % 2) * (CHIP_W + 20);
      const cy = y + HEAD_H + Math.floor(i / 2) * (CHIP_H + 8);
      chips.push({ id: spotKey(p.system, r.place), label: r.label, granted: r.granted, x: cx, y: cy, w: CHIP_W, h: CHIP_H });
      spots[spotKey(p.system, r.place)] = [cx + 20, cy + CHIP_H / 2];
    });
    y += h + GAP;
  }
  const systemsBottom = Math.max(y, HOME.h + GAP);
  const home = { ...HOME, y: Math.max(0, Math.round((systemsBottom - GAP - HOME.h) / 2)) };
  boxes.push({ id: "agent", label: agent, meta: "waiting for work · finished", kind: "agent", ...home });
  spots.agent = [home.x + home.w, home.y + home.h / 2];
  const by = systemsBottom + 16;
  boxes.push({ id: "model", label: "Model API", meta: "thinking", kind: "model", x: SYSTEMS_X, y: by, w: 208, h: BOTTOM_H });
  boxes.push({ id: "outside", label: "Outside the sandbox", meta: "blocked", kind: "outside", x: SYSTEMS_X + 228, y: by, w: 208, h: BOTTOM_H });
  spots.model = [SYSTEMS_X + 104, by];
  spots.outside = [SYSTEMS_X + 228 + 104, by];
  return { height: by + BOTTOM_H + 8, boxes, chips, spots };
}

export function spotOf(l: Layout, step: Step | undefined): [number, number] {
  if (!step) return l.spots.agent ?? [0, 0];
  const { system, place } = step.location;
  return l.spots[spotKey(system, place)] ?? l.spots[system] ?? l.spots.agent ?? [0, 0];
}

export const isBad = (s: Step | undefined) => s?.kind === "blocked" || s?.kind === "violation";

export interface Segment {
  from: [number, number];
  to: [number, number];
  bad: boolean;
  latest: boolean;
}

/** The path one agent took up to the current step; the latest segment is drawn strongest. */
export function trail(l: Layout, steps: Step[], upTo: number, agent: string): Segment[] {
  const mine = steps.filter((s) => s.index <= upTo && s.agent === agent);
  const out: Segment[] = [];
  for (let i = 1; i < mine.length; i++) {
    const a = spotOf(l, mine[i - 1]);
    const b = spotOf(l, mine[i]);
    if (a[0] === b[0] && a[1] === b[1]) continue;
    out.push({ from: a, to: b, bad: isBad(mine[i]), latest: false });
  }
  const last = out[out.length - 1];
  if (last && mine[mine.length - 1] && spotOf(l, mine[mine.length - 1]).join() === last.to.join()) last.latest = true;
  return out;
}

export interface Totals {
  requests: number;
  thoughts: number;
  blocked: number;
  violations: number;
}

export function totals(steps: Step[], upTo: number): Totals {
  const t: Totals = { requests: 0, thoughts: 0, blocked: 0, violations: 0 };
  for (const s of steps) {
    if (s.index > upTo) break;
    t.requests += s.kind === "blocked" ? 0 : s.requests;
    if (s.kind === "think") t.thoughts += 1;
    if (s.kind === "blocked") t.blocked += s.events.length;
    if (s.kind === "violation") t.violations += 1;
  }
  return t;
}

/** A streamed step: new ones are added, a changed one (same index) replaces the old. */
export function merge(steps: Step[], step: Step): Step[] {
  if (step.index < steps.length) {
    const next = steps.slice();
    next[step.index] = step;
    return next;
  }
  return [...steps, step];
}

/** Where each agent is at the current step: its latest step at or before it. */
export function markers(steps: Step[], upTo: number, agents: string[]): { agent: string; step: Step | undefined }[] {
  return agents.map((agent) => {
    let found: Step | undefined;
    for (const s of steps) {
      if (s.index > upTo) break;
      if (s.agent === agent) found = s;
    }
    return { agent, step: found };
  });
}

export const KIND_WORDS: Record<string, string> = {
  request: "",
  think: "thinking",
  blocked: "blocked",
  violation: "rule broken",
  info: "",
  end: "",
};
