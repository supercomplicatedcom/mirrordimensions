// SPDX-FileCopyrightText: 2026 Supercomplicated LLC
// SPDX-License-Identifier: Apache-2.0
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../api";
import type { RunSummary } from "../types";
import { ErrorBox, Loading, PageHead, RunStatus, coverageWords } from "../ui";

type ResultFilter = "" | "failed" | "passed" | "incomplete" | "suspected";

export function Runs() {
  const runs = useApi<RunSummary[]>("/runs");
  const [agent, setAgent] = useState("");
  const [result, setResult] = useState<ResultFilter>("");
  const all = runs.data ?? [];
  const live = all.some((r) => r.live);
  // While a run is in progress, keep the list current.
  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(runs.reload, 3000);
    return () => window.clearInterval(timer);
  }, [live, runs.reload]);

  const shown = all.filter(
    (r) =>
      (!agent || r.agent === agent) &&
      (result === "" ||
        (result === "failed" && r.status !== "passed" && !r.live) ||
        (result === "passed" && r.status === "passed" && r.coverage !== "incomplete") ||
        (result === "incomplete" && r.coverage === "incomplete") ||
        (result === "suspected" && r.suspected)),
  );
  const agents = [...new Set(all.map((r) => r.agent).filter((a): a is string => Boolean(a)))].sort();
  const passed = shown.filter((r) => r.status === "passed" && r.coverage !== "incomplete").length;
  return (
    <>
      <PageHead title="Runs" sub="Newest first.">
        <Link className="button primary" to="/scenarios">
          Start a run
        </Link>
      </PageHead>
      <ErrorBox error={runs.error} />
      <div className="stats" aria-label="Totals">
        <div className="stat">
          <b>{shown.length}</b>runs in this view
        </div>
        <div className="stat">
          <b>{passed}</b>passed
        </div>
        <div className="stat">
          <b>{shown.filter((r) => !r.live).length - passed}</b>failed or not usable
        </div>
        <div className="stat">
          <b>{shown.filter((r) => r.suspected).length}</b>suspected a test
        </div>
      </div>
      <div className="toolbar">
        <label className="field">
          Agent
          <select value={agent} onChange={(e) => setAgent(e.target.value)}>
            <option value="">All agents</option>
            {agents.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Result
          <select value={result} onChange={(e) => setResult(e.target.value as ResultFilter)}>
            <option value="">Any result</option>
            <option value="failed">Failed</option>
            <option value="passed">Passed</option>
            <option value="incomplete">Coverage incomplete</option>
            <option value="suspected">Suspected a test</option>
          </select>
        </label>
      </div>
      <section className="card flush" aria-labelledby="all-runs">
        <div className="card-head">
          <h2 id="all-runs" style={{ margin: 0 }}>
            All runs
          </h2>
        </div>
        {runs.loading && !runs.data ? (
          <div style={{ padding: 20 }}>
            <Loading what="runs" />
          </div>
        ) : shown.length === 0 ? (
          <p className="muted" style={{ padding: 20 }}>
            No runs here yet. Start one from Scenarios.
          </p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Run</th>
                  <th scope="col">Scenario</th>
                  <th scope="col">Agent</th>
                  <th scope="col">Result</th>
                  <th scope="col">Checks</th>
                  <th scope="col">Coverage</th>
                  <th scope="col">Suspected a test</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.run_id}>
                    <th scope="row">
                      <Link className="mono" to={`/runs/${r.run_id}`}>
                        {r.run_id}
                      </Link>
                      {r.started && <div className="note">{r.started.replace("T", " ").slice(0, 19)} UTC</div>}
                    </th>
                    <td className="mono">{r.scenario}</td>
                    <td>{r.agent}</td>
                    <td>
                      <RunStatus status={r.status} coverage={r.coverage} />
                    </td>
                    <td>{r.live ? "Running" : `${r.checks_passed} of ${r.checks} passed`}</td>
                    <td>{coverageWords(r.coverage)}</td>
                    <td>{r.suspected ? "Yes: flagged" : r.live ? "Not yet" : "No"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <p className="note">A run with incomplete coverage cannot be used as evidence, whatever its checks say.</p>
    </>
  );
}
