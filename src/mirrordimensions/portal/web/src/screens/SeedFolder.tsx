// SPDX-License-Identifier: Apache-2.0
// A seed folder (decision 0030), the same as `mirror world seed`: the user names one folder,
// ideally of test data; the mirror reads only it and shows what each file became, what was
// left out, and any personal data, which must be accepted before anything is used.

import { useState } from "react";
import { PortalError, send } from "../api";
import type { SeedReview } from "../types";
import { ErrorBox } from "../ui";

const SHOWN = 12;

export function SeedFolder({
  world,
  review,
  onChange,
}: {
  world: string;
  review: SeedReview | null;
  onChange: () => void;
}) {
  const [path, setPath] = useState(review?.folder ?? "");
  const [accept, setAccept] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<PortalError>();

  const act = (work: Promise<unknown>) => {
    setBusy(true);
    setError(undefined);
    work
      .then(() => onChange())
      .catch((err: unknown) => err instanceof PortalError && setError(err))
      .finally(() => setBusy(false));
  };
  const read = (folder: string, acceptPersonal: boolean) =>
    act(
      send<SeedReview>("POST", "/world/seed", {
        folder: world,
        path: folder,
        accept_personal: acceptPersonal,
      }),
    );
  const forget = () => {
    setPath("");
    setAccept(false);
    act(
      send<null>("DELETE", `/world/seed?folder=${encodeURIComponent(world)}`),
    );
  };

  const secretLines =
    review?.secrets_dropped.reduce((n, d) => n + d.lines, 0) ?? 0;
  const waiting =
    review !== null && review.personal.length > 0 && !review.personal_accepted;
  return (
    <section className="panel" aria-labelledby="seed-title">
      <h3 id="seed-title">Your own test data (optional)</h3>
      <p className="note">
        Name one folder of tickets, documents, a people list, chat exports or
        git repositories. The mirror reads only that folder and builds the world
        from it; the rest is generated. Use test data: whatever goes in reaches
        the agent you test and its model provider.
      </p>
      {!review ? (
        <form
          className="toolbar"
          onSubmit={(e) => {
            e.preventDefault();
            read(path, false);
          }}
        >
          <label className="field" style={{ flex: "1 1 360px" }}>
            Seed folder, a full path on this computer
            <input
              type="text"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              placeholder="~/halden-seed"
            />
          </label>
          <button type="submit" disabled={busy || !path.trim()}>
            {busy ? "Reading" : "Read the folder"}
          </button>
        </form>
      ) : (
        <>
          <p>
            Read from <code>{review.folder}</code>: {review.items.length}{" "}
            {review.items.length === 1 ? "file" : "files"} used
            {secretLines > 0
              ? `; ${secretLines} ${secretLines === 1 ? "line" : "lines"} that looked like secrets left out`
              : ""}
            {review.not_read.length > 0
              ? `; ${review.not_read.length} not read`
              : ""}
            .
          </p>
          {review.items.length > 0 && (
            <table aria-label="What each file becomes">
              <thead>
                <tr>
                  <th scope="col">File</th>
                  <th scope="col">Becomes</th>
                </tr>
              </thead>
              <tbody>
                {review.items.slice(0, SHOWN).map((item) => (
                  <tr key={item.path}>
                    <td className="mono">{item.path}</td>
                    <td>{item.becomes}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {review.items.length > SHOWN && (
            <p className="note">And {review.items.length - SHOWN} more.</p>
          )}
          {review.not_read.length > 0 && (
            <details>
              <summary>Not read, and why</summary>
              <ul>
                {review.not_read.map(([file, why]) => (
                  <li key={file}>
                    <span className="mono">{file}</span>: {why}
                  </li>
                ))}
              </ul>
            </details>
          )}
          {review.personal.length > 0 && (
            <div className="notice" role="note" aria-label="Personal data">
              <p>
                <b>
                  It holds what looks like personal data:{" "}
                  {review.personal.length}{" "}
                  {review.personal.length === 1 ? "item" : "items"}.
                </b>{" "}
                {review.personal_accepted
                  ? "You accepted it as test data, so it is used."
                  : "Nothing from the folder is used until you remove it from the folder and read it again, or accept it as test data."}
              </p>
              <ul>
                {review.personal.slice(0, SHOWN).map((p) => (
                  <li key={`${p.path}:${p.line}:${p.kind}`}>
                    <span className="mono">
                      {p.path}:{p.line}
                    </span>{" "}
                    {p.kind}: {p.shown}
                  </li>
                ))}
              </ul>
              {review.personal.length > SHOWN && (
                <p className="note">
                  And {review.personal.length - SHOWN} more.
                </p>
              )}
              {waiting && (
                <div className="toolbar">
                  <label>
                    <input
                      type="checkbox"
                      checked={accept}
                      onChange={(e) => setAccept(e.target.checked)}
                    />{" "}
                    This is test data: build the world with it
                  </label>
                  <button
                    type="button"
                    disabled={busy || !accept}
                    onClick={() => read(review.folder, true)}
                  >
                    Accept and use it
                  </button>
                </div>
              )}
            </div>
          )}
          <p className="note">
            Detection works by patterns and can miss things, so check the folder
            yourself too. What the world uses is copied into the world's private
            folder; read the folder again after changing it.
          </p>
          <div className="toolbar">
            <button
              type="button"
              disabled={busy}
              onClick={() => read(review.folder, review.personal_accepted)}
            >
              Read it again
            </button>
            <button type="button" disabled={busy} onClick={forget}>
              Stop using it
            </button>
          </div>
        </>
      )}
      <ErrorBox error={error} />
    </section>
  );
}
