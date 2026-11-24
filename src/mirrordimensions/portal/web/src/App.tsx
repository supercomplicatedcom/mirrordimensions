// SPDX-FileCopyrightText: 2026 Supercomplicated LLC
// SPDX-License-Identifier: Apache-2.0
import { useEffect } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Agents } from "./screens/Agents";
import { CompanyScreen } from "./screens/Company";
import { Environment } from "./screens/Environment";
import { HealthScreen } from "./screens/Health";
import { Permissions } from "./screens/Permissions";
import { RunDetail } from "./screens/RunDetail";
import { Runs } from "./screens/Runs";
import { Scenarios } from "./screens/Scenarios";

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

export function App() {
  return (
    <div className="shell">
      <a className="skip" href="#content">
        Skip to content
      </a>
      <Title />
      <nav className="sidebar" aria-label="Sections">
        <div className="brand">Mirror</div>
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
          <Route path="/agents" element={<Agents />} />
          <Route path="/permissions" element={<Permissions />} />
          <Route path="/permissions/:agent" element={<Permissions />} />
          <Route path="/company" element={<CompanyScreen />} />
          <Route path="/scenarios" element={<Scenarios />} />
          <Route path="/runs" element={<Runs />} />
          <Route path="/runs/:runId" element={<RunDetail />} />
          <Route path="/health" element={<HealthScreen />} />
          <Route path="*" element={<Navigate to="/environment" replace />} />
        </Routes>
      </main>
    </div>
  );
}
