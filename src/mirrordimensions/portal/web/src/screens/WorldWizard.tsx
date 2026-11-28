// SPDX-License-Identifier: Apache-2.0
// Define and create a world, in the six steps `mirror world new` asks. Each answer is saved
// at once (mirror.yaml with `status: draft`), so the wizard can be left and resumed, and the
// file it writes is the one the command line writes for the same answers. Creating it shows
// each stage as it runs, then the portal serves the new world.

import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { API, PortalError, send } from "../api";
import type { BuildJob, WorldDraftView } from "../types";
import { ErrorBox, PageHead, Steps } from "../ui";

const STEPS = ["Start", "Company", "Systems", "Links and data", "Review", "Create"];
const STAGES = [
  "Generate the company",
  "Set up the sealed network",
  "Start each system",
  "Load each system",
  "Remove setup traces",
  "Save the base snapshot",
  "Run checks",
  "Ready",
];
const INDUSTRIES = ["logistics", "software", "financial services", "healthcare", "retail", "manufacturing", "insurance"];

type Start = "template" | "systems" | "import";

export function WorldWizard() {
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const [folder, setFolder] = useState(search.get("folder") ?? "");
  const [view, setView] = useState<WorldDraftView>();
  const [step, setStep] = useState(1);
  const [error, setError] = useState<PortalError>();
  const [start, setStart] = useState<Start>("template");
  const [systemsText, setSystemsText] = useState("gitea, mattermost");
  const [stages, setStages] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<BuildJob>();

  const fail = (err: unknown) => err instanceof PortalError && setError(err);
  const open = (name: string) => {
    setError(undefined);
    send<WorldDraftView>("POST", "/worlds/draft", { folder: name })
      .then((v) => {
        setView(v);
        setStep(Math.min(v.step, 5));
        if (v.draft.imported) setStart("import");
        else if (v.draft.systems && !v.draft.template) {
          setStart("systems");
          setSystemsText(v.draft.systems.join(", "));
        }
      })
      .catch(fail);
  };
  useEffect(() => {
    const given = search.get("folder");
    if (given) open(given);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = (fields: Record<string, unknown>, next?: number) => {
    if (!view) return;
    setError(undefined);
    send<WorldDraftView>("PATCH", "/worlds/draft", { folder: view.folder, fields: next ? { ...fields, step: next } : fields })
      .then((v) => {
        setView(v);
        if (next) setStep(next);
      })
      .catch(fail);
  };

  useEffect(() => {
    if (!creating) return;
    const source = new EventSource(`${API}/worlds/create/stream`);
    source.addEventListener("step", (e) => setStages((prev) => [...prev, JSON.parse((e as MessageEvent<string>).data) as string]));
    source.addEventListener("end", (e) => {
      source.close();
      const job = JSON.parse((e as MessageEvent<string>).data) as BuildJob;
      setCreating(false);
      setCreated(job);
      if (job.error) setError(new PortalError(500, job.error));
    });
    return () => source.close();
  }, [creating]);

  const d = view?.draft;
  const company = view?.company;
  return (
    <>
      <PageHead
        eyebrow={
          <>
            <Link to="/worlds">Worlds</Link> / New world
          </>
        }
        title="Define and create a world"
        sub="A world is a company and the systems attached to it. Define it first; nothing is built until the last step."
      />
      {!view ? (
        <section className="card wizard" aria-labelledby="where-title">
          <h2 id="where-title">Where should it live?</h2>
          <form
            className="toolbar"
            onSubmit={(e) => {
              e.preventDefault();
              open(folder);
            }}
          >
            <label className="field" style={{ flex: "1 1 360px" }}>
              Folder: a name beside the current world, or a full path
              <input type="text" value={folder} onChange={(e) => setFolder(e.target.value)} placeholder="acme-ops" />
            </label>
            <button type="submit" className="primary" disabled={!folder.trim()}>
              Start
            </button>
          </form>
          <p className="note">If the folder holds a draft, the wizard continues it where it was left.</p>
          <ErrorBox error={error} />
        </section>
      ) : (
        <>
          <Steps steps={STEPS} current={step} reached={Math.max(view.step, step)} onGo={setStep} label="Steps" />
          <ErrorBox error={error} />
          <div className="grid">
            <section className="card wide wizard" aria-labelledby="step-title">
              {step === 1 && (
                <>
                  <h2 id="step-title">How do you want to start?</h2>
                  <div className="options" role="radiogroup" aria-label="Start">
                    <label className="option">
                      <input type="radio" name="start" checked={start === "template"} onChange={() => setStart("template")} />
                      <span>
                        <b>From a template</b>
                        <span className="meta">A ready-made company shape with typical systems. Fastest way to a first world.</span>
                      </span>
                    </label>
                    <label className="option">
                      <input type="radio" name="start" checked={start === "systems"} onChange={() => setStart("systems")} />
                      <span>
                        <b>Name your systems</b>
                        <span className="meta">List the tools the agent will live among. Each name is matched to a known setup.</span>
                      </span>
                    </label>
                    <label className="option">
                      <input type="radio" name="start" checked={start === "import"} onChange={() => setStart("import")} />
                      <span>
                        <b>Import a description</b>
                        <span className="meta">
                          From files on this computer: agent tool configuration, OpenAPI descriptions, Terraform state. You review what was
                          understood before anything is used.
                        </span>
                      </span>
                    </label>
                  </div>
                  {start === "import" ? (
                    <div className="field">
                      {view.imported ? (
                        <p>
                          {view.imported.sources.length} {view.imported.sources.length === 1 ? "file" : "files"} read: {view.imported.found}{" "}
                          things found, {view.imported.buildable} can be built now
                          {view.imported.open_conflicts > 0 ? `, ${view.imported.open_conflicts} to settle` : ""}.{" "}
                          <Link to={`/worlds/import?folder=${encodeURIComponent(view.folder)}`}>Review the import</Link>
                        </p>
                      ) : (
                        <p>
                          <Link className="button" to={`/worlds/import?folder=${encodeURIComponent(view.folder)}`}>
                            Choose the files
                          </Link>
                        </p>
                      )}
                      <span className="note">The systems come from the import; the company, links and data are set on the next steps.</span>
                    </div>
                  ) : start === "template" ? (
                    <label className="field">
                      Template
                      <select defaultValue={d?.template ?? "software-team"} id="template">
                        {view.templates.map((t) => (
                          <option key={t.name} value={t.name}>
                            {t.description}
                          </option>
                        ))}
                      </select>
                    </label>
                  ) : (
                    <label className="field">
                      Systems, one per line or separated by commas
                      <textarea rows={3} value={systemsText} onChange={(e) => setSystemsText(e.target.value)} />
                      <span className="note">You will see each match on the Systems step.</span>
                    </label>
                  )}
                </>
              )}
              {step === 2 && company && d && (
                <>
                  <h2 id="step-title">The company</h2>
                  <div className="field-row">
                    <label className="field">
                      Company name
                      <input type="text" defaultValue={company.name} key={`n-${company.name}`} id="company-name" />
                    </label>
                    <label className="field">
                      Domain for hostnames and email
                      <input type="text" defaultValue={company.domain} key={`d-${company.domain}`} id="company-domain" />
                    </label>
                  </div>
                  <div className="field-row">
                    <label className="field">
                      Industry
                      <select defaultValue={company.industry} key={`i-${company.industry}`} id="company-industry">
                        {[...new Set([company.industry, ...INDUSTRIES])].map((i) => (
                          <option key={i} value={i}>
                            {i[0]!.toUpperCase() + i.slice(1)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="field">
                      People
                      <input type="number" min={2} max={2000} defaultValue={d.people ?? 25} id="people" />
                    </label>
                    <label className="field">
                      History, in days
                      <input type="number" min={7} max={3650} defaultValue={d.history ?? 180} id="history" />
                    </label>
                  </div>
                  <fieldset className="choice">
                    <legend>How tidy is its data?</legend>
                    {(
                      [
                        ["realistic", "Realistic: some stale and duplicate items"],
                        ["tidy", "Tidy"],
                        ["messy", "Messy"],
                      ] as const
                    ).map(([value, words]) => (
                      <label key={value}>
                        <input type="radio" name="tidiness" value={value} defaultChecked={d.tidiness === value} />
                        <span>{words}</span>
                      </label>
                    ))}
                  </fieldset>
                  <div className="field-row">
                    <label className="field">
                      Seed
                      <input type="number" min={1} defaultValue={d.seed} key={`s-${d.seed}`} id="seed" />
                    </label>
                    <span style={{ alignSelf: "flex-end" }}>
                      <button type="button" onClick={() => save({ another_company: true })}>
                        Suggest another company
                      </button>
                    </span>
                  </div>
                  <p className="note">
                    Use a believable name and domain. They exist only inside the world, and the same seed always produces the same company.
                    Keep the seed private.
                  </p>
                </>
              )}
              {step === 3 && (
                <>
                  <h2 id="step-title">The systems attached to it</h2>
                  {view.proposal && (
                    <section className="panel" aria-label="Systems for this industry">
                      <p>
                        A {view.proposal.profile} company usually runs these. Systems without a twin are recorded in mirror.yaml and left
                        out until one exists.
                      </p>
                      <ul>
                        {view.proposal.lines.map((line) => (
                          <li key={line}>{line}</li>
                        ))}
                      </ul>
                      <button
                        type="button"
                        onClick={() => {
                          setStart("systems");
                          setSystemsText(view.proposal ? view.proposal.systems.join(", ") : systemsText);
                          save({ systems: view.proposal?.systems ?? [] }, 3);
                        }}
                      >
                        Use these systems
                      </button>
                    </section>
                  )}
                  <table>
                    <thead>
                      <tr>
                        <th scope="col">System</th>
                        <th scope="col">Product</th>
                        <th scope="col">Hostname the agent sees</th>
                        <th scope="col">Note</th>
                      </tr>
                    </thead>
                    <tbody>
                      {view.systems.map((s) => (
                        <tr key={`${s.id}-${s.hostname}`}>
                          <th scope="row">{s.kind ? s.kind.replace(/-/g, " ") : s.id}</th>
                          <td>{s.product ?? "None"}</td>
                          <td className="mono">{s.hostname || "None"}</td>
                          <td>
                            {!s.note ? (
                              <span className="tag good">Will be built</span>
                            ) : s.note.startsWith("Runs in place") ? (
                              <span className="tag">{s.note}</span>
                            ) : (
                              <span className="tag bad">{s.note}</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="note">
                    Each system arrives preconfigured; you can change its inputs, outputs, settings and data afterward.{" "}
                    {d?.imported ? (
                      <>
                        The list comes from the import: to change it,{" "}
                        <Link to={`/worlds/import?folder=${encodeURIComponent(view.folder)}`}>review the import</Link>.
                      </>
                    ) : (
                      "To change the list, go back to Start."
                    )}
                  </p>
                </>
              )}
              {step === 4 && d && (
                <>
                  <h2 id="step-title">How the systems connect, and how much they hold</h2>
                  <fieldset className="choice">
                    <legend>Connections between systems</legend>
                    <label>
                      <input type="checkbox" checked disabled />
                      <span>The same people, with the same names and email, exist in every system</span>
                    </label>
                    <label>
                      <input type="checkbox" defaultChecked={d.links.announce ?? true} id="link-announce" />
                      <span>New issues and merged changes are announced in a chat channel</span>
                    </label>
                    <label>
                      <input type="checkbox" defaultChecked={d.links.incidents ?? true} id="link-incidents" />
                      <span>Incidents appear both as chat threads and as tracked issues</span>
                    </label>
                  </fieldset>
                  <div className="field-row">
                    {(
                      [
                        ["repositories", "Repositories"],
                        ["issues", "Issues"],
                        ["messages", "Chat messages"],
                        ["canaries", "Planted secrets, to trace leaks"],
                      ] as const
                    ).map(([key, words]) => (
                      <label key={key} className="field">
                        {words}
                        <input type="number" min={0} defaultValue={d.data[key] ?? 0} id={`data-${key}`} />
                      </label>
                    ))}
                  </div>
                </>
              )}
              {step === 5 && d && company && (
                <>
                  <h2 id="step-title">Review what will be created</h2>
                  <dl className="facts">
                    <dt>Company</dt>
                    <dd>
                      {company.name} ({company.domain}), {d.people ?? 25} people, {d.history ?? 180} days of history, {d.tidiness} data
                    </dd>
                    <dt>Systems</dt>
                    <dd>{view.systems.map((s) => `${s.kind || s.id}${s.note ? ` (${s.note.toLowerCase()})` : ""}`).join(", ")}</dd>
                    <dt>Content</dt>
                    <dd>
                      {d.data.repositories} repositories, {d.data.issues} issues, {d.data.messages} messages
                    </dd>
                    <dt>Planted secrets</dt>
                    <dd>{d.data.canaries}</dd>
                    <dt>Sealed network</dt>
                    <dd>Resolver, gateway, sinkhole</dd>
                    <dt>Agents</dt>
                    <dd>None yet; onboard one after the world exists</dd>
                  </dl>
                  <p className="note">
                    The definition is saved as mirror.yaml. Creating the world is repeatable: the same file and seed give the same world.
                  </p>
                </>
              )}
              {step === 6 && (
                <>
                  <h2 id="step-title">{created && !created.error ? "The world is ready" : "Create the world"}</h2>
                  {!creating && !created && (
                    <p>
                      Every world shares one engine. Creating this one stops the sandbox of whichever world is running now; that world is
                      kept and can be brought back with <code>mirror up</code>. It takes a few minutes.
                    </p>
                  )}
                  {(creating || stages.length > 0) && (
                    <ol className="stages" role="log" aria-live="polite" aria-label="Creation stages">
                      {STAGES.map((name, i) => {
                        const done = stages.some((s) => s.startsWith(`${i + 1}. `));
                        const doneCount = STAGES.filter((_, k) => stages.some((s) => s.startsWith(`${k + 1}. `))).length;
                        const now = creating && !done && i === doneCount;
                        return (
                          <li key={name}>
                            <span className={`tag ${done ? "good" : now ? "" : ""}`}>{done ? "Done" : now ? "Running" : "Waiting"}</span>{" "}
                            {i + 1}. {name}
                          </li>
                        );
                      })}
                    </ol>
                  )}
                  {!creating && !(created && !created.error) && (
                    <div className="toolbar">
                      <button
                        type="button"
                        className="primary"
                        onClick={() => {
                          setError(undefined);
                          setStages([]);
                          setCreated(undefined);
                          send<BuildJob>("POST", "/worlds/create", {
                            folder: view.folder,
                          })
                            .then(() => setCreating(true))
                            .catch(fail);
                        }}
                      >
                        Create world
                      </button>
                    </div>
                  )}
                  {created && !created.error && (
                    <div className="toolbar">
                      <button type="button" className="primary" onClick={() => navigate("/environment")}>
                        Open the environment map
                      </button>
                      <button type="button" onClick={() => navigate("/agents/new")}>
                        Onboard an agent
                      </button>
                    </div>
                  )}
                  <p className="note">If a stage fails, the world stays at the last finished stage and creation can resume from there.</p>
                </>
              )}
              {step < 6 && (
                <div className="wizard-nav">
                  <button type="button" disabled={step === 1} onClick={() => setStep(step - 1)}>
                    Back
                  </button>
                  <button type="button" className="primary" onClick={() => save(answers(step, start, systemsText), step + 1)}>
                    {step === 5 ? "Looks right" : "Next"}
                  </button>
                </div>
              )}
            </section>
            <aside className="card narrow" aria-labelledby="yaml-title">
              <h2 id="yaml-title">mirror.yaml, written as you go</h2>
              <pre className="yaml" tabIndex={0}>
                {view.yaml}
              </pre>
              <p className="note" style={{ overflowWrap: "anywhere" }}>
                The same file comes from: <code>{view.command}</code>
              </p>
            </aside>
          </div>
        </>
      )}
    </>
  );
}

const value = (id: string) => (document.getElementById(id) as HTMLInputElement | HTMLSelectElement | null)?.value ?? "";
const checked = (id: string) => (document.getElementById(id) as HTMLInputElement | null)?.checked ?? false;

/** One step's answers, read from its fields. */
function answers(step: number, start: Start, systemsText: string): Record<string, unknown> {
  if (step === 1) {
    if (start === "import") return { imported: true };
    return start === "template"
      ? { template: value("template") || "software-team" }
      : {
          systems: systemsText
            .split(/[\n,]/)
            .map((s) => s.trim())
            .filter(Boolean),
        };
  }
  if (step === 2) {
    const tidy = (document.querySelector('input[name="tidiness"]:checked') as HTMLInputElement | null)?.value;
    return {
      seed: Number(value("seed")) || undefined,
      company_name: value("company-name"),
      domain: value("company-domain"),
      industry: value("company-industry"),
      people: Number(value("people")),
      history: Number(value("history")),
      tidiness: tidy,
    };
  }
  if (step === 4) {
    return {
      links: {
        announce: checked("link-announce"),
        incidents: checked("link-incidents"),
      },
      data: Object.fromEntries(["repositories", "issues", "messages", "canaries"].map((k) => [k, Number(value(`data-${k}`))])),
    };
  }
  return {};
}
