// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { splitCommand } from "./screens/Onboard";

describe("the onboarding wizard", () => {
  it("splits a command as the command line's shlex would, for ordinary quoting", () => {
    expect(splitCommand("python /opt/agent.py")).toEqual(["python", "/opt/agent.py"]);
    expect(splitCommand(`node run.js --say "hello there" --x 'a b'`)).toEqual(["node", "run.js", "--say", "hello there", "--x", "a b"]);
    expect(splitCommand("   ")).toEqual([]);
  });
});
