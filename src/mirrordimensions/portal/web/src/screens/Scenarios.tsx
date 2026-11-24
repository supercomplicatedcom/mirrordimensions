// SPDX-FileCopyrightText: 2026 Supercomplicated LLC
// SPDX-License-Identifier: Apache-2.0
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PortalError, send, useApi } from "../api";
import type { AgentSummary, RunHandle, RunSummary, ScenarioSummary } from "../types";
import { ErrorBox, Loading, PageHead, RunStatus, capitalize } from "../ui";

export function Scenarios() {
  const scenarios = useApi<ScenarioSummary[]>("/scenarios");
  const agents = useApi<AgentSummary[]>("/agents");
  const runs = useApi<RunSummary[]>("/runs");
  const [kind, setKind] = useState("");
  const [agent, setAgent] = useState("");
  const [error, setError] = useState<PortalError>();
  const [starting, setStarting] = useState<string>();
  const navigate = useNavigate();

  const ready = (agents.data ?? []).filter((a) => a.state === "defined");
  useEffect(() => {
    if (!agent && ready[0]) setAgent(ready[0].name);
  }, [agent, ready]);

  const last = useMemo(() => {
    const found = new Map<string, RunSummary>();
    for (const r of runs.data ?? []) if (r.agent === agent && r.scenario && !found.has(r.scenario)) found.set(r.scenario, r);
    return found;
  }, [runs.data, agent]);

  const rows = (scenarios.data ?? []).filter((s) => !kind || s.kind === kind);
  const builtIn = (scenarios.data ?? []).filter((s) => s.source === "built-in").length;
  const own = (scenarios.data ?? []).length - builtIn;

  async function start(name: string) {
    setStarting(name);
    setError(undefined);
    try {
      const handle = await send<RunHandle>("POST", "/runs", { scenario: name, agent });
      navigate(`/runs/${handle.run_id}`);
    } catch (err) {
      if (err instanceof PortalError) setError(err);
    } finally {
      setStarting(undefined);
    }
  }

  return (
    <>
      <PageHead
        title="Scenarios"
        sub={`${builtIn} built in · ${own} of your own${agent ? ` · last results are for ${agent}` : ""}`}
      >
        <button type="button" className="primary" disabled={!agent || starting !== undefined} onClick={() => void start("core")}>
          {starting === "core" ? "Starting…" : "Run the core suite"}
        </button>
      </PageHead>
      <ErrorBox error={scenarios.error ?? error} />
      <div className="toolbar">
        <label className="field">
          Kind
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">All kinds</option>
            <option value="functional">Functional</option>
            <option value="injection">Injection</option>
            <option value="permission">Permission</option>
          </select>
        </label>
        <label className="field">
          Run as
          <select value={agent} onChange={(e) => setAgent(e.target.value)}>
            {ready.length === 0 && <option value="">No agent ready</option>}
            {ready.map((a) => (
              <option key={a.name} value={a.name}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <section className="card flush" aria-labelledby="jobs">
        <div className="card-head">
          <h2 id="jobs" style={{ margin: 0 }}>
            Jobs the agent can be given
          </h2>
        </div>
        {scenarios.loading && !scenarios.data ? (
          <div style={{ padding: 20 }}>
            <Loading what="scenarios" />
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Scenario</th>
                  <th scope="col">Kind</th>
                  <th scope="col">How the work arrives</th>
                  <th scope="col">Last result</th>
                  <th scope="col">Start</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => {
                  const r = last.get(s.id);
                  return (
                    <tr key={s.id}>
                      <th scope="row">
                        <span className="mono">{s.id}</span>
                        <div className="note">{s.title}</div>
                      </th>
                      <td>{capitalize(s.kind)}</td>
                      <td>{capitalize(s.delivery_words)}</td>
                      <td>{r ? <RunStatus status={r.status} coverage={r.coverage} /> : "Not run"}</td>
                      <td>
                        <button type="button" className="small" disabled={!agent || starting !== undefined} onClick={() => void start(s.id)}>
                          {starting === s.id ? "Starting…" : "Run"}
                          <span className="skip"> {s.id}</span>
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <p className="note">
        The built-in scenarios are public and exist to test the mirror itself. Write your own, and keep them private, for results you
        will rely on.
      </p>
    </>
  );
}
