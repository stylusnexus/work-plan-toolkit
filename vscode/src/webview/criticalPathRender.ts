/**
 * Critical-path graph renderer (#445): CriticalPathModel -> Mermaid text.
 *
 * LAYOUT DECISION (Task 1 spike, variant A2): `graph LR` with one labelled
 * `subgraph` per rank column (each `direction TB`), plus invisible chain links
 * between the column subgraphs (`col_a ~~~ col_b ~~~ ...`) so Done is leftmost
 * and the "can't rank" column is rightmost. Without the chain links, an
 * edge-less column floats to the top-left. "Outside" nodes (issues in other
 * repos or untracked) are declared OUTSIDE every column subgraph: an edge ran
 * behind them when they sat inside one. Connector and "done" stub nodes are
 * outside any column too. Member ids are listed inside each subgraph and the
 * labelled declarations follow, exactly as in the spike.
 *
 * Pure: no vscode imports, no Date / Math.random. Output is deterministic and
 * node ids never contain free text (titles only ever appear inside labels,
 * and always through mermaidLabel).
 */

import type { TrackKey } from "../model.ts";
import type { CritIssueNode, CriticalPathModel } from "./criticalPath.ts";
import { classDefLines, mermaidLabel } from "./graph.ts";

export interface CriticalFilter {
  trackKey: TrackKey | null;
  focusIssue: string | null;
  showClosed: boolean;
}

export interface CriticalRender {
  mermaid: string;
  edgeCount: number;
  tooLarge: boolean;
  banner: string | null;
  legend: { trackKey: TrackKey; label: string; color: string }[];
  empty: string | null;
  /** "Too large to draw (N issues, M links)…" when tooLarge, else null. */
  tooLargeMessage: string | null;
}

const MAX_EDGES = 450;
const MAX_CHARS = 45_000;
const MAX_TITLE = 40;

// Chip border colours, light / dark theme. Cycled by trackOrder index; the
// track label printed on every node is what actually disambiguates (#244).
const PALETTE: readonly (readonly [string, string])[] = [
  ["#2563eb", "#60a5fa"], ["#d97706", "#fbbf24"], ["#059669", "#34d399"],
  ["#db2777", "#f472b6"], ["#7c3aed", "#a78bfa"], ["#0891b2", "#22d3ee"],
  ["#65a30d", "#a3e635"], ["#dc2626", "#f87171"],
];
const chipColor = (idx: number, dark: boolean): string =>
  PALETTE[Math.max(idx, 0) % PALETTE.length][dark ? 1 : 0];

// ---------------------------------------------------------------------------
// Filtering
// ---------------------------------------------------------------------------

export function filterCriticalPath(
  model: CriticalPathModel,
  f: CriticalFilter,
): { model: CriticalPathModel; dimmed: Set<string> } {
  const byId = new Map(model.issues.map(i => [i.id, i]));
  const closed = (id: string): boolean => byId.get(id)?.state === "closed";
  const usable = (e: { from: string; to: string; kind: string }): boolean =>
    e.kind !== "done-stub" && (f.showClosed || (!closed(e.from) && !closed(e.to)));
  const edges = model.edges.filter(usable);

  let keep = new Set<string>([
    ...model.issues.map(i => i.id),
    ...model.outside.map(o => o.id),
    ...model.connectors.map(c => c.id),
  ]);

  if (f.focusIssue !== null) {
    const seen = new Set<string>();
    if (byId.has(f.focusIssue)) {
      for (const dir of ["up", "down"] as const) {
        const todo = [f.focusIssue];
        seen.add(f.focusIssue);
        const visited = new Set(todo);
        while (todo.length) {
          const cur = todo.pop()!;
          for (const e of edges) {
            const next = dir === "up" ? (e.to === cur ? e.from : null) : (e.from === cur ? e.to : null);
            if (next === null || visited.has(next)) continue;
            visited.add(next);
            seen.add(next);
            todo.push(next);
          }
        }
      }
    }
    keep = new Set([...keep].filter(id => seen.has(id)));
  }

  const dimmed = new Set<string>();
  if (f.trackKey !== null) {
    const own = new Set(
      model.issues.filter(i => keep.has(i.id) && i.trackKey === f.trackKey).map(i => i.id),
    );
    const next = new Set(own);
    const connectorIds = new Set(model.connectors.map(c => c.id));
    for (const e of edges) {
      if (!keep.has(e.from) || !keep.has(e.to)) continue;
      if (own.has(e.to) && !own.has(e.from)) {
        next.add(e.from);
        if (byId.has(e.from) || connectorIds.has(e.from)) dimmed.add(e.from);
      }
      if (own.has(e.from) && connectorIds.has(e.to)) {
        next.add(e.to);
        dimmed.add(e.to);
      }
    }
    keep = next;
  }

  if (!f.showClosed) for (const i of model.issues) if (i.state === "closed") keep.delete(i.id);

  const stubs = f.showClosed ? [] : model.stubs.filter(s => keep.has(s.target));
  const stubTargets = new Set(stubs.map(s => `done:${s.target}`));
  const kept = {
    ...model,
    issues: model.issues.filter(i => keep.has(i.id)),
    outside: model.outside.filter(o => keep.has(o.id)),
    connectors: model.connectors.filter(c => keep.has(c.id)),
    stubs,
    edges: model.edges.filter(e => e.kind === "done-stub"
      ? stubTargets.has(e.from) && keep.has(e.to)
      : keep.has(e.from) && keep.has(e.to)),
    cycles: model.cycles.filter(c => c.members.some(m => keep.has(m))),
  };
  return { model: kept, dimmed };
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

/** Escape for a quoted label; `|` is not covered by mermaidLabel. */
const text = (s: string): string => mermaidLabel(s).replace(/\|/g, "/");

const shorten = (s: string): string => {
  const chars = [...s];
  return chars.length > MAX_TITLE ? chars.slice(0, MAX_TITLE).join("") + "…" : s;
};

const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;

function bannerText(model: CriticalPathModel): string | null {
  if (model.cycles.length === 0) return null;
  const num = (id: string): string => `#${id.slice(id.lastIndexOf("#") + 1)}`;
  const parts = model.cycles.map(c => {
    const path = [...c.members, c.members[0]].map(num).join(" → ");
    const waiting = c.waiting === 0
      ? "No other issues wait on them"
      : c.waiting === 1 ? "1 more issue waits on them" : `${c.waiting} more issues wait on them`;
    return `These block each other: ${path}. ${waiting}.`;
  });
  return `${parts.join(" ")} Fix the links on GitHub.`;
}

export function renderCriticalPath(
  full: CriticalPathModel,
  f: CriticalFilter,
  opts: { dark: boolean },
): CriticalRender {
  const { model, dimmed } = filterCriticalPath(full, f);
  const base: CriticalRender = {
    mermaid: "", edgeCount: 0, tooLarge: false, banner: null,
    legend: [], empty: null, tooLargeMessage: null,
  };

  const openCount = model.issues.filter(i => i.state === "open").length;
  if (openCount === 0) {
    const hadOpen = full.issues.some(i => i.state === "open");
    return {
      ...base,
      empty: full.repo === null
        ? "No repo selected — pick a repo to see its critical path."
        : hadOpen ? "No open issues match the current filter." : "No open issues in this repo — nothing to chart.",
    };
  }

  const order = (i: CritIssueNode): number[] => [
    -i.downstreamDepth,
    i.nextUpIndex ?? Number.MAX_SAFE_INTEGER,
    model.trackOrder.indexOf(i.trackKey) < 0 ? Number.MAX_SAFE_INTEGER : model.trackOrder.indexOf(i.trackKey),
    i.number,
  ];
  const cmp = (a: CritIssueNode, b: CritIssueNode): number => {
    const x = order(a), y = order(b);
    for (let k = 0; k < x.length; k++) if (x[k] !== y[k]) return x[k] - y[k];
    return 0;
  };

  // Ids: derived from numbers / indexes only, never from free text.
  const ids = new Map<string, string>();
  for (const i of model.issues) ids.set(i.id, `i_${i.number}`);
  model.outside.forEach((o, k) => ids.set(o.id, `o_${k}`));
  model.connectors.forEach((c, k) => ids.set(c.id, `k_${k}`));
  model.stubs.forEach((s, k) => ids.set(`done:${s.target}`, `s_${k}`));

  // Columns.
  const columns: { id: string; label: string; members: CritIssueNode[] }[] = [];
  const done = model.issues.filter(i => i.state === "closed").sort(cmp);
  if (done.length) columns.push({ id: "col_done", label: "Done", members: done });
  const open = model.issues.filter(i => i.state === "open");
  const ranks = [...new Set(open.filter(i => !i.unranked && i.rank !== null).map(i => i.rank!))]
    .sort((a, b) => a - b);
  for (const r of ranks) {
    columns.push({
      id: `col_r${r}`, label: `Rank ${r}`,
      members: open.filter(i => !i.unranked && i.rank === r).sort(cmp),
    });
  }
  const unranked = open.filter(i => i.unranked).sort(cmp);
  if (unranked.length) {
    columns.push({ id: "col_unranked", label: "Can't rank — dependency loop", members: unranked });
  }

  // Legend / chips: tracks that actually have a node on screen.
  const trackIdx = (k: TrackKey): number => model.trackOrder.indexOf(k);
  const shown = new Map<TrackKey, string>();
  for (const i of model.issues) if (!shown.has(i.trackKey)) shown.set(i.trackKey, i.trackName);
  const legendKeys = [...shown.keys()].sort((a, b) => trackIdx(a) - trackIdx(b));
  const legend = legendKeys.map(k => ({
    trackKey: k, label: shown.get(k)!, color: chipColor(trackIdx(k), opts.dark),
  }));

  const lines: string[] = ["graph LR", ...classDefLines(opts.dark)];
  const neutral = opts.dark ? "fill:#1f2937,color:#e5e7eb" : "fill:#ffffff,color:#1f2937";
  legendKeys.forEach((k, n) => {
    lines.push(`  classDef chip${n} ${neutral},stroke:${chipColor(trackIdx(k), opts.dark)},stroke-width:3px`);
  });
  lines.push("  classDef dimmed stroke-dasharray:4 3,opacity:0.55");
  lines.push("  classDef outside stroke-dasharray:2 3");

  for (const c of columns) {
    lines.push(`  subgraph ${c.id}["${text(c.label)}"]`, "    direction TB");
    for (const m of c.members) lines.push(`    ${ids.get(m.id)}`);
    lines.push("  end");
  }

  const label = (i: CritIssueNode): string => {
    const head = i.state === "closed" ? "✓" : i.unranked || i.rank === null ? "?" : String(i.rank);
    const chip = `${text(i.trackName)}${i.isRef ? " (ref)" : ""}`;
    return `${head} · #${i.number} ${text(shorten(i.title))}<br/>▪ ${chip}`;
  };
  for (const c of columns) for (const m of c.members) lines.push(`  ${ids.get(m.id)}["${label(m)}"]`);
  model.outside.forEach(o => lines.push(`  ${ids.get(o.id)}["${text(o.label)}"]`));
  model.connectors.forEach(c => lines.push(`  ${ids.get(c.id)}(["track ${text(c.dependencyTrack)} done"])`));
  model.stubs.forEach(s => lines.push(`  ${ids.get(`done:${s.target}`)}(["✓ ${s.count} done that blocked this"])`));

  const outsideIds = new Set(model.outside.map(o => o.id));
  let edgeCount = 0;
  for (const e of model.edges) {
    const a = ids.get(e.from), b = ids.get(e.to);
    if (a === undefined || b === undefined) continue;
    const arrow = e.kind === "track-dep" ? "==>" : e.kind === "done-stub" || outsideIds.has(e.from) ? "-.->" : "-->";
    lines.push(`  ${a} ${arrow} ${b}`);
    edgeCount++;
  }

  for (let k = 0; k + 1 < columns.length; k++) lines.push(`  ${columns[k].id} ~~~ ${columns[k + 1].id}`);

  legendKeys.forEach((k, n) => {
    const members = model.issues.filter(i => i.trackKey === k).map(i => ids.get(i.id)!);
    lines.push(`  class ${members.join(",")} chip${n}`);
  });
  const dimIds = [
    ...[...dimmed].map(id => ids.get(id)).filter((x): x is string => x !== undefined),
    ...(f.showClosed ? done.map(i => ids.get(i.id)!) : []),
  ].filter((x, k, a) => a.indexOf(x) === k);
  if (dimIds.length) lines.push(`  class ${dimIds.join(",")} dimmed`);
  if (model.outside.length) lines.push(`  class ${model.outside.map(o => ids.get(o.id)).join(",")} outside`);
  if (f.focusIssue !== null && ids.has(f.focusIssue)) lines.push(`  class ${ids.get(f.focusIssue)} selected`);

  const banner = bannerText(model);
  const mermaid = lines.join("\n");
  if (edgeCount > MAX_EDGES || mermaid.length > MAX_CHARS) {
    return {
      ...base, edgeCount, tooLarge: true, banner, legend,
      tooLargeMessage:
        `Too large to draw (${plural(model.issues.length, "issue", "issues")}, ` +
        `${plural(edgeCount, "link", "links")}). Filter by track or focus on an issue.`,
    };
  }
  return { ...base, mermaid, edgeCount, banner, legend };
}

// ---------------------------------------------------------------------------
// Size cap
// ---------------------------------------------------------------------------

/**
 * Render; if over the cap and no track filter is set, retry filtered to the
 * selected track and say so. Still over the cap -> tooLarge stays true.
 */
export function fitToCap(
  model: CriticalPathModel,
  f: CriticalFilter,
  selected: TrackKey,
  opts: { dark: boolean },
): { filter: CriticalFilter; render: CriticalRender; autoFiltered: string | null } {
  const first = renderCriticalPath(model, f, opts);
  if (!first.tooLarge || f.trackKey !== null) return { filter: f, render: first, autoFiltered: null };
  const filter = { ...f, trackKey: selected };
  const name = model.issues.find(i => i.trackKey === selected)?.trackName ?? selected;
  return {
    filter,
    render: renderCriticalPath(model, filter, opts),
    autoFiltered:
      `This repo is too large to draw at once (${plural(model.issues.length, "issue", "issues")}). ` +
      `Showing track ${name} — clear the filter to try another.`,
  };
}
