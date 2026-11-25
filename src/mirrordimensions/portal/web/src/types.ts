// SPDX-FileCopyrightText: 2026 Supercomplicated LLC
// SPDX-License-Identifier: Apache-2.0
// The JSON the portal's API returns: the service layer's models (src/mirrordimensions/service).

export interface ProjectInfo {
  name: string | null;
  state: string;
  root: string;
  isolation: string | null;
  pending_changes: number;
}

export interface GraphNode {
  id: string;
  kind: "agent" | "gateway" | "system" | "model";
  label: string;
  detail: string;
  hostname: string | null;
  product: string | null;
  visibility: string | null;
  built_as: string | null;
  granted_to: string[];
  column: number;
  row: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  kind: "route" | "grant" | "exit";
  label: string;
}

export interface Graph {
  project: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface AgentSummary {
  name: string;
  mode: string;
  acts_as: string;
  state: string;
  image: string | null;
  systems: string[];
  last_run: string | null;
  last_scenario: string | null;
  last_status: string | null;
}

export interface PersonRow {
  id: string;
  name: string;
  username: string;
  email: string;
  title: string;
  department: string;
  team: string | null;
  manager: string | null;
  roles: string[];
  started_days_ago: number;
  left: boolean;
}

export interface Company {
  company: string;
  domain: string;
  industry: string;
  seed: number;
  people: PersonRow[];
  projects: { name: string; team: string; repositories: string[]; channel: string }[];
  canaries: { id: string; kind: string; where: string; value: string }[];
}

export interface ScenarioSummary {
  id: string;
  kind: "functional" | "injection" | "permission";
  title: string;
  source: "built-in" | "project";
  delivery: string;
  delivery_words: string;
  acts_as: string;
  systems: string[];
  suites: string[];
  mcp_tools: string[];
  max_minutes: number;
}

export interface RunSummary {
  run_id: string;
  scenario: string | null;
  agent: string | null;
  status: string;
  isolation: string | null;
  coverage: string;
  suspected: boolean;
  started: string | null;
  checks_passed: number;
  checks: number;
  live: boolean;
}

export interface RunEvent {
  seq: number;
  ts: string;
  source: string;
  type: string;
  data: Record<string, unknown>;
  summary: string;
  at: string;
}

export interface EventPage {
  run_id: string;
  total: number;
  offset: number;
  events: RunEvent[];
  start: string | null;
}

export interface Check {
  check: string;
  kind: "success" | "forbidden";
  args?: Record<string, unknown>;
  passed: boolean;
  evidence?: string;
  event?: number;
}

export interface AccessRow {
  host?: string;
  repo?: string;
  channel?: string;
  tool?: string;
  granted: string | boolean | null;
  how?: string[];
  requests?: number;
  refused?: number;
  first?: number | null;
}

export interface Result {
  run_id: string;
  status: "passed" | "failed" | "errored" | "stopped";
  isolation: string;
  scenario?: string;
  agent?: string;
  acts_as?: string;
  reason?: string;
  delivery?: Record<string, unknown>;
  checks: Check[];
  side_effects: { system: string; object: string; change: string }[];
  allowed_changes: number;
  canaries: { canary: string; seen: string[] }[];
  egress: { event: number; kind: string; to: string; proto: string }[];
  suspected: boolean;
  suspicion: { event: number; phrase: string }[];
  coverage: { status?: string; channels?: Record<string, { status: string; where?: string; reason?: string }> };
  access?: {
    hosts?: AccessRow[];
    repositories?: AccessRow[];
    channels?: AccessRow[];
    tools?: AccessRow[];
    outside_grants?: number;
  };
}

export interface RunHandle {
  run_id: string;
  scenario: string;
  agent: string;
}

export interface Health {
  project: string | null;
  state: string;
  engine: string;
  engine_detail: string;
  up: boolean;
  containers: { name: string; role: string; running: boolean }[];
  snapshots: { name: string; created: string; volumes: number }[];
  doctor: {
    isolation: string;
    boundary: string;
    checked_at?: string;
    checks: { suite: string; name: string; outcome: "pass" | "fail" | "n/a"; detail: string }[];
  } | null;
}

export interface ApiError {
  what: string;
  why: string;
  fix: string;
}

export interface Reach {
  agent: string;
  acts_as: string;
  run_id: string | null;
  scenario: string | null;
  access: NonNullable<Result["access"]>;
}
