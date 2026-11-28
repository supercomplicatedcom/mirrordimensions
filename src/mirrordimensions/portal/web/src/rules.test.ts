// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { formFromRule, ruleFromForm, ruleWords } from "./rules";
import { examplePath } from "./screens/System";
import type { Rule } from "./types";

describe("the rule form", () => {
  it("starts empty for an endpoint with no rule, named after it", () => {
    const form = formFromRule("file.write", undefined);
    expect(form.name).toBe("file-write");
    expect([form.maxBody, form.delayLow, form.failPercent, form.agent]).toEqual(["", "", "", ""]);
    expect(ruleFromForm("file.write", form)[1]).toEqual(["Set at least one change: a body limit, a delay or a share that fails."]);
  });

  it("writes the rule the design shows: a body limit, a delay range, a failure rate, one agent", () => {
    const form = { ...formFromRule("file.write", undefined), maxBody: "1048576", delayLow: "800", delayHigh: "2500", failPercent: "10", agent: "ops" };
    const [rule, problems] = ruleFromForm("file.write", form);
    expect(problems).toEqual([]);
    expect(rule).toEqual({
      name: "file-write",
      match: { surface: "file.write" },
      input: { max_body_bytes: 1048576, on_reject: "too_large" },
      output: { delay_ms: [800, 2500], fail: { rate: 0.1, error: "unavailable" } },
      when: { agent: "ops" },
    });
    expect(ruleWords(rule!)).toBe("rejects bodies over 1 MB, slow, 0.8 s to 2.5 s, fails 10% of the time (for ops only)");
  });

  it("reads a rule back into the form and keeps what the form does not show", () => {
    const rule: Rule = {
      name: "slow",
      match: { surface: "repo.search" },
      output: { delay_ms: 500, remove_fields: ["email"] },
    };
    const form = formFromRule("repo.search", rule);
    expect([form.delayLow, form.delayHigh]).toEqual(["500", "500"]);
    const [again] = ruleFromForm("repo.search", { ...form, delayLow: "", delayHigh: "" }, rule);
    expect(again).toEqual({ name: "slow", match: { surface: "repo.search" }, output: { remove_fields: ["email"] } });
  });

  it("says what is wrong instead of saving a bad rule", () => {
    const form = { ...formFromRule("x", undefined), name: "Bad Name", delayLow: "900", delayHigh: "100", failPercent: "150" };
    expect(ruleFromForm("x", form)[1]).toEqual([
      "The name may use lowercase letters, digits and dashes.",
      "The longest delay is shorter than the shortest.",
      "The share that fails is a percentage above 0 and up to 100.",
    ]);
  });

  it("fills a path pattern so it can be tried", () => {
    expect(examplePath("/api/v1/repos/{owner}/{repo}/contents/{path+}")).toBe("/api/v1/repos/owner/repo/contents/path");
  });
});
