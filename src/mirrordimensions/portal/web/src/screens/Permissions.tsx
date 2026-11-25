// SPDX-FileCopyrightText: 2026 Supercomplicated LLC
// SPDX-License-Identifier: Apache-2.0
// For one agent: what it is granted, set against what its last run used (the run's access
// map), and the grants themselves, edited here and saved to the agent's file. Grants are
// exact and take effect at the agent's next run.

import { useCallback, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { PortalError, send, useApi } from "../api";
import { PendingChanges } from "../pending";
import type { AccessRow, AgentSummary, GrantSystem, Reach } from "../types";
import { ErrorBox, Loading, PageHead, capitalize } from "../ui";

function used(r: AccessRow): string {
  if (r.how && r.how.length) return capitalize(r.how.join(", "));
  if ((r.requests ?? 0) || (r.refused ?? 0))
    return `${r.requests ?? 0} request(s)${r.refused ? `, ${r.refused} refused` : ""}`;
  return "Not used";
}

function finding(r: AccessRow, ran: boolean): [string, string] {
  const touched = Boolean((r.how && r.how.length) || r.requests || r.refused);
  if (touched && (r.granted === null || r.granted === false)) return ["Used without a grant", "bad"];
  if (touched) return ["Matches the job", "good"];
  if (!ran) return ["Not run yet", ""];
  if (r.granted) return ["Could be removed", ""];
  return ["Stayed out", ""];
}

export function Permissions() {
  const { agent } = useParams();
  const navigate = useNavigate();
  const agents = useApi<AgentSummary[]>("/agents");
  const chosen = agent ?? agents.data?.[0]?.name;
  const reach = useApi<Reach>(chosen ? `/agents/${encodeURIComponent(chosen)}/reach` : null);
  const grants = useApi<GrantSystem[]>(chosen ? `/agents/${encodeURIComponent(chosen)}/grants` : null);
  const [tick, setTick] = useState(0);
  const [error, setError] = useState<PortalError>();
  const [saved, setSaved] = useState<string>();
  const reloadGrants = grants.reload;
  const edited = useCallback(() => {
    setTick((t) => t + 1);
    reloadGrants();
  }, [reloadGrants]);
  const access = reach.data?.access;
  const sections: [string, string, AccessRow[]][] = [
    ["Tools", "tool", access?.tools ?? []],
    ["Hosts", "host", access?.hosts ?? []],
  ];
  const setGrant = (system: GrantSystem, name: string, grant: string) => {
    if (!chosen) return;
    setError(undefined);
    send<{ what: string }>("PATCH", `/agents/${encodeURIComponent(chosen)}/grants`, {
      resource: `${system.app_id}/${name}`,
      grant,
    })
      .then((c) => {
        setSaved(c.what);
        edited();
      })
      .catch((err: unknown) => err instanceof PortalError && setError(err));
  };
  const usedRow = (system: GrantSystem, name: string): AccessRow | undefined =>
    system.key === "repos"
      ? access?.repositories?.find((r) => String(r.repo ?? "").split("/").pop() === name)
      : system.key === "channels"
        ? access?.channels?.find((r) => r.channel === name)
        : access?.tools?.find((r) => r.tool === name);
  return (
    <>
      <PageHead eyebrow={<Link to="/agents">Agents</Link>} title={chosen ? `What ${chosen} can reach` : "Permissions"}>
        <label className="field">
          Agent
          <select value={chosen ?? ""} onChange={(e) => navigate(`/permissions/${e.target.value}`)}>
            {(agents.data ?? []).map((a) => (
              <option key={a.name} value={a.name}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
      </PageHead>
      <ErrorBox error={agents.error ?? reach.error ?? grants.error ?? error} />
      <PendingChanges tick={tick} onApplied={edited} />
      {saved && (
        <p role="status" className="note">
          Saved to the agent file: {saved}. It takes effect at the agent's next run.
        </p>
      )}
      {(agents.loading || reach.loading) && !reach.data && <Loading what="grants" />}
      {reach.data && (
        <p className="sub" style={{ marginTop: -8 }}>
          Acting as {reach.data.acts_as} ·{" "}
          {reach.data.run_id ? (
            <>
              set against its last run,{" "}
              <Link to={`/runs/${reach.data.run_id}`} className="mono">
                {reach.data.run_id}
              </Link>{" "}
              ({reach.data.scenario})
            </>
          ) : (
            "grants only: no run of it has kept an access map yet"
          )}
        </p>
      )}
      {(grants.data ?? [])
        .filter((g) => g.key && g.items.length > 0)
        .map((system) => (
          <section key={system.app_id} className="card flush" aria-labelledby={`grant-${system.app_id}`}>
            <div className="card-head">
              <h2 id={`grant-${system.app_id}`} style={{ margin: 0 }}>
                {system.label}: {system.key === "repos" ? "repositories" : system.key}
              </h2>
            </div>
            <table>
              <thead>
                <tr>
                  <th scope="col">Resource</th>
                  <th scope="col">Granted</th>
                  <th scope="col">{reach.data?.run_id ? "Used in last run" : "Used"}</th>
                  <th scope="col">Finding</th>
                </tr>
              </thead>
              <tbody>
                {system.items.map((item) => {
                  const row = usedRow(system, item.name);
                  const [word, tone] = row
                    ? finding({ ...row, granted: item.grant ?? false }, Boolean(reach.data?.run_id))
                    : item.grant
                      ? finding({ granted: item.grant } as AccessRow, Boolean(reach.data?.run_id))
                      : ["Stayed out", ""];
                  const options = system.levels.length > 1 ? system.levels : ["member"];
                  return (
                    <tr key={item.name}>
                      <th scope="row" className="mono">
                        {item.label}
                      </th>
                      <td>
                        <select
                          aria-label={`Grant on ${item.label}`}
                          value={item.grant ?? "none"}
                          onChange={(e) => setGrant(system, item.name, e.target.value)}
                        >
                          <option value="none">None</option>
                          {options.map((level) => (
                            <option key={level} value={level}>
                              {capitalize(level)}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>{row ? used(row) : "Not used"}</td>
                      <td>
                        <span className={`tag ${tone}`}>{word}</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>
        ))}
      {access &&
        sections
          .filter(([, , rows]) => rows.length > 0)
          .map(([title, key, rows]) => (
            <section key={title} className="card flush" aria-labelledby={`perm-${key}`}>
              <div className="card-head">
                <h2 id={`perm-${key}`} style={{ margin: 0 }}>
                  {title}
                </h2>
              </div>
              <table>
                <thead>
                  <tr>
                    <th scope="col">Resource</th>
                    <th scope="col">Granted</th>
                    <th scope="col">{reach.data?.run_id ? "Used in last run" : "Used"}</th>
                    <th scope="col">Finding</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const name = String(r[key as keyof AccessRow] ?? "");
                    const [word, tone] = finding(r, Boolean(reach.data?.run_id));
                    return (
                      <tr key={name}>
                        <th scope="row" className="mono">
                          {key === "channel" ? `#${name}` : name}
                        </th>
                        <td>{r.granted === null || r.granted === false ? "None" : r.granted === true ? "Granted" : capitalize(String(r.granted))}</td>
                        <td>{used(r)}</td>
                        <td>
                          <span className={`tag ${tone}`}>{word}</span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </section>
          ))}
      <p className="note">
        Grants live in the agent's file and are exact: for a run, the person it acts as has only these. The same edit from the command line:{" "}
        <code>mirror set grant {chosen ?? "<agent>"} code/billing-service write</code>.
      </p>
    </>
  );
}
