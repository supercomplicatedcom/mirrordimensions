// SPDX-License-Identifier: Apache-2.0
import { useMemo, useState } from "react";
import { useApi } from "../api";
import type { Company } from "../types";
import { ErrorBox, Loading, PageHead } from "../ui";

type Tab = "people" | "projects" | "canaries";

const CANARY_WORDS: Record<string, string> = { token: "Token", password: "Password", record: "Record" };

export function CompanyScreen() {
  const world = useApi<Company>("/world");
  const [tab, setTab] = useState<Tab>("people");
  const [query, setQuery] = useState("");
  const [showLeft, setShowLeft] = useState(true);
  const c = world.data;
  const q = query.trim().toLowerCase();
  const people = useMemo(
    () =>
      (c?.people ?? []).filter(
        (p) =>
          (showLeft || !p.left) &&
          (!q || [p.name, p.username, p.title, p.department, p.team ?? "", p.roles.join(" ")].join(" ").toLowerCase().includes(q)),
      ),
    [c, q, showLeft],
  );
  const names = useMemo(() => new Map((c?.people ?? []).map((p) => [p.id, p.name])), [c]);
  return (
    <>
      <PageHead
        title="Company"
        sub={
          c
            ? `${c.company} · ${c.people.length} people · ${c.projects.length} projects · ${c.industry} · seed ${c.seed}`
            : undefined
        }
      />
      <ErrorBox error={world.error} />
      {world.loading && !c && <Loading what="the company" />}
      {c && (
        <>
          <div className="toolbar" role="group" aria-label="Parts of the company">
            {(
              [
                ["people", "People"],
                ["projects", "Projects"],
                ["canaries", "Planted secrets"],
              ] as [Tab, string][]
            ).map(([key, label]) => (
              <button key={key} type="button" aria-pressed={tab === key} onClick={() => setTab(key)}>
                {label}
              </button>
            ))}
          </div>
          {tab === "people" && (
            <section className="card flush" aria-labelledby="people-h">
              <div className="card-head">
                <h2 id="people-h" style={{ margin: 0 }}>
                  People
                </h2>
                <span style={{ flex: 1 }} />
                <label className="field">
                  Search
                  <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Name, title, team or role" />
                </label>
                <label style={{ display: "inline-flex", gap: 8, alignItems: "center", minHeight: 44 }}>
                  <input type="checkbox" checked={showLeft} onChange={(e) => setShowLeft(e.target.checked)} />
                  Include people who left
                </label>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Name</th>
                      <th scope="col">Title</th>
                      <th scope="col">Team</th>
                      <th scope="col">Reports to</th>
                      <th scope="col">Role tags</th>
                      <th scope="col">Username</th>
                    </tr>
                  </thead>
                  <tbody>
                    {people.map((p) => (
                      <tr key={p.id}>
                        <th scope="row">
                          {p.name}
                          {p.left && <div className="note">Left; accounts disabled</div>}
                        </th>
                        <td>{p.title}</td>
                        <td>{p.team ?? p.department}</td>
                        <td>{p.manager ? (names.get(p.manager) ?? p.manager) : "Nobody"}</td>
                        <td>{p.roles.join(", ")}</td>
                        <td className="mono">{p.username}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="note" style={{ padding: "12px 20px" }}>
                Showing {people.length} of {c.people.length}. Everyone here is invented; the same people appear in every system.
              </p>
            </section>
          )}
          {tab === "projects" && (
            <section className="card flush" aria-labelledby="projects-h">
              <div className="card-head">
                <h2 id="projects-h" style={{ margin: 0 }}>
                  Projects
                </h2>
              </div>
              <table>
                <thead>
                  <tr>
                    <th scope="col">Project</th>
                    <th scope="col">Team</th>
                    <th scope="col">Repositories</th>
                    <th scope="col">Channel</th>
                  </tr>
                </thead>
                <tbody>
                  {c.projects.map((p) => (
                    <tr key={p.name}>
                      <th scope="row">{p.name}</th>
                      <td>{p.team}</td>
                      <td className="mono">{p.repositories.join(", ")}</td>
                      <td className="mono">#{p.channel}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}
          {tab === "canaries" && (
            <section className="card flush" aria-labelledby="canaries-h">
              <div className="card-head">
                <h2 id="canaries-h" style={{ margin: 0 }}>
                  Planted secrets
                </h2>
              </div>
              <table>
                <thead>
                  <tr>
                    <th scope="col">Secret</th>
                    <th scope="col">Kind</th>
                    <th scope="col">Where it was planted</th>
                  </tr>
                </thead>
                <tbody>
                  {c.canaries.map((k) => (
                    <tr key={k.id}>
                      <th scope="row" className="mono">
                        {k.id}
                      </th>
                      <td>{CANARY_WORDS[k.kind] ?? k.kind}</td>
                      <td>{k.where}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="note" style={{ padding: "12px 20px" }}>
                If one of these shows up anywhere it should not, the run reports where it travelled. Scenarios plant their own as well.
              </p>
            </section>
          )}
        </>
      )}
    </>
  );
}
