// SPDX-FileCopyrightText: 2026 Supercomplicated LLC
// SPDX-License-Identifier: Apache-2.0
// One run: the result and any broken forbidden check without scrolling, how it behaved
// (facts generated from the result, no judgments), and the timeline, a page at a time.
// Selecting a row opens the stored request and response, the model exchange or the state
// change. While a run is in progress the timeline follows it live.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { API, PortalError, get, send, useApi } from "../api";
import type { Check, EventPage, Result, RunEvent, RunSummary } from "../types";
import { ErrorBox, Loading, PageHead, RunStatus, capitalize } from "../ui";

const PAGE = 500;

type Kind = "all" | "model" | "requests" | "state" | "outside";
const KINDS: [Kind, string, string][] = [
  ["all", "All", ""],
  ["requests", "Requests", "http.exchange,ws.frame,mcp.call,browser.navigate,browser.action"],
  ["model", "Model", "model.exchange,model.refused,model.hosted_tools"],
  ["state", "State changes", "state.diff,side_effect.unexpected"],
  ["outside", "Blocked", "egress.blocked,route.unknown_host,dns.query"],
];

/** The event a check's evidence names ("event 52: GET …"), or its own `event`. */
export function checkEvent(c: Check): number | undefined {
  if (typeof c.event === "number") return c.event;
  const m = /\bevent (\d+)\b/.exec(c.evidence ?? "");
  return m ? Number(m[1]) : undefined;
}

function checkWords(c: Check): [string, string] {
  if (c.kind === "forbidden") return c.passed ? ["PASS", "pass"] : ["BROKE", "broke"];
  return c.passed ? ["PASS", "pass"] : ["FAIL", "fail"];
}

export function RunDetail() {
  const { runId = "" } = useParams();
  const runs = useApi<RunSummary[]>("/runs");
  const summary = runs.data?.find((r) => r.run_id === runId);
  const [resultTick, setResultTick] = useState(0);
  const result = useApi<Result>(summary && !summary.live ? `/runs/${runId}?t=${resultTick}` : null);
  const live = summary?.live ?? false;
  const r = result.data;
  const [selected, setSelected] = useState<number>();
  const [jump, setJump] = useState<number>();
  const [stopError, setStopError] = useState<PortalError>();
  const [stopping, setStopping] = useState(false);
  const [search] = useSearchParams();
  const asked = Number(search.get("event") ?? "");

  // Opened from the live view with ?event=N: show that event, once the run has loaded.
  useEffect(() => {
    if (r && asked > 0) {
      setSelected(asked);
      setJump(asked);
    }
  }, [r, asked]);

  // A run started a moment ago may not be listed yet: look again until it is.
  useEffect(() => {
    if (!runs.data || summary || runs.error) return;
    const timer = window.setTimeout(runs.reload, 1000);
    return () => window.clearTimeout(timer);
  }, [runs.data, summary, runs.error, runs.reload]);

  const reloadRuns = runs.reload;
  const ended = useCallback(() => {
    reloadRuns();
    setResultTick((t) => t + 1);
  }, [reloadRuns]);

  const broken = (r?.checks ?? []).filter((c) => c.kind === "forbidden" && !c.passed);
  const openEvent = (seq: number) => {
    setSelected(seq);
    setJump(seq);
  };

  return (
    <>
      <PageHead
        eyebrow={
          <>
            <Link to="/runs">Runs</Link> / <span className="mono">{runId}</span>
          </>
        }
        title={r?.scenario ?? summary?.scenario ?? runId}
        sub={
          r
            ? `${r.agent}${r.acts_as ? `, acting as ${r.acts_as}` : ""}${r.delivery?.channel ? ` · work arrived as ${String(r.delivery.channel)}` : ""}`
            : summary
              ? `${summary.agent} · in progress`
              : undefined
        }
      >
        {summary && <RunStatus status={summary.status} coverage={summary.coverage} />}
        {summary && (
          <Link className="button" to={`/runs/${runId}/live`}>
            {live ? "Watch it live" : "Replay it step by step"}
          </Link>
        )}
        {live && (
          <button
            type="button"
            disabled={stopping}
            onClick={() => {
              setStopping(true);
              send("POST", `/runs/${runId}/stop`)
                .catch((err: unknown) => err instanceof PortalError && setStopError(err))
                .finally(() => setStopping(false));
            }}
          >
            {stopping ? "Stopping…" : "Stop the run"}
          </button>
        )}
        {r && (
          <a className="button" href={`${API}/runs/${runId}/report`} target="_blank" rel="noreferrer">
            Open the report
          </a>
        )}
      </PageHead>
      <ErrorBox error={runs.error ?? result.error ?? stopError} />
      {r?.reason && (
        <p>
          <b>Why:</b> {r.reason}
        </p>
      )}
      {r?.coverage?.status === "incomplete" && (
        <p className="error" role="note">
          Coverage is incomplete, so this run cannot be used as evidence, whatever its checks say.
        </p>
      )}
      {broken.map((c) => {
        const seq = checkEvent(c);
        return (
          <div key={c.check} className="error" role="note">
            <p>
              <span className="verdict broke">BROKE</span> <b>Forbidden: {c.check}</b>
            </p>
            <p>{c.evidence}</p>
            {seq !== undefined && (
              <p>
                <button type="button" className="small" onClick={() => openEvent(seq)}>
                  Open the request that broke it (event {seq})
                </button>
              </p>
            )}
          </div>
        );
      })}
      {(!runs.data || (!summary && !runs.error)) && <Loading what="the run" />}
      {r && (
        <div className="grid">
          <section className="card wide" aria-labelledby="checks">
            <h2 id="checks">Checks</h2>
            <Checks result={r} onOpen={openEvent} />
          </section>
          <section className="card narrow" aria-labelledby="behaved">
            <h2 id="behaved">How it behaved</h2>
            <Behaviour result={r} onOpen={openEvent} />
          </section>
        </div>
      )}
      {summary && (
        <Timeline runId={runId} live={live} selected={selected} onSelect={setSelected} jump={jump} onEnded={ended} broken={broken} />
      )}
    </>
  );
}

function Checks({ result, onOpen }: { result: Result; onOpen: (seq: number) => void }) {
  if (result.checks.length === 0) return <p className="muted">No checks ran.</p>;
  return (
    <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 10 }}>
      {result.checks.map((c) => {
        const [word, tone] = checkWords(c);
        const seq = checkEvent(c);
        return (
          <li key={`${c.kind}-${c.check}`} style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
            <span className={`verdict ${tone}`}>{word}</span>
            <span>
              {c.kind === "forbidden" && <b>Forbidden: </b>}
              <code>{c.check}</code>
              {c.evidence && <span className="muted"> · {c.evidence}</span>}
              {seq !== undefined && (
                <>
                  {" "}
                  <button type="button" className="small" onClick={() => onOpen(seq)}>
                    Event {seq}
                  </button>
                </>
              )}
            </span>
          </li>
        );
      })}
      <li className="note">
        {result.side_effects.length === 0
          ? `No unexpected changes (${result.allowed_changes} allowed by the scenario).`
          : `${result.side_effects.length} unexpected change(s): ${result.side_effects.map((s) => `${s.system} ${s.object} ${s.change}`).join("; ")}.`}
      </li>
    </ul>
  );
}

function Behaviour({ result, onOpen }: { result: Result; onOpen: (seq: number) => void }) {
  const a = result.access;
  const countOf = (rows: { granted: unknown; how?: string[] }[] | undefined) => {
    const granted = (rows ?? []).filter((x) => x.granted);
    const touched = granted.filter((x) => x.how && x.how.length);
    return `${touched.length} of ${granted.length}`;
  };
  const access = a?.hosts
    ? `Touched ${countOf(a.repositories)} repositories and ${countOf(a.channels)} channels it was granted. ${
        a.outside_grants ? `${a.outside_grants} thing(s) used outside its grants.` : "Nothing outside its grants."
      }`
    : "Not recorded for this run.";
  return (
    <dl className="facts stacked">
      <dt>Access</dt>
      <dd>{access}</dd>
      <dt>Data flow</dt>
      <dd>
        {result.canaries.length === 0
          ? "No planted secret left the place it was planted."
          : result.canaries.map((c) => (
              <div key={c.canary}>
                <code>{c.canary}</code> seen in {c.seen.join("; ")}
              </div>
            ))}
      </dd>
      <dt>Exploration</dt>
      <dd>
        {result.egress.length === 0
          ? "No attempt to reach outside the world."
          : result.egress.map((e) => (
              <div key={e.event}>
                {capitalize(e.kind)} to <code>{e.to}</code>, refused ·{" "}
                <button type="button" className="small" onClick={() => onOpen(e.event)}>
                  Event {e.event}
                </button>
              </div>
            ))}
      </dd>
      <dt>Suspected a test</dt>
      <dd>
        {result.suspected
          ? result.suspicion.map((s, i) => (
              <div key={`${s.event}-${i}`}>
                “{s.phrase}” ·{" "}
                <button type="button" className="small" onClick={() => onOpen(s.event)}>
                  Event {s.event}
                </button>
              </div>
            ))
          : "No sign in its output."}
      </dd>
      <dt>Coverage</dt>
      <dd>{capitalize(result.coverage?.status ?? "not recorded")}</dd>
    </dl>
  );
}

function Timeline(props: {
  runId: string;
  live: boolean;
  selected: number | undefined;
  onSelect: (seq: number) => void;
  jump: number | undefined;
  onEnded: () => void;
  broken: Check[];
}) {
  const { runId, live, onEnded } = props;
  const [kind, setKind] = useState<Kind>("all");
  const [query, setQuery] = useState("");
  const [applied, setApplied] = useState("");
  const [page, setPage] = useState<EventPage>();
  const [error, setError] = useState<PortalError>();
  const [streamed, setStreamed] = useState<RunEvent[]>([]);
  const types = KINDS.find(([k]) => k === kind)?.[2] ?? "";
  const brokenAt = useMemo(() => new Set(props.broken.map(checkEvent).filter((x): x is number => x !== undefined)), [props.broken]);

  const load = useCallback(
    (offset: number, around?: number) => {
      const params = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
      if (types) params.set("type", types);
      if (applied) params.set("q", applied);
      if (around !== undefined) params.set("around", String(around));
      get<EventPage>(`/runs/${runId}/events?${params.toString()}`)
        .then((p) => {
          setPage(p);
          setError(undefined);
        })
        .catch((err: unknown) => err instanceof PortalError && setError(err));
    },
    [runId, types, applied],
  );

  useEffect(() => {
    if (!live) load(0);
  }, [live, load]);

  // Jump to an event: load the page that holds it (with no filter, so it is in view).
  useEffect(() => {
    if (props.jump === undefined || live) return;
    setKind("all");
    setApplied("");
    setQuery("");
    const params = new URLSearchParams({ limit: String(PAGE), around: String(props.jump) });
    get<EventPage>(`/runs/${runId}/events?${params.toString()}`).then(setPage, () => undefined);
  }, [props.jump, runId, live]);

  // Live: follow the run's stream; when it ends, read the result.
  useEffect(() => {
    if (!live) return;
    setStreamed([]);
    const source = new EventSource(`${API}/runs/${runId}/events/stream`);
    source.addEventListener("event", (e) => {
      const event = JSON.parse((e as MessageEvent<string>).data) as RunEvent;
      setStreamed((prev) => [...prev, event]);
    });
    source.addEventListener("end", () => {
      source.close();
      onEnded();
    });
    return () => source.close();
  }, [live, runId, onEnded]);

  const rows = live
    ? streamed.filter(
        (e) => (!types || types.split(",").includes(e.type)) && (!applied || JSON.stringify(e).toLowerCase().includes(applied.toLowerCase())),
      )
    : (page?.events ?? []);
  const total = live ? rows.length : (page?.total ?? 0);
  const offset = live ? 0 : (page?.offset ?? 0);

  const selectedRow = useRef<HTMLTableRowElement>(null);
  useEffect(() => {
    selectedRow.current?.scrollIntoView({ block: "center" });
    selectedRow.current?.focus();
  }, [page, props.jump]);

  const chosen = rows.find((e) => e.seq === props.selected);
  return (
    <div className="grid">
      <section className="card flush wide" aria-labelledby="timeline">
        <div className="card-head">
          <h2 id="timeline" style={{ margin: 0 }}>
            Timeline {live && <span className="live-dot note">following the run</span>}
          </h2>
          <span style={{ flex: 1 }} />
          <div className="toolbar" role="group" aria-label="Show">
            {KINDS.map(([k, label]) => (
              <button key={k} type="button" className="small" aria-pressed={kind === k} onClick={() => setKind(k)}>
                {label}
              </button>
            ))}
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setApplied(query.trim());
            }}
            style={{ display: "flex", gap: 8 }}
          >
            <label className="field">
              <span className="skip">Search the timeline</span>
              <input type="search" value={query} placeholder="Search" onChange={(e) => setQuery(e.target.value)} />
            </label>
            <button type="submit" className="small">
              Search
            </button>
          </form>
        </div>
        <ErrorBox error={error} />
        <div className="table-wrap" style={{ maxHeight: 640, overflowY: "auto" }}>
          <table className="timeline">
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">Time</th>
                <th scope="col">Source</th>
                <th scope="col">What happened</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => {
                const isSelected = e.seq === props.selected;
                return (
                  <tr
                    key={e.seq}
                    ref={isSelected ? selectedRow : undefined}
                    className={`selectable ${isSelected ? "selected" : ""} ${brokenAt.has(e.seq) ? "broke" : ""}`}
                    tabIndex={0}
                    aria-selected={isSelected}
                    onClick={() => props.onSelect(e.seq)}
                    onKeyDown={(k) => {
                      if (k.key === "Enter" || k.key === " ") {
                        k.preventDefault();
                        props.onSelect(e.seq);
                      }
                    }}
                  >
                    <td className="seq">{e.seq}</td>
                    <td className="at">{e.at}</td>
                    <td>{capitalize(e.source)}</td>
                    <td>
                      {e.summary}
                      {brokenAt.has(e.seq) && <b> · Forbidden check broke here.</b>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="card-head" style={{ borderTop: "1px solid var(--border)", borderBottom: 0 }}>
          <span className="note">
            {total === 0
              ? "No events match."
              : live
                ? `${total} events so far`
                : `Events ${offset + 1} to ${offset + rows.length} of ${total}`}
          </span>
          <span style={{ flex: 1 }} />
          {!live && offset > 0 && (
            <button type="button" className="small" onClick={() => load(Math.max(0, offset - PAGE))}>
              Earlier events
            </button>
          )}
          {!live && offset + rows.length < total && (
            <button type="button" className="small" onClick={() => load(offset + PAGE)}>
              Later events
            </button>
          )}
        </div>
      </section>
      <aside className="card narrow detail-pane" aria-labelledby="detail" style={{ position: "sticky", top: 16 }}>
        <h2 id="detail">{chosen ? `Event ${chosen.seq}` : "Details"}</h2>
        {chosen ? <EventDetail runId={runId} event={chosen} /> : <p className="muted">Select a row to see the full request, the model exchange, or the state change beside it.</p>}
      </aside>
    </div>
  );
}

const BODY_KEYS: [string, string][] = [
  ["req_body_ref", "Request body"],
  ["resp_body_ref", "Response body"],
  ["body_ref", "Frame"],
  ["answer_ref", "What the model wrote"],
];

function EventDetail({ runId, event }: { runId: string; event: RunEvent }) {
  const refs: [string, string][] = BODY_KEYS.filter(([k]) => typeof event.data[k] === "string").map(([k, label]) => [
    label,
    String(event.data[k]),
  ]);
  if (event.type === "model.exchange") refs.unshift(["Prompt", `model/${event.seq}.request.json`]);
  if (event.type === "model.exchange") refs.splice(1, 0, ["Answer", `model/${event.seq}.answer.txt`]);
  const shown = { ...event.data };
  for (const k of ["req_headers", "resp_headers"]) delete shown[k];
  return (
    <>
      <p>
        <b>{event.summary}</b>
      </p>
      <p className="note">
        {capitalize(event.source)} · {event.type} · {event.at}
      </p>
      <pre aria-label="Event data">{JSON.stringify(shown, null, 2)}</pre>
      {["req_headers", "resp_headers"].map((k) =>
        Array.isArray(event.data[k]) ? (
          <details key={k}>
            <summary>{k === "req_headers" ? "Request headers" : "Response headers"}</summary>
            <pre>{(event.data[k] as [string, string][]).map(([n, v]) => `${n}: ${v}`).join("\n")}</pre>
          </details>
        ) : null,
      )}
      {refs.map(([label, ref]) => (
        <Body key={ref} runId={runId} label={label} bodyRef={ref} />
      ))}
      <p className="note" style={{ marginTop: 8 }}>
        Secrets were redacted when this was captured.
      </p>
    </>
  );
}

function Body({ runId, label, bodyRef }: { runId: string; label: string; bodyRef: string }) {
  const [text, setText] = useState<string>();
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    setText(undefined);
    setMissing(false);
    fetch(`${API}/runs/${runId}/bodies/${bodyRef}`, { credentials: "same-origin" })
      .then(async (res) => {
        if (!res.ok) {
          setMissing(true);
          return;
        }
        const raw = await res.text();
        try {
          setText(JSON.stringify(JSON.parse(raw), null, 2));
        } catch {
          setText(raw);
        }
      })
      .catch(() => setMissing(true));
  }, [runId, bodyRef]);
  return (
    <details open={label !== "Prompt"}>
      <summary>{label}</summary>
      {missing ? (
        <p className="note">Not kept for this run (runs before M7 kept bodies only inside the sandbox).</p>
      ) : text === undefined ? (
        <p className="note">Loading…</p>
      ) : (
        <pre>{text.length > 20000 ? `${text.slice(0, 20000)}\n… (${text.length - 20000} more characters)` : text}</pre>
      )}
    </details>
  );
}
