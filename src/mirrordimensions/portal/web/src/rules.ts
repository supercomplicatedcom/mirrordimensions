// SPDX-License-Identifier: Apache-2.0
// The System screen's rule form: the common customizations of one portal or endpoint
// (a body size limit, added delay, a share of requests failing, who it applies to), read
// from a rule and written back into one. Anything else a rule does is kept as it is.

import type { Rule } from "./types";

export interface RuleForm {
  name: string;
  maxBody: string; // bytes; empty for no limit
  onReject: string;
  delayLow: string; // ms; empty for none
  delayHigh: string;
  failPercent: string; // empty for none
  failError: string;
  agent: string; // empty for every identity
}

const str = (v: unknown) => (v === undefined || v === null ? "" : String(v));

export function formFromRule(surfaceId: string, rule: Rule | undefined): RuleForm {
  const input = (rule?.input ?? {}) as Record<string, unknown>;
  const output = (rule?.output ?? {}) as Record<string, unknown>;
  const delay = output.delay_ms;
  const fail = (output.fail ?? {}) as Record<string, unknown>;
  const [low, high] = Array.isArray(delay) ? delay : [delay, delay];
  return {
    name: rule?.name ?? surfaceId.replace(/[^a-z0-9-]+/g, "-"),
    maxBody: str(input.max_body_bytes),
    onReject: str(input.on_reject) || "too_large",
    delayLow: str(low),
    delayHigh: str(high),
    failPercent: fail.rate === undefined ? "" : String(Math.round(Number(fail.rate) * 1000) / 10),
    failError: str(fail.error) || "unavailable",
    agent: str((rule?.when as Record<string, unknown> | null | undefined)?.agent),
  };
}

/** The rule the form describes, keeping what the form does not show. Problems, if any. */
export function ruleFromForm(surfaceId: string, form: RuleForm, base?: Rule): [Rule | null, string[]] {
  const problems: string[] = [];
  const whole = (text: string, what: string, min = 0): number | undefined => {
    if (!text.trim()) return undefined;
    const n = Number(text);
    if (!Number.isInteger(n) || n < min) problems.push(`${what} must be a whole number of at least ${min}.`);
    return n;
  };
  if (!/^[a-z0-9][a-z0-9-]*$/.test(form.name)) problems.push("The name may use lowercase letters, digits and dashes.");
  const maxBody = whole(form.maxBody, "The largest body", 1);
  let low = whole(form.delayLow, "The shortest delay");
  let high = whole(form.delayHigh, "The longest delay");
  if (low === undefined && high !== undefined) low = high;
  if (high === undefined && low !== undefined) high = low;
  if (low !== undefined && high !== undefined && high < low) problems.push("The longest delay is shorter than the shortest.");
  let rate: number | undefined;
  if (form.failPercent.trim()) {
    rate = Number(form.failPercent) / 100;
    if (!(rate > 0 && rate <= 1)) problems.push("The share that fails is a percentage above 0 and up to 100.");
  }
  if (problems.length) return [null, problems];
  const input: Record<string, unknown> = { ...(base?.input ?? {}) };
  delete input.max_body_bytes;
  delete input.on_reject;
  if (maxBody !== undefined) Object.assign(input, { max_body_bytes: maxBody, on_reject: form.onReject });
  const output: Record<string, unknown> = { ...(base?.output ?? {}) };
  delete output.delay_ms;
  delete output.fail;
  if (low !== undefined && high !== undefined) output.delay_ms = low === high ? low : [low, high];
  if (rate !== undefined) output.fail = { rate, error: form.failError };
  const when: Record<string, unknown> = { ...(base?.when ?? {}) };
  delete when.agent;
  if (form.agent) when.agent = form.agent;
  const rule: Rule = { name: form.name, match: base?.match ?? { surface: surfaceId } };
  if (Object.keys(input).length) rule.input = input;
  if (Object.keys(output).length) rule.output = output;
  if (Object.keys(when).length) rule.when = when;
  if (!rule.input && !rule.output) return [null, ["Set at least one change: a body limit, a delay or a share that fails."]];
  return [rule, []];
}

function seconds(ms: number): string {
  return `${Math.round(ms / 100) / 10} s`;
}

/** What a rule does, in a few words, for the Behavior column. */
export function ruleWords(rule: Rule): string {
  const words: string[] = [];
  const input = (rule.input ?? {}) as Record<string, unknown>;
  const output = (rule.output ?? {}) as Record<string, unknown>;
  if (input.max_body_bytes !== undefined) {
    const n = Number(input.max_body_bytes);
    words.push(`rejects bodies over ${n >= 1048576 ? `${n / 1048576} MB` : n >= 1024 ? `${n / 1024} KB` : `${n} bytes`}`);
  }
  if (input.require_fields || input.forbid_fields || input.set_fields || input.rename_fields) words.push("changes what it accepts");
  const delay = output.delay_ms;
  if (Array.isArray(delay)) words.push(`slow, ${seconds(Number(delay[0]))} to ${seconds(Number(delay[1]))}`);
  else if (delay !== undefined) words.push(`slow, ${seconds(Number(delay))}`);
  const fail = output.fail as Record<string, unknown> | undefined;
  if (fail) {
    const rate = Number(fail.rate);
    words.push(rate >= 1 ? "always fails" : `fails ${Math.round(rate * 100)}% of the time`);
  }
  if (output.rate_limit) words.push("rate limited");
  if (output.respond) words.push("fixed answer");
  if (output.set_fields || output.remove_fields || output.insert_text) words.push("edits its answer");
  if (output.page_size) words.push(`pages of ${String(output.page_size)}`);
  const who = (rule.when as Record<string, unknown> | null | undefined)?.agent;
  return `${words.join(", ") || "customized"}${who ? ` (for ${String(who)} only)` : ""}`;
}
