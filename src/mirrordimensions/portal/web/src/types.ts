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
  kind: "agent" | "gateway" | "system" | "model" | "device";
  label: string;
  detail: string;
  hostname: string | null;
  product: string | null;
  visibility: string | null;
  built_as: string | null;
  granted_to: string[];
  location: string | null;
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

/** One disruptive or safety-critical device command the agent tried (decision 0026). */
export interface Physical {
  device: string;
  where: string;
  command: string;
  consequence: string;
  status: string;
  causes: string;
  called_for: boolean;
  why: string;
  asked_first: boolean;
  event?: number;
  asked_at?: number;
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
  physical?: Physical[];
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
    coverage?: string;
    undetectability?: string;
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

export type StepKind = "request" | "think" | "blocked" | "violation" | "info" | "end";

export interface Step {
  index: number;
  start: string;
  end: string;
  at: string;
  agent: string;
  location: { system: string; resource: string | null; place: string | null; label: string };
  kind: StepKind;
  sentence: string;
  detail: string;
  events: number[];
  requests: number;
}

export interface Place {
  system: string;
  label: string;
  kind: "system" | "model" | "outside";
  resources: { place: string; label: string; granted: boolean }[];
}

export interface StepsView {
  run_id: string;
  live: boolean;
  agents: string[];
  places: Place[];
  steps: Step[];
}

export interface Change {
  kind: "company" | "data" | "system" | "visibility" | "rule" | "grant";
  target: string;
  what: string;
  before: unknown;
  after: unknown;
  applies: "next run" | "restart" | "rebuild";
}

export interface ApplyResult {
  rebuilt: boolean;
  applied: Change[];
  waiting: Change[];
}

export interface BuildJob {
  running: boolean;
  steps: string[];
  result: ApplyResult | null;
  error: ApiError | null;
}

export interface GrantSystem {
  app_id: string;
  label: string;
  key: string | null;
  levels: string[];
  granted: boolean;
  items: { name: string; label: string; grant: string | null }[];
}

export interface SystemSummary {
  id: string;
  kind: string | null;
  product: string | null;
  hostname: string;
  visibility: string;
  surfaces: number;
  rules: number;
  twin: boolean;
}

export interface Surface {
  id: string;
  kind: string;
  method: string;
  path: string;
  resource: string | null;
  access: string | null;
  sentence: string;
  customized_by: string[];
  takes: string;
  gives: string;
}

export interface Rule {
  name: string;
  match: Record<string, unknown>;
  input?: Record<string, unknown> | null;
  output?: Record<string, unknown> | null;
  when?: Record<string, unknown> | null;
}

export interface SystemDetail {
  summary: SystemSummary;
  settings: Record<string, unknown>;
  data: Record<string, unknown>;
  surfaces: Surface[];
  rules: Rule[];
  errors: string[];
}

export interface TryResult {
  surface: string;
  resource: string | null;
  sentence: string;
  rules_fired: { rule: string; changed: string[] }[];
  status: number;
  headers: string[][];
  body: string;
  from_rule: boolean;
}

export interface WorldEntry {
  folder: string;
  name: string;
  company: string;
  state: string;
  current: boolean;
}

export interface WorldDraft {
  seed: number;
  attempt: number;
  company: { name: string; domain: string; industry: string } | null;
  template: string | null;
  systems: string[] | null;
  people: number | null;
  history: number | null;
  tidiness: "tidy" | "realistic" | "messy";
  links: Record<string, boolean>;
  data: Record<string, number>;
  step: number;
  imported: boolean;
}

export interface WorldDraftView {
  folder: string;
  step: number;
  draft: WorldDraft;
  company: { name: string; domain: string; industry: string };
  systems: { id: string; kind: string; product: string | null; hostname: string; note: string }[];
  yaml: string;
  templates: { name: string; description: string }[];
  command: string;
  imported: ImportReview | null;
  proposal: { profile: string; industry: string; systems: string[]; lines: string[] } | null;
}

// World import (decision 0025): the review of what files on this machine described.

export interface ImportSource {
  importer: string;
  label: string;
  file: string;
  path: string;
  summary: string;
  skipped_secrets: number;
  skipped_people: number;
  skipped: Record<string, number>;
}

export interface ImportConflict {
  id: string;
  subject: string;
  label: string;
  field: string;
  choices: { value: string; sources: string[] }[];
  settled: string | null;
}

export interface ImportFinding {
  id: string;
  label: string;
  kind: string;
  kind_label: string;
  product: string | null;
  twin: string | null;
  hostname: string | null;
  endpoint: string | null;
  sources: string[];
  understood: string;
  options: string[];
  decision: string;
  proposed: boolean;
  facts: string[];
  tools: {
    name: string;
    mapped: boolean;
    backed_by: string | null;
    reason: string;
  }[];
  endpoints: number;
}

export interface ImportReview {
  sources: ImportSource[];
  findings: ImportFinding[];
  conflicts: ImportConflict[];
  gaps: { what: string; why: string }[];
  found: number;
  buildable: number;
  open_conflicts: number;
  skipped_secrets: number;
  skipped_people: number;
  words: Record<string, string>;
}

export interface ImportApplied {
  changes: Change[];
  wizard: boolean;
}

export interface AgentDraft {
  name: string;
  step: number;
  fields: Record<string, unknown>;
  path: string;
}

export interface PreflightCheck {
  name: string;
  outcome: "pass" | "fail" | "n/a";
  detail: string;
  fix: string;
}

export interface RoleDefaults {
  role: string;
  person: { username: string; name: string; title: string };
  grants: Record<string, { repos?: Record<string, string>; channels?: string[]; tools?: string[] }>;
  lines: string[];
  options: { app_id: string; label: string; key: string; levels: string[]; names: string[] }[];
}
