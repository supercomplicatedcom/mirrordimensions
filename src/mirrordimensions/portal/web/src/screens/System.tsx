// SPDX-FileCopyrightText: 2026 Supercomplicated LLC
// SPDX-License-Identifier: Apache-2.0
// One system's inputs and outputs: every portal page and endpoint the agent can use, what
// each takes in and gives back, and whether a rule customizes it. Choosing one opens a
// rule form (a body size limit, added delay, a share of requests failing, who it applies
// to), saved to mirror.yaml and used from the next run, and a dry run of a request.

import { useCallback, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { PortalError, send, useApi } from "../api";
import { PendingChanges } from "../pending";
import { type RuleForm, formFromRule, ruleFromForm, ruleWords } from "../rules";
import type { AgentSummary, Change, Rule, Surface, SystemDetail, TryResult } from "../types";
import { ErrorBox, Loading, PageHead, capitalize } from "../ui";

type Show = "all" | "customized";

const ERROR_WORDS: Record<string, string> = {
  forbidden: 'The product\'s "forbidden" error',
  not_found: 'The product\'s "not found" error',
  too_large: 'The product\'s "too large" error',
  unavailable: 'The product\'s "unavailable" error',
  rate_limited: 'The product\'s "too many requests" error',
};

function errorWords(name: string): string {
  return ERROR_WORDS[name] ?? `The product's ${name.replace(/_/g, " ")} error`;
}

export function SystemScreen() {
  const { appId = "" } = useParams();
  const [tick, setTick] = useState(0);
  const system = useApi<SystemDetail>(`/systems/${appId}?t=${tick}`);
  const agents = useApi<AgentSummary[]>("/agents");
  const [show, setShow] = useState<Show>("all");
  const [chosen, setChosen] = useState<string>();
  const reload = system.reload;
  const edited = useCallback(() => {
    setTick((t) => t + 1);
    reload();
  }, [reload]);
  const d = system.data;
  const rulesByName = useMemo(() => new Map((d?.rules ?? []).map((r) => [r.name, r])), [d]);
  const surfaces = (d?.surfaces ?? []).filter((s) => show === "all" || s.customized_by.length > 0);
  const surface = d?.surfaces.find((s) => s.id === chosen);
  const label = d ? capitalize(d.summary.kind?.replace(/-/g, " ") ?? d.summary.product ?? d.summary.id) : appId;

  return (
    <>
      <PageHead
        eyebrow={
          <>
            <Link to="/environment">Environment</Link> / {label}
          </>
        }
        title={d ? `${label}: inputs and outputs` : "System"}
        sub={
          d
            ? `${capitalize(d.summary.product ?? "")} · ${d.summary.hostname} · ${d.summary.rules} rule${d.summary.rules === 1 ? "" : "s"} active`
            : undefined
        }
      />
      <ErrorBox error={system.error} />
      <PendingChanges tick={tick} onApplied={edited} />
      {!d && !system.error && <Loading what="the system" />}
      {d && (
        <div className="grid">
          <section className="card flush wide" aria-labelledby="surfaces-title">
            <div className="card-head">
              <h2 id="surfaces-title" style={{ margin: 0 }}>
                Portals and endpoints
              </h2>
              <span style={{ flex: 1 }} />
              <div className="toolbar" role="group" aria-label="Show">
                <button type="button" className="small" aria-pressed={show === "all"} onClick={() => setShow("all")}>
                  All
                </button>
                <button type="button" className="small" aria-pressed={show === "customized"} onClick={() => setShow("customized")}>
                  Customized only
                </button>
              </div>
            </div>
            <div className="table-wrap">
              <table className="surfaces">
                <thead>
                  <tr>
                    <th scope="col">Kind</th>
                    <th scope="col">Portal or endpoint</th>
                    <th scope="col">Takes in</th>
                    <th scope="col">Gives back</th>
                    <th scope="col">Behavior</th>
                  </tr>
                </thead>
                <tbody>
                  {surfaces.map((s) => (
                    <tr key={s.id} className={s.id === chosen ? "selected" : ""}>
                      <td>{capitalize(s.kind)}</td>
                      <th scope="row">
                        <button type="button" className="link" aria-pressed={s.id === chosen} onClick={() => setChosen(s.id)}>
                          <span className="mono">
                            {s.method} {s.path}
                          </span>
                        </button>
                        <div className="note">{s.sentence}</div>
                      </th>
                      <td>{s.takes}</td>
                      <td>{s.gives}</td>
                      <td>
                        {s.customized_by.length ? (
                          <span className="tag bad">
                            Customized: {s.customized_by.map((n) => (rulesByName.get(n) ? ruleWords(rulesByName.get(n)!) : n)).join("; ")}
                          </span>
                        ) : (
                          <span className="tag">Preconfigured</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          <aside className="narrow live-side" aria-label="Selected endpoint">
            {surface ? (
              <RuleEditor
                key={surface.id}
                appId={appId}
                surface={surface}
                existing={surface.customized_by.map((n) => rulesByName.get(n)).find((r): r is Rule => Boolean(r))}
                errors={d.errors}
                agents={(agents.data ?? []).map((a) => a.name)}
                onSaved={edited}
              />
            ) : (
              <section className="card">
                <h2>Selected endpoint</h2>
                <p className="muted">Choose a portal or endpoint to customize how it behaves, or to try a request.</p>
              </section>
            )}
            {surface && <TryPanel key={`try-${surface.id}`} appId={appId} surface={surface} />}
          </aside>
        </div>
      )}
    </>
  );
}

function RuleEditor(props: {
  appId: string;
  surface: Surface;
  existing: Rule | undefined;
  errors: string[];
  agents: string[];
  onSaved: () => void;
}) {
  const { appId, surface, existing } = props;
  const [form, setForm] = useState<RuleForm>(() => formFromRule(surface.id, existing));
  const [problems, setProblems] = useState<string[]>([]);
  const [error, setError] = useState<PortalError>();
  const [saved, setSaved] = useState<Change>();
  const set = (key: keyof RuleForm) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });
  const writes = ["POST", "PUT", "PATCH"].includes(surface.method);
  const errors = props.errors.length ? props.errors : ["forbidden", "unavailable"];

  const save = () => {
    const [rule, found] = ruleFromForm(surface.id, form, existing?.name === form.name ? existing : undefined);
    setProblems(found);
    setError(undefined);
    if (!rule) return;
    send<Change>("PUT", `/systems/${appId}/rules/${encodeURIComponent(rule.name)}`, rule)
      .then((c) => {
        setSaved(c);
        props.onSaved();
      })
      .catch((err: unknown) => err instanceof PortalError && setError(err));
  };
  const remove = () => {
    if (!existing) return;
    send<Change>("DELETE", `/systems/${appId}/rules/${encodeURIComponent(existing.name)}`)
      .then((c) => {
        setSaved(c);
        setForm(formFromRule(surface.id, undefined));
        props.onSaved();
      })
      .catch((err: unknown) => err instanceof PortalError && setError(err));
  };

  return (
    <section className="card rule-form" aria-labelledby="rule-title">
      <h2 id="rule-title">{surface.sentence || surface.id}</h2>
      <p className="mono note">
        {surface.method} {surface.path}
      </p>
      <label className="field">
        Rule name
        <input type="text" value={form.name} onChange={set("name")} />
      </label>
      {writes && (
        <fieldset className="choice">
          <legend>Input</legend>
          <label className="field">
            Largest body accepted, in bytes (empty for no limit)
            <input type="text" inputMode="numeric" value={form.maxBody} onChange={set("maxBody")} />
          </label>
          <label className="field">
            When rejected, answer with
            <select value={form.onReject} onChange={set("onReject")}>
              {errors.map((e) => (
                <option key={e} value={e}>
                  {errorWords(e)}
                </option>
              ))}
            </select>
          </label>
        </fieldset>
      )}
      <fieldset className="choice">
        <legend>Output</legend>
        <div className="field-row">
          <label className="field">
            Added delay from, ms
            <input type="text" inputMode="numeric" value={form.delayLow} onChange={set("delayLow")} />
          </label>
          <label className="field">
            to, ms
            <input type="text" inputMode="numeric" value={form.delayHigh} onChange={set("delayHigh")} />
          </label>
        </div>
        <div className="field-row">
          <label className="field">
            Fail this share of requests, %
            <input type="text" inputMode="decimal" value={form.failPercent} onChange={set("failPercent")} />
          </label>
          <label className="field">
            Failing with
            <select value={form.failError} onChange={set("failError")}>
              {errors.map((e) => (
                <option key={e} value={e}>
                  {errorWords(e)}
                </option>
              ))}
            </select>
          </label>
        </div>
      </fieldset>
      <label className="field">
        Applies to
        <select value={form.agent} onChange={set("agent")}>
          <option value="">Every identity</option>
          {props.agents.map((a) => (
            <option key={a} value={a}>
              {a} only
            </option>
          ))}
        </select>
      </label>
      {problems.length > 0 && (
        <div className="error" role="alert">
          {problems.map((p) => (
            <p key={p}>{p}</p>
          ))}
        </div>
      )}
      <ErrorBox error={error} />
      <div className="toolbar">
        <button type="button" className="primary" onClick={save}>
          Save rule
        </button>
        {existing && (
          <button type="button" onClick={remove}>
            Remove rule {existing.name}
          </button>
        )}
      </div>
      {saved && (
        <p role="status" className="note">
          {saved.what}. Saved to mirror.yaml; used from the next run.
        </p>
      )}
      <p className="note">
        The agent sees an ordinary product response, with the product's own error pages. Every time a rule fires it is recorded in the run.
      </p>
    </section>
  );
}

/** A path to try: the surface's pattern with each name filled in as itself. */
export function examplePath(path: string): string {
  return path.replace(/\{(\w+)\+?\}/g, (_m, name: string) => name);
}

function TryPanel({ appId, surface }: { appId: string; surface: Surface }) {
  const [path, setPath] = useState(examplePath(surface.path));
  const [body, setBody] = useState("");
  const [result, setResult] = useState<TryResult>();
  const [error, setError] = useState<PortalError>();
  const writes = ["POST", "PUT", "PATCH"].includes(surface.method);
  return (
    <section className="card" aria-labelledby="try-title">
      <h2 id="try-title">Try a request</h2>
      <p className="note">
        A dry run: which rules fire and what the agent would get. The product is asked directly, never through the gateway, so the agent
        sees nothing of it.
      </p>
      <label className="field">
        Path, for {surface.method}
        <input type="text" value={path} onChange={(e) => setPath(e.target.value)} />
      </label>
      {writes && (
        <label className="field">
          Body
          <textarea rows={4} value={body} onChange={(e) => setBody(e.target.value)} />
        </label>
      )}
      <div className="toolbar">
        <button
          type="button"
          onClick={() => {
            setError(undefined);
            send<TryResult>("POST", `/systems/${appId}/try`, { method: surface.method, path, body })
              .then(setResult)
              .catch((err: unknown) => err instanceof PortalError && setError(err));
          }}
        >
          Try it
        </button>
      </div>
      <ErrorBox error={error} />
      {result && (
        <div className="detail-pane" role="status">
          <p>
            <b>{result.status}</b>
            {result.from_rule ? " from a rule" : " from the product"} ·{" "}
            {result.rules_fired.length ? `rules fired: ${result.rules_fired.map((r) => r.rule).join(", ")}` : "no rule fired"}
          </p>
          <pre>{result.body.slice(0, 4000)}</pre>
        </div>
      )}
    </section>
  );
}
