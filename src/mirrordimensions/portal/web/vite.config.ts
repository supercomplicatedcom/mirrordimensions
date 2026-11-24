// SPDX-FileCopyrightText: 2026 Supercomplicated LLC
// SPDX-License-Identifier: Apache-2.0
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Built into ../static, which ships inside the Python package. Everything is bundled: the
// portal must work with no internet access (build spec, "Portal").
export default defineConfig({
  plugins: [react()],
  base: "/",
  build: {
    outDir: "../static",
    emptyOutDir: true,
    assetsInlineLimit: 0,
    sourcemap: false,
  },
  server: {
    // `npm run dev` against a running `mirror portal --port 7420 --no-open`.
    proxy: { "/api": "http://127.0.0.1:7420" },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.tsx", "src/**/*.test.ts"],
    setupFiles: ["src/test-setup.ts"],
  },
});
