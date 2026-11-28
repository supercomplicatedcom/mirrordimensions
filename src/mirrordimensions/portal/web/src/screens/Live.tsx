// SPDX-License-Identifier: Apache-2.0
// The live view: the agent moving through the world as it works. A marker sits on the
// resource it is acting on, a trail shows the path so far, and the Now panel says in plain
// words what it is doing. During a run it follows the step stream; afterwards the same
// controls replay it. A finished run opens paused at the first step.

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { API, PortalError, send, useApi } from "../api";
import { KIND_WORDS, MAP_WIDTH, isBad, layout, markers, merge, spotOf, totals, trail, withTouched } from "../live";
import type { RunSummary, Step, StepsView } from "../types";
import { ErrorBox, Loading, PageHead, RunStatus } from "../ui";

const PLAY_MS = 1500;

export function Live() {
  const { runId = "" } = useParams();
  const [tick, setTick] = useState(0);
  const view = useApi<StepsView>(`/runs/${runId}/steps?t=${tick}`);
  const runs = useApi<RunSummary[]>("/runs");
  const summary = runs.data?.find((r) => r.run_id === runId);
  const [steps, setSteps] = useState<Step[]>([]);
  const [cursor, setCursor] = useState(0);
  const [following, setFollowing] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [stopError, setStopError] = useState<PortalError>();
  const live = view.data?.live ?? false;

  // A finished run: every step at once, paused at the first.
  useEffect(() => {
    if (!view.data || view.data.live) return;
    setSteps(view.data.steps);
    setStreaming(false);
  }, [view.data]);

  // A run in progress: follow its steps as they happen. The stream starts from the first
  // step and sends a step again whenever it grows or turns out to have broken a rule.
  const reloadRuns = runs.reload;
  const ended = useCallback(() => {
    setTick((t) => t + 1);
    reloadRuns();
  }, [reloadRuns]);
  useEffect(() => {
    if (!live) return;
    setSteps([]);
    setFollowing(true);
    setStreaming(true);
    const source = new EventSource(`${API}/runs/${runId}/steps/stream`);
    source.addEventListener("step", (e) => {
      const step = JSON.parse((e as MessageEvent<string>).data) as Step;
      setSteps((prev) => merge(prev, step));
    });
    source.addEventListener("end", () => {
      source.close();
      setStreaming(false);
      ended();
    });
    return () => source.close();
  }, [live, runId, ended]);

  const last = steps.length - 1;
  const current = following ? Math.max(0, last) : Math.min(cursor, Math.max(0, last));

  useEffect(() => {
    if (!playing) return;
    if (current >= last) {
      setPlaying(false);
      return;
    }
    const timer = window.setTimeout(() => setCursor(current + 1), PLAY_MS);
    return () => window.clearTimeout(timer);
  }, [playing, current, last]);

  const go = (i: number) => {
    setFollowing(false);
    setPlaying(false);
    setCursor(Math.max(0, Math.min(last, i)));
  };
  const toggle = () => {
    if (playing) {
      setPlaying(false);
      return;
    }
    setFollowing(false);
    setCursor(current >= last ? 0 : current);
    setPlaying(true);
  };

  const agents = view.data?.agents ?? [];
  const agent = agents[0] ?? summary?.agent ?? "agent";
  const places = useMemo(() => withTouched(view.data?.places ?? [], steps), [view.data, steps]);
  const map = useMemo(() => layout(places, agent), [places, agent]);
  const now = steps[current];
  const count = totals(steps, current);
  const status = streaming ? (following ? "Live" : "Paused") : summary && !summary.live ? null : "Paused";

  return (
    <>
      <PageHead
        eyebrow={
          <>
            <Link to="/runs">Runs</Link> / <Link to={`/runs/${runId}`} className="mono">{runId}</Link> / Live view
          </>
        }
        title={`Watching ${agent} work`}
        sub={summary?.scenario ? `Job: ${summary.scenario}` : undefined}
      >
        {status ? (
          <span className={`tag ${status === "Live" ? "good" : ""}`}>{status === "Live" ? <span className="live-dot">Live</span> : status}</span>
        ) : (
          summary && <RunStatus status={summary.status} coverage={summary.coverage} />
        )}
        <Link className="button" to={`/runs/${runId}`}>
          Full run detail
        </Link>
        {streaming && (
          <button
            type="button"
            onClick={() => {
              send("POST", `/runs/${runId}/stop`).catch((err: unknown) => err instanceof PortalError && setStopError(err));
            }}
          >
            Stop the run
          </button>
        )}
      </PageHead>
      <ErrorBox error={view.error ?? runs.error ?? stopError} />
      {!view.data && !view.error && <Loading what="the run's steps" />}
      {view.data && (
        <div className="grid">
          <section className="card wide live-map-card" aria-labelledby="map-title">
            <h2 id="map-title">Where it is</h2>
            <div className="live-scroll" tabIndex={0} aria-label="The map (scrolls sideways on a narrow screen)">
            <div
              className="live-map"
              role="img"
              aria-label={now ? `${agent} is at ${now.location.label}: ${now.sentence}` : `${agent} has not started yet`}
              style={{ width: MAP_WIDTH, height: map.height }}
            >
              <svg className="trail" width={MAP_WIDTH} height={map.height} aria-hidden="true">
                {agents.flatMap((name) =>
                  trail(map, steps, current, name).map((seg, i) => (
                    <line
                      key={`${name}-${i}`}
                      x1={seg.from[0]}
                      y1={seg.from[1]}
                      x2={seg.to[0]}
                      y2={seg.to[1]}
                      className={`${seg.bad ? "bad" : "good"}${seg.latest ? " latest" : ""}`}
                    />
                  )),
                )}
              </svg>
              {map.boxes.map((b) => (
                <div
                  key={b.id}
                  aria-hidden="true"
                  className={`live-box ${b.kind}${now && now.location.system === b.id && !now.location.place ? (isBad(now) ? " here bad" : " here") : ""}`}
                  style={{ left: b.x, top: b.y, width: b.w, height: b.h }}
                >
                  <span className="name">{b.label}</span>
                  {b.meta && <span className="meta">{b.meta}</span>}
                </div>
              ))}
              {map.chips.map((c) => {
                const here = now && `${now.location.system}|${now.location.place}` === c.id;
                const seen = steps.some((s) => s.index <= current && `${s.location.system}|${s.location.place}` === c.id);
                return (
                  <div
                    key={c.id}
                    aria-hidden="true"
                    className={`live-chip${c.granted ? "" : " ungranted"}${seen ? " seen" : ""}${here ? (isBad(now) ? " here bad" : " here") : ""}`}
                    style={{ left: c.x, top: c.y, width: c.w, height: c.h }}
                  >
                    {c.label}
                    {!c.granted && <span className="meta"> · not granted</span>}
                  </div>
                );
              })}
              {markers(steps, current, agents).map(({ agent: name, step }) => {
                const [x, y] = spotOf(map, step);
                const word = step ? KIND_WORDS[step.kind] : "";
                return (
                  <div
                    key={name}
                    aria-hidden="true"
                    className={`marker${isBad(step) ? " bad" : ""}`}
                    style={{ transform: `translate(${x - 12}px, ${y - 12}px)` }}
                  >
                    <span className="dot" />
                    <span className="marker-label">
                      {name}
                      {word ? ` · ${word}` : ""}
                    </span>
                  </div>
                );
              })}
            </div>
            </div>
            <p className="note">
              The dot shows where the agent is acting; the line behind it is the path it has taken, the latest part strongest. Dashed lines and
              orange mark blocked attempts and broken rules.
            </p>
          </section>
          <div className="narrow live-side">
            <section className={`card now${isBad(now) ? " bad" : ""}`} aria-labelledby="now-title" aria-live={following ? "polite" : "off"}>
              <h2 id="now-title">Now</h2>
              {now ? (
                <>
                  <p className="mono">
                    {now.at} · {now.location.label}
                  </p>
                  <p className="now-sentence">
                    {now.sentence}
                    {KIND_WORDS[now.kind] && <span className={`tag ${isBad(now) ? "bad" : ""}`}> {KIND_WORDS[now.kind]}</span>}
                  </p>
                  {now.detail && <p className="muted">{now.detail}</p>}
                  <p>
                    <Link to={`/runs/${runId}?event=${now.events[0] ?? ""}`}>
                      Its {now.events.length === 1 ? "event" : `${now.events.length} events`} in the timeline
                    </Link>
                  </p>
                </>
              ) : (
                <p className="muted">{streaming ? "Waiting for the agent's first step…" : "This run has no steps."}</p>
              )}
            </section>
            <div className="stats live-stats">
              <div className="stat">
                <b>{count.requests}</b> requests to systems
              </div>
              <div className="stat">
                <b>{count.thoughts}</b> model calls
              </div>
              <div className="stat">
                <b>{count.blocked}</b> blocked attempts
              </div>
              <div className={`stat${count.violations ? " bad" : ""}`}>
                <b>{count.violations}</b> rules broken
              </div>
            </div>
          </div>
          <section className="card wide" aria-labelledby="controls-title">
            <h2 id="controls-title" className="visually-hidden">
              Replay
            </h2>
            <div className="toolbar live-controls">
              <button type="button" onClick={() => go(current - 1)} disabled={current <= 0}>
                Back
              </button>
              <button type="button" className="primary" onClick={toggle} disabled={steps.length === 0}>
                {playing ? "Pause" : current >= last && last > 0 ? "Replay" : "Play"}
              </button>
              <button type="button" onClick={() => go(current + 1)} disabled={current >= last}>
                Next
              </button>
              {streaming && !following && (
                <button type="button" onClick={() => setFollowing(true)}>
                  Follow live
                </button>
              )}
              <label className="field live-jump">
                <span>
                  Step {steps.length ? current + 1 : 0} of {steps.length}
                </span>
                <input
                  type="range"
                  min={0}
                  max={Math.max(0, last)}
                  value={current}
                  aria-label="Jump to a step"
                  aria-valuetext={now ? `Step ${current + 1}: ${now.sentence}` : "No steps"}
                  onChange={(e) => go(Number(e.target.value))}
                  disabled={steps.length < 2}
                />
              </label>
            </div>
          </section>
          <section className="card narrow" aria-labelledby="steps-title">
            <h2 id="steps-title">Steps so far</h2>
            <ol className="feed" reversed>
              {steps
                .slice(0, current + 1)
                .reverse()
                .map((s) => (
                  <li key={s.index}>
                    <button
                      type="button"
                      className={`feed-row${isBad(s) ? " bad" : ""}`}
                      aria-current={s.index === current ? "step" : undefined}
                      onClick={() => go(s.index)}
                    >
                      <span className="mono">{s.at}</span>
                      <span>{s.sentence}</span>
                      {KIND_WORDS[s.kind] ? <span className={`tag ${isBad(s) ? "bad" : ""}`}>{KIND_WORDS[s.kind]}</span> : <span />}
                    </button>
                  </li>
                ))}
            </ol>
          </section>
        </div>
      )}
    </>
  );
}
