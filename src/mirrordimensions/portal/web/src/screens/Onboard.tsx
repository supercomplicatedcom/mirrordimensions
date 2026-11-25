// SPDX-FileCopyrightText: 2026 Supercomplicated LLC
// SPDX-License-Identifier: Apache-2.0
// Onboard an agent in the six steps of `mirror agent new`. Each answer is written to the
// agent's file at once (`status: draft` until step 5), so onboarding can be left and
// resumed here or on the command line, and the file is the one the command line writes.

import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { PortalError, get, send, useApi } from "../api";
import type { AgentDraft, Company, PreflightCheck, RoleDefaults, RunHandle, ScenarioSummary } from "../types";
import { ErrorBox, PageHead, Steps, capitalize } from "../ui";

const STEPS = ["Connect", "Model", "Identity", "Access", "Work", "Check"];
type Grants = RoleDefaults["grants"];

export function Onboard() {
  const { name: resumed } = useParams();
  const navigate = useNavigate();
  const [name, setName] = useState(resumed ?? "");
  const [draft, setDraft] = useState<AgentDraft>();
  const [step, setStep] = useState(1);
  const [error, setError] = useState<PortalError>();
  const company = useApi<Company>(draft ? "/world/people" : null);
  const fail = (err: unknown) => err instanceof PortalError && setError(err);

  const begin = (agent: string) => {
    setError(undefined);
    send<AgentDraft>("POST", "/agents/drafts", { name: agent })
      .then((d) => {
        setDraft(d);
        setStep(Math.min(d.step, 6));
        if (!resumed) navigate(`/agents/new/${encodeURIComponent(d.name)}`, { replace: true });
      })
      .catch(fail);
  };
  useEffect(() => {
    if (resumed) begin(resumed);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const answer = (n: number, body: Record<string, unknown>) => {
    if (!draft) return;
    setError(undefined);
    send<AgentDraft>("PATCH", `/agents/drafts/${encodeURIComponent(draft.name)}`, { step: n, ...body })
      .then((d) => {
        setDraft(d);
        setStep(n + 1);
      })
      .catch(fail);
  };

  return (
    <>
      <PageHead
        eyebrow={
          <>
            <Link to="/agents">Agents</Link> / Onboard an agent
          </>
        }
        title={draft ? `Onboard ${draft.name}` : "Onboard an agent"}
        sub="Six steps. Nothing about the agent's own code changes."
      />
      {!draft ? (
        <section className="card wizard" aria-labelledby="name-title">
          <h2 id="name-title">What is it called?</h2>
          <form
            className="toolbar"
            onSubmit={(e) => {
              e.preventDefault();
              begin(name.trim());
            }}
          >
            <label className="field">
              Name: lowercase letters, digits and dashes
              <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="ops-assistant" />
            </label>
            <button type="submit" className="primary" disabled={!name.trim()}>
              Start
            </button>
          </form>
          <p className="note">An agent already started is continued where it was left.</p>
          <ErrorBox error={error} />
        </section>
      ) : (
        <>
          <Steps steps={STEPS} current={step} reached={Math.min(Math.max(draft.step, step), 6)} onGo={setStep} label="Steps" />
          <ErrorBox error={error} />
          <div className="grid">
            <section className="card wide wizard" aria-labelledby="step-title">
              {step === 1 && <Connect draft={draft} onNext={(f) => answer(1, { fields: f })} />}
              {step === 2 && <Model onNext={(model) => answer(2, { model })} />}
              {step === 3 && <Identity draft={draft} company={company.data} onNext={(f) => answer(3, { fields: f })} />}
              {step === 4 && <Access draft={draft} onNext={(grants) => answer(4, { fields: { grants } })} />}
              {step === 5 && <Work draft={draft} onNext={(wake) => answer(5, { fields: { wake } })} />}
              {step === 6 && <Check name={draft.name} />}
              {step > 1 && step < 6 && (
                <div className="wizard-nav">
                  <button type="button" onClick={() => setStep(step - 1)}>
                    Back
                  </button>
                </div>
              )}
            </section>
            <aside className="card narrow" aria-labelledby="file-title">
              <h2 id="file-title">agents/{draft.name}.yaml, written as you go</h2>
              <pre className="yaml" tabIndex={0}>
                {toYaml(draft.fields)}
              </pre>
              <p className="note">
                The same file comes from: <code>mirror agent new {draft.name}</code>
              </p>
            </aside>
          </div>
        </>
      )}
    </>
  );
}

function toYaml(value: unknown, indent = ""): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return `[${value.map((v) => String(v)).join(", ")}]`;
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([k, v]) =>
        v !== null && typeof v === "object" && !Array.isArray(v) ? `${indent}${k}:\n${toYaml(v, `${indent}  `)}` : `${indent}${k}: ${toYaml(v)}`,
      )
      .join("\n");
  }
  return String(value);
}

function Next({ onClick, disabled, label = "Next" }: { onClick: () => void; disabled?: boolean; label?: string }) {
  return (
    <div className="wizard-nav">
      <span />
      <button type="button" className="primary" onClick={onClick} disabled={disabled}>
        {label}
      </button>
    </div>
  );
}

function Connect({ draft, onNext }: { draft: AgentDraft; onNext: (fields: Record<string, unknown>) => void }) {
  const [mode, setMode] = useState(String(draft.fields.mode ?? "hosted"));
  const [image, setImage] = useState(String(draft.fields.image ?? ""));
  const [build, setBuild] = useState(String(draft.fields.build ?? ""));
  return (
    <>
      <h2 id="step-title">How does the agent connect?</h2>
      <div className="options" role="radiogroup" aria-label="How it connects">
        {(
          [
            ["hosted", "Hosted container", "Its own image runs inside the sandbox. Strongest containment, fullest record. Recommended."],
            ["browser", "Managed browser", "The mirror supplies the browser and the agent drives it. For agents that work through web pages."],
          ] as const
        ).map(([value, title, meta]) => (
          <label key={value} className="option">
            <input type="radio" name="mode" checked={mode === value} onChange={() => setMode(value)} />
            <span>
              <b>{title}</b>
              <span className="meta">{meta}</span>
            </span>
          </label>
        ))}
        <label className="option">
          <input type="radio" name="mode" disabled />
          <span>
            <b>Remote gateway</b>
            <span className="meta">The agent stays on its vendor's platform. Arrives with the MCP ingress (M7.5).</span>
          </span>
        </label>
      </div>
      <label className="field">
        Container image {mode === "browser" ? "(where the agent's own program runs, beside the browser)" : ""}
        <input type="text" value={image} onChange={(e) => setImage(e.target.value)} placeholder="ops-assistant:1.0" />
      </label>
      <label className="field">
        Build it from a folder on this computer (blank if the image exists)
        <input type="text" value={build} onChange={(e) => setBuild(e.target.value)} placeholder="~/agents/ops-assistant" />
      </label>
      {mode === "browser" && (
        <p className="note">The agent signs in with the username and password it is issued, as a person would. Only screenshots and actions go to its model.</p>
      )}
      <Next onClick={() => onNext({ mode, image, ...(build.trim() ? { build: build.trim() } : {}) })} disabled={!image.trim()} />
    </>
  );
}

function Model({ onNext }: { onNext: (model: Record<string, unknown>) => void }) {
  const [where, setWhere] = useState("cloud");
  const [provider, setProvider] = useState("anthropic");
  const [host, setHost] = useState("");
  const [upstream, setUpstream] = useState("");
  const [env, setEnv] = useState("");
  const [tools, setTools] = useState("block");
  return (
    <>
      <h2 id="step-title">Where does its model run?</h2>
      <div className="options" role="radiogroup" aria-label="Where its model runs">
        {(
          [
            ["cloud", "Cloud provider", "Calls leave through the model gateway to one provider host. This is the only exit."],
            ["self-hosted", "Your own hardware", "The gateway forwards to one fixed address and port on your network, and nowhere else."],
            ["none", "No model", "A scripted agent, or one that brings no model of its own."],
          ] as const
        ).map(([value, title, meta]) => (
          <label key={value} className="option">
            <input type="radio" name="where" checked={where === value} onChange={() => setWhere(value)} />
            <span>
              <b>{title}</b>
              <span className="meta">{meta}</span>
            </span>
          </label>
        ))}
        <label className="option">
          <input type="radio" name="where" disabled />
          <span>
            <b>Inside the mirror</b>
            <span className="meta">A model server in the sandbox, with no exit at all. Not available yet.</span>
          </span>
        </label>
      </div>
      {where === "cloud" && (
        <div className="field-row">
          <label className="field">
            Provider
            <select value={provider} onChange={(e) => setProvider(e.target.value)}>
              <option value="anthropic">Anthropic</option>
              <option value="openai">OpenAI</option>
            </select>
          </label>
          <label className="field">
            Model host (blank for the provider's own)
            <input type="text" value={host} onChange={(e) => setHost(e.target.value)} />
          </label>
        </div>
      )}
      {where === "self-hosted" && (
        <div className="field-row">
          <label className="field">
            Hostname the agent uses
            <input type="text" value={host} onChange={(e) => setHost(e.target.value)} placeholder="llm.internal.example" />
          </label>
          <label className="field">
            Address and port to forward to
            <input type="text" value={upstream} onChange={(e) => setUpstream(e.target.value)} placeholder="10.0.0.5:8000" />
          </label>
        </div>
      )}
      {where !== "none" && (
        <>
          <label className="field">
            Credential: read from this variable on the host (blank for the provider's usual)
            <input type="text" value={env} onChange={(e) => setEnv(e.target.value)} placeholder="ANTHROPIC_API_KEY" />
          </label>
          <label className="field">
            Tools that run on the provider's servers
            <select value={tools} onChange={(e) => setTools(e.target.value)}>
              <option value="block">Block (recommended)</option>
              <option value="flag">Allow, and mark coverage incomplete</option>
              <option value="allow">Allow as a stated exception</option>
            </select>
          </label>
          <p className="note">The agent is given a placeholder key. The real one is added at the gateway and never enters the sandbox.</p>
        </>
      )}
      <Next
        onClick={() =>
          onNext({
            where,
            provider: where === "cloud" ? provider : undefined,
            host: host.trim() || undefined,
            upstream: upstream.trim() || undefined,
            credential_env: env.trim() || undefined,
            hosted_tools: tools,
          })
        }
      />
    </>
  );
}

function Identity({
  draft,
  company,
  onNext,
}: {
  draft: AgentDraft;
  company: Company | undefined;
  onNext: (fields: Record<string, unknown>) => void;
}) {
  const acts = (draft.fields.acts_as ?? {}) as { role?: string; person?: string };
  const people = (company?.people ?? []).filter((p) => !p.left);
  const roles = useMemo(() => [...new Set(people.flatMap((p) => p.roles))].sort(), [people]);
  const [role, setRole] = useState(acts.role ?? "engineer");
  const [person, setPerson] = useState(acts.person ?? "");
  const [preview, setPreview] = useState<RoleDefaults>();
  useEffect(() => {
    const q = person ? `?person=${encodeURIComponent(person)}` : "";
    get<RoleDefaults>(`/roles/${encodeURIComponent(role)}/defaults${q}`).then(setPreview, () => setPreview(undefined));
  }, [role, person]);
  return (
    <>
      <h2 id="step-title">Who does it act as?</h2>
      <div className="field-row">
        <label className="field">
          Role
          <select
            value={role}
            onChange={(e) => {
              setRole(e.target.value);
              setPerson("");
            }}
          >
            {(roles.length ? roles : ["engineer"]).map((r) => (
              <option key={r} value={r}>
                {capitalize(r)}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Person in the company
          <select value={person} onChange={(e) => setPerson(e.target.value)}>
            <option value="">Pick for me</option>
            {people
              .filter((p) => p.roles.includes(role))
              .map((p) => (
                <option key={p.username} value={p.username}>
                  {p.name}, {p.title}
                </option>
              ))}
          </select>
        </label>
      </div>
      {preview && (
        <p role="status">
          <b>
            {preview.person.name}, {preview.person.title}.
          </b>{" "}
          An account is issued in each system it is granted, in this person's name, in the form production uses.
        </p>
      )}
      <Next onClick={() => onNext({ acts_as: person ? { person } : { role } })} />
    </>
  );
}

function Access({ draft, onNext }: { draft: AgentDraft; onNext: (grants: Grants) => void }) {
  const acts = (draft.fields.acts_as ?? {}) as { role?: string; person?: string };
  const [grants, setGrants] = useState<Grants>((draft.fields.grants as Grants | undefined) ?? {});
  const [options, setOptions] = useState<RoleDefaults["options"]>();
  const [error, setError] = useState<PortalError>();
  useEffect(() => {
    const q = acts.person ? `?person=${encodeURIComponent(acts.person)}` : "";
    get<RoleDefaults>(`/roles/${encodeURIComponent(acts.role ?? "engineer")}/defaults${q}`)
      .then((d) => {
        setOptions(d.options);
        if (!draft.fields.grants) setGrants(d.grants); // start from the role's usual access
      })
      .catch((err: unknown) => err instanceof PortalError && setError(err));
  }, [acts.role, acts.person, draft.fields.grants]);
  const level = (app: string, key: string, name: string): string => {
    const g = grants[app];
    if (key === "repos") return g?.repos?.[name] ?? "none";
    return g?.channels?.includes(name) ? "member" : "none";
  };
  const set = (app: string, key: string, name: string, value: string) => {
    const g = { ...(grants[app] ?? {}) };
    if (key === "repos") {
      const repos = { ...(g.repos ?? {}) };
      if (value === "none") delete repos[name];
      else repos[name] = value;
      g.repos = repos;
    } else {
      const channels = new Set(g.channels ?? []);
      if (value === "none") channels.delete(name);
      else channels.add(name);
      g.channels = [...channels].sort();
    }
    setGrants({ ...grants, [app]: g });
  };
  return (
    <>
      <h2 id="step-title">What can it reach?</h2>
      <p className="note">
        Start from the role's usual access, then widen or narrow. Grants are exact: the person it acts as has only these during a run. You can change
        them later on the Permissions page.
      </p>
      <ErrorBox error={error} />
      <table>
        <thead>
          <tr>
            <th scope="col">Resource</th>
            <th scope="col">System</th>
            <th scope="col">Grant</th>
          </tr>
        </thead>
        <tbody>
          {(options ?? []).flatMap((o) =>
            o.names.map((n) => {
              const label = o.key === "channels" ? `#${n}` : n;
              const levels = o.levels.length > 1 ? o.levels : ["member"];
              return (
                <tr key={`${o.app_id}-${n}`}>
                  <th scope="row" className="mono">
                    {label}
                  </th>
                  <td>{o.label}</td>
                  <td>
                    <select aria-label={`Grant on ${label}`} value={level(o.app_id, o.key, n)} onChange={(e) => set(o.app_id, o.key, n, e.target.value)}>
                      <option value="none">None</option>
                      {levels.map((l) => (
                        <option key={l} value={l}>
                          {capitalize(l)}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              );
            }),
          )}
        </tbody>
      </table>
      <Next onClick={() => onNext(prune(grants))} disabled={!options} />
    </>
  );
}

/** Systems left with nothing in them are not granted. */
function prune(grants: Grants): Grants {
  const out: Grants = {};
  for (const [app, g] of Object.entries(grants)) {
    if ((g.repos && Object.keys(g.repos).length) || (g.channels && g.channels.length) || g.tools) out[app] = g;
  }
  return out;
}

function Work({ draft, onNext }: { draft: AgentDraft; onNext: (wake: Record<string, unknown>) => void }) {
  const wake = (draft.fields.wake ?? {}) as { type?: string; command?: string[] };
  const [how, setHow] = useState(wake.type ?? "command");
  const [command, setCommand] = useState((wake.command ?? []).join(" "));
  const browser = draft.fields.mode === "browser";
  return (
    <>
      <h2 id="step-title">How does work reach it?</h2>
      <p>
        Work always arrives through a system, the way it would for an employee: an assigned issue or a chat message. This step sets how the
        agent notices.
      </p>
      {browser ? (
        <p className="note">A browser agent watches its inbox in the browser, signing in as a person would.</p>
      ) : (
        <>
          <fieldset className="choice">
            <legend>The agent notices new work when</legend>
            <label>
              <input type="radio" name="wake" checked={how === "command"} onChange={() => setHow("command")} />
              <span>The system sends it an event, and a command runs to handle it</span>
            </label>
            <label>
              <input type="radio" name="wake" checked={how === "poll"} onChange={() => setHow("poll")} />
              <span>It is already watching: start it once and leave it running</span>
            </label>
          </fieldset>
          {how === "command" && (
            <label className="field">
              Command to run
              <input type="text" value={command} onChange={(e) => setCommand(e.target.value)} placeholder="python /opt/agent/run.py" />
            </label>
          )}
        </>
      )}
      <Next
        label="Check and finish"
        disabled={!browser && how === "command" && !command.trim()}
        onClick={() => onNext(browser ? { type: "poll" } : how === "command" ? { type: "command", command: splitCommand(command) } : { type: "poll" })}
      />
    </>
  );
}

/** Split a command line as a shell would, for the simple quoting people type. */
export function splitCommand(text: string): string[] {
  const out: string[] = [];
  const re = /"([^"]*)"|'([^']*)'|(\S+)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) out.push(m[1] ?? m[2] ?? m[3] ?? "");
  return out;
}

function Check({ name }: { name: string }) {
  const navigate = useNavigate();
  const [checks, setChecks] = useState<PreflightCheck[]>();
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<PortalError>();
  const scenarios = useApi<ScenarioSummary[]>("/scenarios");
  const [scenario, setScenario] = useState("");
  const ready = checks !== undefined && checks.every((c) => c.outcome !== "fail");
  return (
    <>
      <h2 id="step-title">Is it ready?</h2>
      <p>The preflight starts nothing from a scenario: it checks the image, the identities, the names it will see, its model route and coverage.</p>
      <div className="toolbar">
        <button
          type="button"
          className="primary"
          disabled={running}
          onClick={() => {
            setRunning(true);
            setError(undefined);
            send<PreflightCheck[]>("POST", `/agents/${encodeURIComponent(name)}/check`)
              .then(setChecks)
              .catch((err: unknown) => err instanceof PortalError && setError(err))
              .finally(() => setRunning(false));
          }}
        >
          {running ? "Checking…" : checks ? "Check again" : "Run the checks"}
        </button>
      </div>
      <ErrorBox error={error} />
      {checks && (
        <ul className="pending-list" aria-label="Checks">
          {checks.map((c) => (
            <li key={c.name}>
              <span className={`verdict ${c.outcome === "fail" ? "fail" : "pass"}`}>{c.outcome === "fail" ? "FAIL" : c.outcome === "pass" ? "OK" : "N/A"}</span>{" "}
              {c.name}
              {c.detail && <span className="muted"> · {c.detail}</span>}
              {c.outcome === "fail" && c.fix && <div className="note">{c.fix}</div>}
            </li>
          ))}
        </ul>
      )}
      <div className="toolbar">
        <Link className="button" to="/agents">
          Save and close
        </Link>
        <label className="field">
          Give it a first job
          <select value={scenario} onChange={(e) => setScenario(e.target.value)}>
            <option value="">Choose a scenario</option>
            {(scenarios.data ?? []).map((s) => (
              <option key={s.id} value={s.id}>
                {s.title}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          disabled={!scenario || !ready}
          onClick={() => {
            send<RunHandle>("POST", "/runs", { scenario, agent: name })
              .then((h) => navigate(`/runs/${h.run_id}/live`))
              .catch((err: unknown) => err instanceof PortalError && setError(err));
          }}
        >
          Run it and watch
        </button>
      </div>
      {!ready && <p className="note">A first job can start once every check passes.</p>}
    </>
  );
}
