// SPDX-FileCopyrightText: 2026 Supercomplicated LLC
// SPDX-License-Identifier: Apache-2.0
// Edits saved to mirror.yaml or an agent file that are not in effect yet, and the button
// that puts them into effect now, with each step of a rebuild shown as it happens.

import { useEffect, useState } from "react";
import { API, PortalError, send, useApi } from "./api";
import type { BuildJob, Change } from "./types";
import { ErrorBox } from "./ui";

const APPLIES_WORDS: Record<Change["applies"], string> = {
  "next run": "Next run",
  restart: "Needs a restart",
  rebuild: "Needs a rebuild",
};

export function PendingChanges({ tick, onApplied }: { tick: number; onApplied: () => void }) {
  const changes = useApi<Change[]>(`/changes?t=${tick}`);
  const [steps, setSteps] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<PortalError>();
  const [done, setDone] = useState<string>();
  const reload = changes.reload;

  useEffect(() => {
    if (!running) return;
    const source = new EventSource(`${API}/build/stream`);
    source.addEventListener("step", (e) => setSteps((prev) => [...prev, JSON.parse((e as MessageEvent<string>).data) as string]));
    source.addEventListener("end", (e) => {
      source.close();
      const job = JSON.parse((e as MessageEvent<string>).data) as BuildJob;
      setRunning(false);
      if (job.error) setError(new PortalError(500, job.error));
      else setDone(job.result?.rebuilt ? "Rebuilt. Everything saved is in effect." : "In effect now.");
      reload();
      onApplied();
    });
    return () => source.close();
  }, [running, reload, onApplied]);

  const found = changes.data ?? [];
  if (!found.length && !running && !steps.length && !error) return null;
  const rebuild = found.some((c) => c.applies === "rebuild");
  const restart = !rebuild && found.some((c) => c.applies === "restart");
  return (
    <section className="card pending" aria-labelledby="pending-title">
      <h2 id="pending-title">{found.length ? `${found.length} saved change${found.length === 1 ? "" : "s"} not in effect yet` : "Changes"}</h2>
      {found.length > 0 && (
        <ul className="pending-list">
          {found.map((c, i) => (
            <li key={`${c.kind}-${c.target}-${i}`}>
              <span className={`tag ${c.applies === "next run" ? "" : "bad"}`}>{APPLIES_WORDS[c.applies]}</span> {c.what}
            </li>
          ))}
        </ul>
      )}
      {found.length > 0 && (
        <div className="toolbar">
          <button
            type="button"
            className="primary"
            disabled={running}
            onClick={() => {
              setSteps([]);
              setError(undefined);
              setDone(undefined);
              send<BuildJob>("POST", "/build")
                .then(() => setRunning(true))
                .catch((err: unknown) => err instanceof PortalError && setError(err));
            }}
          >
            {running ? "Applying…" : rebuild ? "Rebuild changes" : restart ? "Restart with changes" : "Apply now"}
          </button>
          <span className="note">
            {rebuild
              ? "A rebuild restores the base snapshot and re-runs the world's creation from the first stage the changes affect."
              : restart
                ? "A system leaves or joins the network: the sandbox restarts, and runs wait until it has."
                : "These take effect at the next run anyway; applying hands the running gateway the new rules and visibility now."}
          </span>
        </div>
      )}
      {(running || steps.length > 0) && (
        <ol className="build-steps" role="log" aria-live="polite" aria-label="Progress">
          {steps.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
          {running && <li className="muted">Working…</li>}
        </ol>
      )}
      {done && (
        <p role="status" className="note">
          {done}
        </p>
      )}
      <ErrorBox error={changes.error ?? error} />
    </section>
  );
}
