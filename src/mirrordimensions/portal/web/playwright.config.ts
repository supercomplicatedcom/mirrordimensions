// SPDX-License-Identifier: Apache-2.0
import { defineConfig } from "@playwright/test";

// One browser test per screen, against a project with a generated world and recorded runs
// (tests/portal_fixture.py), served by the real portal with the built front end.
const PORT = 7499;
const REPO = "../../../..";

export default defineConfig({
  testDir: "tests",
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: "retain-on-failure" },
  webServer: {
    command: `node -e "require('fs').rmSync('test-results/fixture',{recursive:true,force:true})" && uv run --project ${REPO} python ${REPO}/tests/portal_fixture.py test-results/fixture --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/v1/project`,
    // The API refuses without the token (401): any answer means the server is up.
    ignoreHTTPSErrors: true,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
