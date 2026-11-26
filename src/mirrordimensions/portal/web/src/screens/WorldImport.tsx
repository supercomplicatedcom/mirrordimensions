// SPDX-FileCopyrightText: 2026 Supercomplicated LLC
// SPDX-License-Identifier: Apache-2.0
// World import (decision 0025): choose files on this computer, then review what they
// described, settle where they disagree, and apply it. The same draft as
// `mirror world import`: either can be used, and each sees what the other did. For a world
// the wizard is defining, applying returns to the wizard with the imported systems.

import { Fragment, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { PortalError, send, useApi } from "../api";
import type { ImportApplied, ImportConflict, ImportFinding, ImportReview } from "../types";
import { ErrorBox, Loading, PageHead } from "../ui";

export function WorldImport() {
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const folder = search.get("folder") ?? "";
  const query = folder ? `?folder=${encodeURIComponent(folder)}` : "";
  const loaded = useApi<ImportReview | null>(`/world/import${query}`);
  const kinds = useApi<{ name: string; label: string }[]>("/world/import/kinds");
  const [review, setReview] = useState<ImportReview | null>();
  const [error, setError] = useState<PortalError>();
  const [paths, setPaths] = useState("");
  const [kind, setKind] = useState("");
  const [busy, setBusy] = useState(false);
  const [applied, setApplied] = useState<ImportApplied>();

  const shown = review !== undefined ? review : loaded.data;
  const fail = (err: unknown) => err instanceof PortalError && setError(err);
  const act = <T,>(call: Promise<T>, then: (value: T) => void) => {
    setError(undefined);
    setBusy(true);
    call
      .then(then)
      .catch(fail)
      .finally(() => setBusy(false));
  };
  const target = folder ? { folder } : {};
  const decide = (subject: string, decision: string) =>
    act(send<ImportReview>("PATCH", `/world/import/findings/${encodeURIComponent(subject)}`, { ...target, decision }), setReview);

  const wizard = `/worlds/new?folder=${encodeURIComponent(folder)}`;
  return (
    <>
      <PageHead
        eyebrow={
          <>
            <Link to="/worlds">Worlds</Link> / {folder ? <Link to={wizard}>New world</Link> : "This world"} / Import
          </>
        }
        title={shown ? "Review what was understood" : "Import a description"}
        sub="Files are read where they are on this computer and never copied. Nothing is added to the world definition until you apply it."
      >
        {shown && !applied && (
          <div className="toolbar">
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                act(send<null>("DELETE", `/world/import${query}`), () => {
                  setReview(null);
                  setApplied(undefined);
                })
              }
            >
              Discard
            </button>
            <button
              type="button"
              className="primary"
              disabled={busy || shown.open_conflicts > 0}
              onClick={() =>
                act(send<ImportApplied>("POST", "/world/import/apply", target), (result) => {
                  if (result.wizard) navigate(wizard);
                  else setApplied(result);
                })
              }
            >
              Apply to the definition
            </button>
          </div>
        )}
      </PageHead>
      <ErrorBox error={error ?? loaded.error} />
      {loaded.loading && review === undefined && <Loading what="the import" />}
      {applied && <Applied applied={applied} />}
      {!loaded.loading && !applied && (
        <>
          <section className="card" aria-labelledby="read-title">
            <h2 id="read-title">{shown ? "Read more files" : "Which files describe the company?"}</h2>
            <p className="note">
              Agent tool configuration (such as .mcp.json) and exported tool lists, OpenAPI descriptions, and Terraform state. Secret values
              are skipped and never stored; people's names and addresses are not read.
            </p>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                const list = paths
                  .split("\n")
                  .map((p) => p.trim())
                  .filter(Boolean);
                act(
                  send<ImportReview>("POST", "/world/import", {
                    ...target,
                    paths: list,
                    kind: kind || null,
                  }),
                  (r) => {
                    setReview(r);
                    setPaths("");
                  },
                );
              }}
            >
              <label className="field">
                Files on this computer: full paths, one per line
                <textarea rows={4} style={{ width: "100%" }} value={paths} onChange={(e) => setPaths(e.target.value)} spellCheck={false} />
              </label>
              <div className="toolbar">
                <label className="field">
                  Kind of file
                  <select value={kind} onChange={(e) => setKind(e.target.value)}>
                    <option value="">Recognize each file</option>
                    {(kinds.data ?? []).map((k) => (
                      <option key={k.name} value={k.name}>
                        {k.label}
                      </option>
                    ))}
                  </select>
                </label>
                <button type="submit" className={shown ? "" : "primary"} disabled={busy || !paths.trim()}>
                  Read the files
                </button>
              </div>
            </form>
          </section>
          {shown && <Review review={shown} busy={busy} decide={decide} />}
        </>
      )}
    </>
  );
}

function Review({ review, busy, decide }: { review: ImportReview; busy: boolean; decide: (subject: string, decision: string) => void }) {
  const r = review;
  return (
    <>
      <div className="stats" aria-label="Totals" style={{ margin: "20px 0" }}>
        <div className="stat">
          <b>{r.found}</b>things found
        </div>
        <div className="stat">
          <b>{r.buildable}</b>can be built now
        </div>
        <div className={`stat ${r.open_conflicts ? "bad" : ""}`}>
          <b>{r.open_conflicts}</b>
          {r.open_conflicts === 1 ? "disagreement" : "disagreements"} to settle
        </div>
        <div className="stat">
          <b>{r.sources.length}</b>
          {r.sources.length === 1 ? "file" : "files"} read
        </div>
      </div>
      {r.conflicts.map((c) => (
        <Conflict key={c.id} conflict={c} busy={busy} decide={decide} />
      ))}
      <section className="card flush" aria-labelledby="findings-title" style={{ marginTop: 20 }}>
        <div className="card-head">
          <h2 id="findings-title" style={{ margin: 0 }}>
            Findings
          </h2>
        </div>
        <table>
          <thead>
            <tr>
              <th scope="col">Found</th>
              <th scope="col">Kind</th>
              <th scope="col">Came from</th>
              <th scope="col">What we understood</th>
              <th scope="col">Your decision</th>
            </tr>
          </thead>
          <tbody>
            {r.findings.map((f) => (
              <Row key={f.id} finding={f} words={r.words} busy={busy} decide={decide} />
            ))}
          </tbody>
        </table>
      </section>
      <div className="grid" style={{ marginTop: 20 }}>
        <section className="card wide" aria-labelledby="sources-title">
          <h2 id="sources-title">What was read</h2>
          <dl className="facts stacked">
            {r.sources.map((s) => (
              <Fragment key={`${s.importer}-${s.file}`}>
                <dt>
                  {s.label} <span className="mono note">{s.file}</span>
                </dt>
                <dd>
                  {s.summary}
                  {s.skipped_secrets > 0 &&
                    `. ${s.skipped_secrets} secret ${s.skipped_secrets === 1 ? "value" : "values"} skipped, none stored`}
                  {s.skipped_people > 0 && `. ${s.skipped_people} person ${s.skipped_people === 1 ? "detail" : "details"} not read`}
                </dd>
              </Fragment>
            ))}
          </dl>
        </section>
        <section className="card narrow" aria-labelledby="gaps-title">
          <h2 id="gaps-title">What no file could tell us</h2>
          <dl className="facts">
            {r.gaps.map((g) => (
              <Fragment key={g.what}>
                <dt>{g.what}</dt>
                <dd>{g.why}</dd>
              </Fragment>
            ))}
          </dl>
        </section>
      </div>
    </>
  );
}

function Conflict({
  conflict,
  busy,
  decide,
}: {
  conflict: ImportConflict;
  busy: boolean;
  decide: (subject: string, decision: string) => void;
}) {
  const c = conflict;
  return (
    <section className={c.settled ? "card" : "notice"} aria-labelledby={`conflict-${c.id}`} style={{ marginTop: 12 }}>
      <p id={`conflict-${c.id}`}>
        <b>
          {c.settled ? "Settled: " : ""}
          {c.choices.length === 2 ? "Two" : c.choices.length} sources disagree on the {c.field} for {c.label}.
        </b>
      </p>
      <fieldset className="choice">
        <legend>Which {c.field} does the agent use?</legend>
        {c.choices.map((choice) => (
          <label key={choice.value}>
            <input
              type="radio"
              name={`conflict-${c.id}`}
              checked={c.settled === choice.value}
              disabled={busy}
              onChange={() => decide(c.id, choice.value)}
            />
            <span>
              <span className="mono">{choice.value}</span> <span className="note">from {choice.sources.join("; ")}</span>
            </span>
          </label>
        ))}
      </fieldset>
    </section>
  );
}

function Row({
  finding,
  words,
  busy,
  decide,
}: {
  finding: ImportFinding;
  words: Record<string, string>;
  busy: boolean;
  decide: (subject: string, decision: string) => void;
}) {
  const f = finding;
  const unavailable = f.tools.filter((t) => !t.mapped);
  return (
    <tr>
      <th scope="row">
        {f.label}
        {f.hostname && <div className="mono note">{f.hostname}</div>}
      </th>
      <td>{f.kind_label}</td>
      <td className="note">{f.sources.join("; ")}</td>
      <td>
        {f.understood}
        {f.tools.length > 0 && (
          <div className="note">
            {f.tools.length - unavailable.length} of {f.tools.length} tools served.
            {unavailable.length > 0 && (
              <>
                {" "}
                Unavailable:{" "}
                {unavailable.map((t, i) => (
                  <span key={t.name}>
                    {i > 0 && ", "}
                    <span className="mono">{t.name}</span> ({t.reason})
                  </span>
                ))}
              </>
            )}
          </div>
        )}
      </td>
      <td>
        <select aria-label={`Decision for ${f.label}`} value={f.decision} disabled={busy} onChange={(e) => decide(f.id, e.target.value)}>
          {f.options.map((o) => (
            <option key={o} value={o}>
              {words[o] ?? o}
            </option>
          ))}
        </select>
        {f.proposed && <div className="note">Proposed</div>}
      </td>
    </tr>
  );
}

function Applied({ applied }: { applied: ImportApplied }) {
  return (
    <section className="card" aria-labelledby="applied-title">
      <h2 id="applied-title">Applied to mirror.yaml</h2>
      {applied.changes.length === 0 ? (
        <p>Nothing changed: the definition already holds everything the import says.</p>
      ) : (
        <ul>
          {applied.changes.map((c, i) => (
            <li key={i}>{c.what}</li>
          ))}
        </ul>
      )}
      <p className="note">
        Each entry is traced to the facts it came from (<code>mirror world import provenance</code>). The world is rebuilt from the new
        definition with <code>mirror world create</code>.
      </p>
      <div className="toolbar">
        <Link className="button primary" to="/environment">
          Open the environment map
        </Link>
      </div>
    </section>
  );
}
