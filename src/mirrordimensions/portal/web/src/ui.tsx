// SPDX-FileCopyrightText: 2026 Supercomplicated LLC
// SPDX-License-Identifier: Apache-2.0
// Shared pieces: the page header, errors, and the words every status is shown with.

import type { ReactNode } from "react";
import type { PortalError } from "./api";

export function PageHead(props: { eyebrow?: ReactNode; title: ReactNode; sub?: ReactNode; children?: ReactNode }) {
  return (
    <header className="page-head">
      <div className="titles">
        {props.eyebrow !== undefined && <div className="eyebrow">{props.eyebrow}</div>}
        <h1>{props.title}</h1>
        {props.sub !== undefined && <p className="sub">{props.sub}</p>}
      </div>
      {props.children}
    </header>
  );
}

export function ErrorBox({ error }: { error: PortalError | undefined }) {
  if (!error) return null;
  return (
    <div className="error" role="alert">
      <p>
        <b>{error.detail.what}</b>
      </p>
      {error.detail.why && <p>{error.detail.why}</p>}
      {error.detail.fix && <p>{error.detail.fix}</p>}
    </div>
  );
}

export function Loading({ what }: { what: string }) {
  return (
    <p className="muted" role="status">
      Loading {what}…
    </p>
  );
}

const STATUS_WORDS: Record<string, [string, "good" | "bad" | ""]> = {
  passed: ["Passed", "good"],
  failed: ["Failed", "bad"],
  errored: ["Errored", "bad"],
  stopped: ["Stopped", ""],
  running: ["Running", ""],
  unfinished: ["Did not finish", "bad"],
};

export function RunStatus({ status, coverage }: { status: string; coverage?: string }) {
  if (coverage === "incomplete") return <span className="tag bad">Not usable</span>;
  const [word, tone] = STATUS_WORDS[status] ?? [status, ""];
  return <span className={`tag ${tone}`}>{status === "running" ? <span className="live-dot">{word}</span> : word}</span>;
}

export function coverageWords(coverage: string): string {
  switch (coverage) {
    case "complete":
      return "Complete";
    case "incomplete":
      return "Incomplete";
    case "pending":
      return "Not yet";
    default:
      return "Not recorded";
  }
}

export const VISIBILITY_WORDS: Record<string, [string, string]> = {
  granted: ["Granted", "listed and usable"],
  denied: ["Denied", "visible, access refused"],
  present: ["Present", "running, not in the agent's tools"],
  absent: ["Absent", "not in the mirror"],
};

export function capitalize(text: string): string {
  return text ? text[0]!.toUpperCase() + text.slice(1) : text;
}
