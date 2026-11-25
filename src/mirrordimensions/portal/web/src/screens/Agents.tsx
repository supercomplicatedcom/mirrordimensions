// SPDX-FileCopyrightText: 2026 Supercomplicated LLC
// SPDX-License-Identifier: Apache-2.0
import { useState } from "react";
import { Link } from "react-router-dom";
import { PortalError, send, useApi } from "../api";
import type { AgentSummary } from "../types";
import { ErrorBox, Loading, PageHead, RunStatus, capitalize } from "../ui";

const MODE_WORDS: Record<string, string> = {
  hosted: "Hosted container",
  browser: "Managed browser",
  remote: "Remote gateway",
};

export function Agents() {
  const agents = useApi<AgentSummary[]>("/agents");
  const [path, setPath] = useState("");
  const [error, setError] = useState<PortalError>();
  const [busy, setBusy] = useState(false);
  const rows = agents.data ?? [];
  const ready = rows.filter((a) => a.state === "defined").length;

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(undefined);
    try {
      await fn();
      agents.reload();
    } catch (err) {
      if (err instanceof PortalError) setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHead title="Agents" sub={`${rows.length} registered · ${ready} ready to run`} />
      <ErrorBox error={agents.error ?? error} />
      <section className="card flush" aria-labelledby="registered">
        <div className="card-head">
          <h2 id="registered" style={{ margin: 0 }}>
            Registered agents
          </h2>
        </div>
        {agents.loading && !agents.data ? (
          <div style={{ padding: 20 }}>
            <Loading what="agents" />
          </div>
        ) : rows.length === 0 ? (
          <p style={{ padding: 20 }} className="muted">
            No agents yet. Add one from its file below, or run <code>mirror agent new</code>.
          </p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Agent</th>
                  <th scope="col">Connects as</th>
                  <th scope="col">Acts as</th>
                  <th scope="col">Systems</th>
                  <th scope="col">Last run</th>
                  <th scope="col">Status</th>
                  <th scope="col">
                    <span className="skip">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => (
                  <tr key={a.name}>
                    <th scope="row">
                      <Link to={`/permissions/${a.name}`}>{a.name}</Link>
                      {a.image && <div className="note mono">{a.image}</div>}
                    </th>
                    <td>{MODE_WORDS[a.mode] ?? capitalize(a.mode)}</td>
                    <td>{capitalize(a.acts_as)}</td>
                    <td>{a.systems.join(", ") || "None"}</td>
                    <td>
                      {a.last_run ? (
                        <Link to={`/runs/${a.last_run}`} aria-label={`${a.last_status} run ${a.last_run} of ${a.last_scenario}`}>
                          <RunStatus status={a.last_status ?? ""} />
                        </Link>
                      ) : (
                        "Not run yet"
                      )}
                    </td>
                    <td>{a.state === "defined" ? "Ready" : `Finish setup: ${a.state.replace("draft, ", "")}`}</td>
                    <td>
                      <button
                        type="button"
                        className="small"
                        disabled={busy}
                        onClick={() => {
                          if (window.confirm(`Remove ${a.name} from this project? Its file is deleted; past runs are kept.`))
                            void act(() => send("DELETE", `/agents/${encodeURIComponent(a.name)}`));
                        }}
                      >
                        Remove<span className="skip"> {a.name}</span>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section className="card" aria-labelledby="add">
        <h2 id="add">Add an agent from its file</h2>
        <form
          className="toolbar"
          onSubmit={(e) => {
            e.preventDefault();
            if (path.trim()) void act(() => send("POST", "/agents", { path: path.trim() })).then(() => setPath(""));
          }}
        >
          <label className="field" style={{ flex: "1 1 420px" }}>
            Path to the agent file on this computer
            <input type="text" value={path} onChange={(e) => setPath(e.target.value)} placeholder="~/agents/ops-assistant/agent.yaml" />
          </label>
          <button type="submit" className="primary" disabled={busy || !path.trim()}>
            Add agent
          </button>
        </form>
        <p className="note" style={{ marginTop: 8 }}>
          The same as <code>mirror agent add &lt;file&gt;</code>: the file is checked against the world and copied into the project.
        </p>
      </section>
      <section className="card" aria-labelledby="ways">
        <h2 id="ways">Ways an agent can enter</h2>
        <dl className="facts">
          <dt>Hosted container</dt>
          <dd>The agent's own image runs inside the sandbox. Strongest containment and the fullest record.</dd>
          <dt>Managed browser</dt>
          <dd>The mirror provides the browser; the agent drives it. For agents that work through web pages.</dd>
        </dl>
      </section>
    </>
  );
}
