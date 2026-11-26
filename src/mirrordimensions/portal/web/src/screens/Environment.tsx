// SPDX-FileCopyrightText: 2026 Supercomplicated LLC
// SPDX-License-Identifier: Apache-2.0
// The environment as a map: agents, the gateway, each system and the model endpoints, and
// the devices each device platform fronts. The layout is computed from the graph (left to
// right: agents, gateway, systems, devices), so the same environment always draws the same
// way. A table view lists the same systems and devices.

import { type CSSProperties, useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { PortalError, send, useApi } from "../api";
import { PendingChanges } from "../pending";
import type { Change, Graph, GraphNode, Result, RunSummary } from "../types";
import { ErrorBox, Loading, PageHead, VISIBILITY_WORDS, capitalize } from "../ui";

const COLUMN_X = [24, 316, 608, 900];
const ROW_H = 92;
const NODE_W = 200;
const NODE_H = 64;
const PAD = 24;

type Layer = "visibility" | "build";

interface Placed extends GraphNode {
  x: number;
  y: number;
}

export function layout(graph: Graph): { placed: Placed[]; width: number; height: number } {
  const rows = [0, 0, 0, 0];
  for (const n of graph.nodes) rows[n.column] = Math.max(rows[n.column] ?? 0, n.row + 1);
  const tallest = Math.max(1, ...rows);
  const height = tallest * ROW_H + PAD * 2 - (ROW_H - NODE_H);
  const placed = graph.nodes.map((n) => {
    const count = rows[n.column] ?? 1;
    // Each column is centred against the tallest one.
    const offset = ((tallest - count) * ROW_H) / 2;
    return { ...n, x: COLUMN_X[n.column] ?? 0, y: PAD + offset + n.row * ROW_H };
  });
  const last = Math.max(2, ...graph.nodes.map((n) => n.column));
  return { placed, width: (COLUMN_X[last] ?? 0) + NODE_W + PAD, height };
}

function nodeMeta(n: GraphNode, layer: Layer): string {
  if (n.kind === "system") {
    const product = n.product ? capitalize(n.product) : n.detail;
    if (layer === "build") return `${product} · ${capitalize(n.built_as ?? "")}`;
    return `${product} · ${VISIBILITY_WORDS[n.visibility ?? ""]?.[0] ?? n.visibility ?? ""}`;
  }
  return n.detail;
}

export function Environment() {
  const project = useApi<{ name: string | null; isolation: string | null }>("/project");
  const graph = useApi<Graph>("/environment/graph");
  const runs = useApi<RunSummary[]>("/runs");
  const [layer, setLayer] = useState<Layer>("visibility");
  const [view, setView] = useState<"map" | "table">("map");
  const [selected, setSelected] = useState<string>();
  const [overlayRun, setOverlayRun] = useState<string>("");
  const overlay = useApi<Result>(overlayRun ? `/runs/${overlayRun}` : null);
  const [tick, setTick] = useState(0);
  const reloadGraph = graph.reload;
  const edited = useCallback(() => {
    setTick((t) => t + 1);
    reloadGraph();
  }, [reloadGraph]);

  const touched = useMemo(() => {
    const byHost = new Map<string, number>();
    for (const h of overlay.data?.access?.hosts ?? []) {
      if (h.host && (h.requests ?? 0) + (h.refused ?? 0) > 0) byHost.set(h.host, (h.requests ?? 0) + (h.refused ?? 0));
    }
    return byHost;
  }, [overlay.data]);

  const isolation = project.data?.isolation;
  return (
    <>
      <PageHead eyebrow={project.data?.name ?? ""} title="Environment">
        <span className={`pill ${isolation === "full" ? "good" : isolation ? "bad" : ""}`}>
          Isolation: {isolation ?? "not checked yet"}
        </span>
      </PageHead>
      <ErrorBox error={graph.error ?? project.error} />
      <PendingChanges tick={tick} onApplied={edited} />
      <div className="toolbar" role="group" aria-label="Show layer">
        <span className="note" style={{ alignSelf: "center", marginRight: 4 }}>
          Show layer
        </span>
        <button type="button" aria-pressed={layer === "visibility"} onClick={() => setLayer("visibility")}>
          Visibility
        </button>
        <button type="button" aria-pressed={layer === "build"} onClick={() => setLayer("build")}>
          Build status
        </button>
        <span style={{ flex: 1 }} />
        <label className="field">
          Overlay a run
          <select value={overlayRun} onChange={(e) => setOverlayRun(e.target.value)}>
            <option value="">None</option>
            {(runs.data ?? [])
              .filter((r) => !r.live)
              .map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.run_id} · {r.scenario} · {r.agent}
                </option>
              ))}
          </select>
        </label>
        <button type="button" aria-pressed={view === "table"} onClick={() => setView(view === "map" ? "table" : "map")}>
          {view === "map" ? "Show as a table" : "Show as a map"}
        </button>
      </div>
      {graph.loading && !graph.data && <Loading what="the environment" />}
      {graph.data && (
        <div className="grid">
          <section className="card flush wide" aria-label={view === "map" ? "Environment map" : "Systems"}>
            {view === "map" ? (
              <MapView graph={graph.data} layer={layer} selected={selected} onSelect={setSelected} touched={touched} />
            ) : (
              <TableView graph={graph.data} touched={touched} overlay={overlayRun !== ""} />
            )}
            <p className="note" style={{ padding: "12px 20px", borderTop: "1px solid var(--border)" }}>
              Sandbox: nothing here can reach a real system. The model API is the only exit.
            </p>
          </section>
          <aside className="card narrow" aria-label="Selected">
            <Detail
              key={selected ?? ""}
              node={graph.data.nodes.find((n) => n.id === selected)}
              touched={touched}
              overlay={overlayRun}
              onEdited={edited}
            />
          </aside>
        </div>
      )}
      <Legend />
    </>
  );
}

function MapView(props: {
  graph: Graph;
  layer: Layer;
  selected: string | undefined;
  onSelect: (id: string) => void;
  touched: Map<string, number>;
}) {
  const { placed, width, height } = useMemo(() => layout(props.graph), [props.graph]);
  const at = new Map(placed.map((n) => [n.id, n]));
  return (
    <div style={{ overflowX: "auto" }}>
      <div className="map" style={{ width, height }}>
        <svg className="edges" width={width} height={height} aria-hidden="true">
          {props.graph.edges
            .filter((e) => e.kind !== "grant")
            .map((e) => {
              const a = at.get(e.source);
              const b = at.get(e.target);
              if (!a || !b) return null;
              const x1 = a.x + NODE_W;
              const y1 = a.y + NODE_H / 2;
              const x2 = b.x;
              const y2 = b.y + NODE_H / 2;
              const mid = (x1 + x2) / 2;
              return (
                <path
                  key={`${e.source}-${e.target}`}
                  d={`M ${x1} ${y1} L ${mid} ${y1} L ${mid} ${y2} L ${x2} ${y2}`}
                  fill="none"
                  stroke="#8A94A6"
                  strokeWidth={2}
                  strokeDasharray={e.kind === "exit" ? "6 4" : undefined}
                />
              );
            })}
        </svg>
        {placed.map((n) => {
          const hits = n.hostname ? props.touched.get(n.hostname) : undefined;
          return (
            <button
              key={n.id}
              type="button"
              className={`node ${n.kind} ${n.kind === "system" && props.layer === "visibility" ? `vis-${n.visibility}` : ""}`}
              style={{ left: n.x, top: n.y }}
              aria-pressed={props.selected === n.id}
              onClick={() => props.onSelect(n.id)}
            >
              <span className="name">{n.label}</span>
              <span className="meta">{nodeMeta(n, props.layer)}</span>
              {hits !== undefined && <span className="tag good">Touched: {hits} request(s)</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function TableView({ graph, touched, overlay }: { graph: Graph; touched: Map<string, number>; overlay: boolean }) {
  const systems = graph.nodes.filter((n) => n.kind === "system" || n.kind === "model");
  const devices = graph.nodes.filter((n) => n.kind === "device");
  const platformOf = (id: string) => {
    const edge = graph.edges.find((e) => e.target === id);
    return graph.nodes.find((n) => n.id === edge?.source)?.label ?? "";
  };
  return (
    <div className="table-wrap">
      <table>
        <caption className="skip">Systems in this environment</caption>
        <thead>
          <tr>
            <th scope="col">System</th>
            <th scope="col">Product</th>
            <th scope="col">Hostname the agent sees</th>
            <th scope="col">Visibility</th>
            <th scope="col">Built as</th>
            <th scope="col">Granted to</th>
            {overlay && <th scope="col">Touched in the run</th>}
          </tr>
        </thead>
        <tbody>
          {systems.map((n) => (
            <tr key={n.id}>
              <th scope="row">{n.label}</th>
              <td>{n.product ? capitalize(n.product) : n.detail}</td>
              <td className="mono">{n.hostname}</td>
              <td>{n.kind === "model" ? "The only exit" : (VISIBILITY_WORDS[n.visibility ?? ""]?.[0] ?? "")}</td>
              <td>{n.kind === "model" ? "Outside the sandbox" : capitalize(n.built_as ?? "")}</td>
              <td>{n.granted_to.join(", ") || "Nobody"}</td>
              {overlay && <td>{n.hostname && touched.has(n.hostname) ? `${touched.get(n.hostname)} request(s)` : "No"}</td>}
            </tr>
          ))}
        </tbody>
      </table>
      {devices.length > 0 && (
        <table>
          <caption className="skip">Devices in this environment</caption>
          <thead>
            <tr>
              <th scope="col">Device</th>
              <th scope="col">Type</th>
              <th scope="col">Where</th>
              <th scope="col">Reached through</th>
            </tr>
          </thead>
          <tbody>
            {devices.map((n) => (
              <tr key={n.id}>
                <th scope="row">{n.label}</th>
                <td>{n.detail}</td>
                <td>{n.location}</td>
                <td>{platformOf(n.id)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Detail({
  node,
  touched,
  overlay,
  onEdited,
}: {
  node: GraphNode | undefined;
  touched: Map<string, number>;
  overlay: string;
  onEdited: () => void;
}) {
  const [saved, setSaved] = useState<Change>();
  const [error, setError] = useState<PortalError>();
  const [choice, setChoice] = useState(node?.visibility ?? undefined);
  useEffect(() => setChoice(node?.visibility ?? undefined), [node?.visibility]);
  if (!node) {
    return (
      <>
        <h2>Selected</h2>
        <p className="muted">Choose a box on the map to see its details.</p>
      </>
    );
  }
  return (
    <>
      <h2>{node.label}</h2>
      <dl className="facts">
        {node.product && (
          <>
            <dt>Product</dt>
            <dd>{capitalize(node.product)}</dd>
          </>
        )}
        {node.built_as && (
          <>
            <dt>Built as</dt>
            <dd>{capitalize(node.built_as)}</dd>
          </>
        )}
        {node.hostname && (
          <>
            <dt>{node.kind === "model" ? "Host" : "Hostname the agent sees"}</dt>
            <dd className="mono">{node.hostname}</dd>
          </>
        )}
        {node.kind === "system" && (
          <>
            <dt>Granted to</dt>
            <dd>{node.granted_to.join(", ") || "Nobody"}</dd>
          </>
        )}
        {node.kind !== "system" && node.detail && (
          <>
            <dt>What it is</dt>
            <dd>{capitalize(node.detail)}</dd>
          </>
        )}
        {node.location && (
          <>
            <dt>Where</dt>
            <dd>{node.location}</dd>
          </>
        )}
        {overlay && node.hostname && (
          <>
            <dt>In {overlay}</dt>
            <dd>{touched.has(node.hostname) ? `${touched.get(node.hostname)} request(s)` : "Not touched"}</dd>
          </>
        )}
      </dl>
      {node.kind === "system" && node.visibility && (
        <fieldset className="choice">
          <legend>Visibility, for every agent</legend>
          {Object.entries(VISIBILITY_WORDS).map(([key, [word, meaning]]) => (
            <label key={key}>
              <input
                type="radio"
                name={`visibility-${node.id}`}
                value={key}
                checked={choice === key}
                onChange={() => {
                  setError(undefined);
                  setChoice(key);
                  send<Change>("PATCH", `/environment/apps/${node.id.slice("system:".length)}`, { visibility: key })
                    .then((c) => {
                      setSaved(c);
                      onEdited();
                    })
                    .catch((err: unknown) => {
                      setChoice(node.visibility ?? undefined);
                      if (err instanceof PortalError) setError(err);
                    });
                }}
              />
              <span>
                <b>{word}</b> <span className="muted">{meaning}</span>
              </span>
            </label>
          ))}
        </fieldset>
      )}
      {saved && (
        <p role="status" className="note">
          Saved to mirror.yaml.{" "}
          {saved.applies === "rebuild"
            ? "It needs a rebuild."
            : saved.applies === "restart"
              ? "It takes effect when the sandbox restarts."
              : "It takes effect at the next run."}
        </p>
      )}
      <ErrorBox error={error} />
      {node.kind === "system" && node.built_as === "real software" && node.product && (
        <p style={{ marginTop: 12 }}>
          <Link to={`/environment/systems/${node.id.slice("system:".length)}`}>Inputs and outputs of {node.label}</Link>
        </p>
      )}
      <p className="note" style={{ marginTop: 16 }}>
        Changes are written to mirror.yaml. Visibility, rules and grants take effect at the next run; making a system absent, or bringing
        one back, restarts the sandbox when you apply it.
      </p>
    </>
  );
}

function Legend() {
  return (
    <div className="legend" aria-label="Legend">
      {Object.entries(VISIBILITY_WORDS).map(([key, [word, meaning]]) => (
        <span key={key}>
          <span className={`swatch node-swatch vis-${key}`} style={swatchStyle(key)} />
          <b>{word}</b> {meaning}
        </span>
      ))}
    </div>
  );
}

function swatchStyle(key: string): CSSProperties {
  switch (key) {
    case "granted":
      return { border: "2px solid #1D4ED8" };
    case "denied":
      return { border: "2px solid #9A3412", background: "#FFF4E8" };
    case "present":
      return { border: "2px solid #C9CED6" };
    default:
      return { border: "2px dashed #C9CED6" };
  }
}
