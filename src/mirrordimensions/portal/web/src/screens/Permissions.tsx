// SPDX-FileCopyrightText: 2026 Supercomplicated LLC
// SPDX-License-Identifier: Apache-2.0
// For one agent: what it was granted, set against what its last run used (the run's access
// map). Editing grants arrives with the next part of M7; until then this screen reads only.

import { Link, useNavigate, useParams } from "react-router-dom";
import { useApi } from "../api";
import type { AccessRow, AgentSummary, Reach } from "../types";
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
  const access = reach.data?.access;
  const sections: [string, string, AccessRow[]][] = [
    ["Repositories", "repo", access?.repositories ?? []],
    ["Channels", "channel", access?.channels ?? []],
    ["Tools", "tool", access?.tools ?? []],
    ["Hosts", "host", access?.hosts ?? []],
  ];
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
      <ErrorBox error={agents.error ?? reach.error} />
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
        Grants live in the agent's file. Change them there, or with <code>mirror agent add</code> after editing; the portal's grant editor
        comes in the next part of this milestone.
      </p>
    </>
  );
}
