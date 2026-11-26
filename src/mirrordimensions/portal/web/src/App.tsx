// SPDX-FileCopyrightText: 2026 Supercomplicated LLC
// SPDX-License-Identifier: Apache-2.0
import { useEffect } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useApi } from "./api";
import { Agents } from "./screens/Agents";
import { CompanyScreen } from "./screens/Company";
import { Environment } from "./screens/Environment";
import { HealthScreen } from "./screens/Health";
import { Live } from "./screens/Live";
import { Onboard } from "./screens/Onboard";
import { Permissions } from "./screens/Permissions";
import { RunDetail } from "./screens/RunDetail";
import { Runs } from "./screens/Runs";
import { Scenarios } from "./screens/Scenarios";
import { SystemScreen } from "./screens/System";
import { WorldImport } from "./screens/WorldImport";
import { WorldWizard } from "./screens/WorldWizard";
import { Worlds } from "./screens/Worlds";

export const SECTIONS: [string, string][] = [
  ["/environment", "Environment"],
  ["/agents", "Agents"],
  ["/permissions", "Permissions"],
  ["/company", "Company"],
  ["/scenarios", "Scenarios"],
  ["/runs", "Runs"],
  ["/health", "Health"],
];

function Title() {
  const { pathname } = useLocation();
  useEffect(() => {
    const section = SECTIONS.find(([path]) => pathname.startsWith(path));
    document.title = section ? `${section[1]} · Mirror` : "Mirror";
  }, [pathname]);
  return null;
}

function CurrentWorld() {
  const { pathname } = useLocation();
  const project = useApi<{ name: string | null; root: string }>(`/project?at=${pathname.startsWith("/worlds") ? pathname : ""}`);
  return (
    <div className="world">
      <span>
        World: <b>{project.data?.name ?? "…"}</b>
      </span>
      <Link to="/worlds">Switch or define a world</Link>
    </div>
  );
}

export function App() {
  return (
    <div className="shell">
      <a className="skip" href="#content">
        Skip to content
      </a>
      <Title />
      <nav className="sidebar" aria-label="Sections">
        <div className="brand">Mirror</div>
        <CurrentWorld />
        {SECTIONS.map(([path, label]) => (
          <NavLink key={path} to={path}>
            {label}
          </NavLink>
        ))}
      </nav>
      <main id="content" tabIndex={-1}>
        <Routes>
          <Route path="/" element={<Navigate to="/environment" replace />} />
          <Route path="/environment" element={<Environment />} />
          <Route path="/environment/systems/:appId" element={<SystemScreen />} />
          <Route path="/agents" element={<Agents />} />
          <Route path="/agents/new" element={<Onboard />} />
          <Route path="/agents/new/:name" element={<Onboard key="resume" />} />
          <Route path="/worlds" element={<Worlds />} />
          <Route path="/worlds/new" element={<WorldWizard />} />
          <Route path="/worlds/import" element={<WorldImport />} />
          <Route path="/permissions" element={<Permissions />} />
          <Route path="/permissions/:agent" element={<Permissions />} />
          <Route path="/company" element={<CompanyScreen />} />
          <Route path="/scenarios" element={<Scenarios />} />
          <Route path="/runs" element={<Runs />} />
          <Route path="/runs/:runId" element={<RunDetail />} />
          <Route path="/runs/:runId/live" element={<Live />} />
          <Route path="/health" element={<HealthScreen />} />
          <Route path="*" element={<Navigate to="/environment" replace />} />
        </Routes>
      </main>
    </div>
  );
}
