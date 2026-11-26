// SPDX-FileCopyrightText: 2026 Supercomplicated LLC
// SPDX-License-Identifier: Apache-2.0
// The worlds on this machine beside the current one: switch the portal to another, or
// define a new one. Every world shares the one engine; only one world's sandbox runs.

import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { PortalError, send, useApi } from "../api";
import type { WorldEntry } from "../types";
import { ErrorBox, Loading, PageHead, capitalize } from "../ui";

export function Worlds() {
  const worlds = useApi<WorldEntry[]>("/worlds");
  const navigate = useNavigate();
  const [error, setError] = useState<PortalError>();
  return (
    <>
      <PageHead title="Worlds" sub="Worlds in the folder beside this one. The portal serves one at a time.">
        <div className="toolbar">
          <Link className="button" to="/worlds/import">
            Import into this world
          </Link>
          <Link className="button primary" to="/worlds/new">
            Define a new world
          </Link>
        </div>
      </PageHead>
      <ErrorBox error={worlds.error ?? error} />
      {!worlds.data && !worlds.error && <Loading what="worlds" />}
      {worlds.data && (
        <section className="card flush" aria-labelledby="worlds-title">
          <div className="card-head">
            <h2 id="worlds-title" style={{ margin: 0 }}>
              On this computer
            </h2>
          </div>
          <table>
            <thead>
              <tr>
                <th scope="col">World</th>
                <th scope="col">Company</th>
                <th scope="col">State</th>
                <th scope="col">Folder</th>
                <th scope="col">
                  <span className="skip">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {worlds.data.map((w) => (
                <tr key={w.folder} className={w.current ? "selected" : ""}>
                  <th scope="row">{w.name}</th>
                  <td>{w.company}</td>
                  <td>
                    <span className={`tag ${w.state === "ready" ? "good" : w.state === "failed" ? "bad" : ""}`}>{capitalize(w.state)}</span>
                  </td>
                  <td className="mono note">{w.folder}</td>
                  <td>
                    {w.current ? (
                      <span className="tag good">Served now</span>
                    ) : w.state === "draft" ? (
                      <Link to={`/worlds/new?folder=${encodeURIComponent(w.folder)}`}>Continue defining {w.name}</Link>
                    ) : (
                      <button
                        type="button"
                        className="small"
                        onClick={() => {
                          setError(undefined);
                          send("POST", "/worlds/switch", { folder: w.folder })
                            .then(() => navigate("/environment"))
                            .catch((err: unknown) => err instanceof PortalError && setError(err));
                        }}
                      >
                        Switch to {w.name}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      <p className="note">
        Switching changes which world every screen shows. It does not start or stop a sandbox: <code>mirror up</code> in that world, or a
        run, does.
      </p>
    </>
  );
}
