// SPDX-FileCopyrightText: 2026 Supercomplicated LLC
// SPDX-License-Identifier: Apache-2.0
import { useState } from "react";
import { PortalError, send, useApi } from "../api";
import type { Health } from "../types";
import { ErrorBox, Loading, PageHead, capitalize } from "../ui";

function age(iso: string | undefined): string {
  if (!iso) return "never";
  const minutes = Math.round((Date.now() - Date.parse(iso)) / 60000);
  if (Number.isNaN(minutes)) return iso;
  if (minutes < 2) return "just now";
  if (minutes < 90) return `${minutes} minutes ago`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours} hours ago` : `${Math.round(hours / 24)} days ago`;
}

const OUTCOME: Record<string, [string, string]> = {
  pass: ["OK", "pass"],
  fail: ["FAIL", "fail"],
  "n/a": ["N/A", ""],
};

export function HealthScreen() {
  const health = useApi<Health>("/health");
  const [busy, setBusy] = useState<"doctor" | string>();
  const [error, setError] = useState<PortalError>();
  const [done, setDone] = useState<string>();
  const h = health.data;
  const doctor = h?.doctor;

  async function act(label: string, fn: () => Promise<unknown>, message: string) {
    setBusy(label);
    setError(undefined);
    setDone(undefined);
    try {
      await fn();
      setDone(message);
      health.reload();
    } catch (err) {
      if (err instanceof PortalError) setError(err);
    } finally {
      setBusy(undefined);
    }
  }

  const suites = new Map<string, NonNullable<typeof doctor>["checks"]>();
  for (const c of doctor?.checks ?? []) suites.set(c.suite, [...(suites.get(c.suite) ?? []), c]);

  return (
    <>
      <PageHead
        title="Health"
        sub={doctor ? `Isolation: ${doctor.isolation} · last checked ${age(doctor.checked_at)}` : "The isolation checks have not run yet."}
      >
        <button
          type="button"
          className="primary"
          disabled={busy !== undefined || !h?.up}
          onClick={() => void act("doctor", () => send("POST", "/health/doctor"), "The checks have run.")}
        >
          {busy === "doctor" ? "Running the checks (about a minute)…" : "Run all checks"}
        </button>
      </PageHead>
      <ErrorBox error={health.error ?? error} />
      {done && (
        <p role="status" className="pill good" style={{ alignSelf: "flex-start" }}>
          {done}
        </p>
      )}
      {health.loading && !h && <Loading what="health" />}
      {h && (
        <>
          <div className="stats">
            <div className="stat">
              <b>{capitalize(h.state)}</b>project
            </div>
            <div className="stat">
              <b>{capitalize(h.engine)}</b>engine{h.engine_detail ? ` · ${h.engine_detail}` : ""}
            </div>
            <div className="stat">
              <b>{h.up ? "Up" : "Down"}</b>sandbox
            </div>
          </div>
          {!h.up && (
            <p className="note">
              The sandbox is down. Start it with <code>mirror up</code>; the checks need it running.
            </p>
          )}
          {[...suites.entries()].map(([suite, checks]) => (
            <section key={suite} className="card flush" aria-labelledby={`suite-${suite}`}>
              <div className="card-head">
                <h2 id={`suite-${suite}`} style={{ margin: 0 }}>
                  {capitalize(suite)}
                </h2>
              </div>
              <table>
                <thead>
                  <tr>
                    <th scope="col">Result</th>
                    <th scope="col">Check</th>
                    <th scope="col">Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {checks.map((c) => {
                    const [word, tone] = OUTCOME[c.outcome] ?? [c.outcome, ""];
                    return (
                      <tr key={c.name}>
                        <td>
                          <span className={`verdict ${tone}`}>{word}</span>
                        </td>
                        <th scope="row" style={{ fontWeight: 400 }}>
                          {c.name}
                        </th>
                        <td className="note">{c.detail}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </section>
          ))}
          <section className="card flush" aria-labelledby="containers">
            <div className="card-head">
              <h2 id="containers" style={{ margin: 0 }}>
                Containers
              </h2>
            </div>
            {h.containers.length === 0 ? (
              <p className="muted" style={{ padding: 20 }}>
                {h.engine === "running" ? "None." : "The engine is not running."}
              </p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th scope="col">Container</th>
                    <th scope="col">Role</th>
                    <th scope="col">State</th>
                  </tr>
                </thead>
                <tbody>
                  {h.containers.map((c) => (
                    <tr key={c.name}>
                      <th scope="row" className="mono">
                        {c.name}
                      </th>
                      <td>{capitalize(c.role)}</td>
                      <td>{c.running ? <span className="tag good">Running</span> : <span className="tag bad">Stopped</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
          <section className="card flush" aria-labelledby="snapshots">
            <div className="card-head">
              <h2 id="snapshots" style={{ margin: 0 }}>
                Snapshots
              </h2>
            </div>
            {h.snapshots.length === 0 ? (
              <p className="muted" style={{ padding: 20 }}>
                No snapshots. Create the world with <code>mirror world create</code>.
              </p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th scope="col">Snapshot</th>
                    <th scope="col">Saved</th>
                    <th scope="col">Use</th>
                  </tr>
                </thead>
                <tbody>
                  {h.snapshots.map((s) => (
                    <tr key={s.name}>
                      <th scope="row" className="mono">
                        {s.name}
                      </th>
                      <td>
                        {age(s.created)} · {s.volumes} volumes
                      </td>
                      <td>
                        <button
                          type="button"
                          className="small"
                          disabled={busy !== undefined || !h.up}
                          onClick={() => {
                            if (window.confirm(`Reset the world to ${s.name}? Everything changed since is lost.`))
                              void act(s.name, () => send("POST", `/snapshots/${encodeURIComponent(s.name)}/restore`), `Reset to ${s.name}.`);
                          }}
                        >
                          {busy === s.name ? "Resetting…" : "Reset to this"}
                          <span className="skip"> {s.name}</span>
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}
    </>
  );
}
