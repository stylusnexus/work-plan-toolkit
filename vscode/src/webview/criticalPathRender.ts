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
import type { GraphMode } from "./messages.ts";

export interface CriticalFilter {
  trackKey: TrackKey | null;
  focusIssue: string | null;
  showClosed: boolean;
  /** Draw startable issues that have no links; off collapses them into one summary node. */
  showUnlinked: boolean;
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
  /** Mermaid node id -> full hover text for every drawn issue node; {} when nothing is drawn. */
  nodeTitles: Record<string, string>;
  /** Drawn links as [from, to] Mermaid node ids, for the webview's click-to-trace; [] when nothing is drawn. */
  nodeLinks: [string, string][];
  /** Mermaid node id -> status of drawn open issues that are not startable; absent when startable, in progress or closed. */
  nodeStatus: Record<string, IssueStatus>;
  /** Open issues in the filtered set with no rank-carrying link (drawn or collapsed). */
  unlinkedCount: number;
}

/**
 * "blocked": two or more steps from startable (a blocker is itself blocked) or
 * stuck in a loop; "waiting": one step from startable. Startable, in-progress
 * and closed issues carry none.
 */
export type IssueStatus = "blocked" | "waiting";

export function issueStatus(i: Pick<CritIssueNode, "state" | "rank" | "unranked" | "inProgress">): IssueStatus | null {
  if (i.state === "closed" || i.inProgress) return null;
  if (i.unranked || i.rank === null) return "blocked";
  return i.rank >= 2 ? "blocked" : i.rank === 1 ? "waiting" : null;
}

const MAX_EDGES = 450;
const MAX_CHARS = 45_000;
const MAX_TITLE = 40;
/** Unlinked issues per row when they are shown as a grid. */
const GRID_ROW = 8;
/** Mermaid label wrapping width (px) for this view; its default 200 wraps a title into 4-5 lines. */
const WRAP_WIDTH = 400;

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

/** The sidebar lens in effect, or null when absent or every repo track is visible. */
function activeLens(
  model: CriticalPathModel,
  visibleTracks: ReadonlySet<TrackKey> | undefined,
): ReadonlySet<TrackKey> | null {
  return visibleTracks && model.trackOrder.some(k => !visibleTracks.has(k)) ? visibleTracks : null;
}

/** The lens keeps an issue when any of its member tracks is visible. */
const lensKeeps = (i: CritIssueNode, lens: ReadonlySet<TrackKey> | null): boolean =>
  lens === null || i.memberTrackKeys.some(k => lens.has(k));

/** Issues the sidebar lens keeps (all of them with no lens): picker items and the stale-focus check. */
export function lensVisibleIssues(
  model: CriticalPathModel,
  visibleTracks: ReadonlySet<TrackKey> | undefined,
): CritIssueNode[] {
  const lens = activeLens(model, visibleTracks);
  return model.issues.filter(i => lensKeeps(i, lens));
}

/**
 * Narrow the drawn graph; never re-rank. The track filter and the sidebar lens
 * (`visibleTracks`, the tracks the lens left in this repo) work the same way:
 * keep issues whose member tracks match, plus their direct blockers and
 * connectors from elsewhere, dimmed.
 */
export function filterCriticalPath(
  model: CriticalPathModel,
  f: CriticalFilter,
  visibleTracks?: ReadonlySet<TrackKey>,
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

  const lens = activeLens(model, visibleTracks);
  const dimmed = new Set<string>();
  const tk = f.trackKey;
  if (tk !== null || lens !== null) {
    const matches = (i: CritIssueNode): boolean =>
      (tk === null || i.memberTrackKeys.includes(tk)) && lensKeeps(i, lens);
    const own = new Set(model.issues.filter(i => keep.has(i.id) && matches(i)).map(i => i.id));
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
    // A connector between two kept tracks is not from elsewhere: undim it.
    for (const c of connectorIds) {
      if (edges.some(e => e.to === c && own.has(e.from)) && edges.some(e => e.from === c && own.has(e.to))) {
        dimmed.delete(c);
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

/** Rank means "steps from startable", never priority or order (spec anti-goal). */
const columnLabel = (r: number): string =>
  r === 0 ? "Startable now" : `${plural(r, "step", "steps")} from startable`;

function bannerText(model: CriticalPathModel): string | null {
  if (model.cycles.length === 0) return null;
  const num = (id: string): string => `#${id.slice(id.lastIndexOf("#") + 1)}`;
  const parts = model.cycles.map(c => {
    // Members are in export order, not path order: arrows are only honest for
    // a self-block or a two-issue loop.
    const path = c.members.length <= 2
      ? [...c.members, c.members[0]].map(num).join(" → ")
      : c.members.map(num).join(", ");
    const waiting = c.waiting === 0
      ? "No other issues wait on them"
      : c.waiting === 1 ? "1 more issue waits on them" : `${c.waiting} more issues wait on them`;
    return `These block each other: ${path}. ${waiting}.`;
  });
  return `${parts.join(" ")} Fix the links on GitHub.`;
}

/**
 * Issues (and connectors / outside nodes) on a rank-carrying edge of the full
 * model: an open-to-open or outside-to-open `blocks` edge, or a track-dependency
 * edge. A done stub or a closed issue's display edge does not count: neither
 * affects rank, so an issue with only those is still startable with no links.
 */
function linkedIds(full: CriticalPathModel): Set<string> {
  const open = new Set(full.issues.filter(i => i.state === "open").map(i => i.id));
  const outside = new Set(full.outside.map(o => o.id));
  const linked = new Set<string>();
  for (const e of full.edges) {
    const rankEdge = e.kind === "track-dep" ||
      (e.kind === "blocks" && (open.has(e.from) || outside.has(e.from)) && open.has(e.to));
    if (rankEdge) { linked.add(e.from); linked.add(e.to); }
  }
  return linked;
}

/** Tracks the sidebar lens leaves visible, in export order (the track dropdown). */
export function visibleTrackOrder(
  model: CriticalPathModel,
  visibleTracks: ReadonlySet<TrackKey> | undefined,
): TrackKey[] {
  return visibleTracks ? model.trackOrder.filter(k => visibleTracks.has(k)) : [...model.trackOrder];
}

export function renderCriticalPath(
  full: CriticalPathModel,
  f: CriticalFilter,
  opts: { dark: boolean; visibleTracks?: ReadonlySet<TrackKey> },
): CriticalRender {
  const filtered = filterCriticalPath(full, f, opts.visibleTracks);
  const { dimmed } = filtered;
  const base: CriticalRender = {
    mermaid: "", edgeCount: 0, tooLarge: false, banner: null,
    legend: [], empty: null, tooLargeMessage: null, nodeTitles: {}, nodeLinks: [], nodeStatus: {}, unlinkedCount: 0,
  };
  let model = filtered.model;

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

  // Unlinked: open, rank 0 by definition, no rank-carrying link in the full
  // model. Collapsed after filtering, display only (ranks never change). The
  // focused issue is never collapsed.
  const linked = linkedIds(full);
  const unlinked = model.issues.filter(i =>
    i.state === "open" && !i.unranked && !linked.has(i.id) && i.id !== f.focusIssue);
  const unlinkedIds = new Set(unlinked.map(i => i.id));
  const hiddenCount = f.showUnlinked ? 0 : unlinked.length;
  if (hiddenCount > 0) {
    model = {
      ...model,
      issues: model.issues.filter(i => !unlinkedIds.has(i.id)),
      stubs: model.stubs.filter(s => !unlinkedIds.has(s.target)),
      edges: model.edges.filter(e => !unlinkedIds.has(e.to) && !unlinkedIds.has(e.from)),
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

  // Rank columns hold linked issues only. Collapsed unlinked issues become one
  // summary node in "Startable now". Shown ones go in their own block as a
  // wrapped grid: inside a column Mermaid stacks them into one tall strip, so
  // each row is chained with invisible links to lay it out across instead.
  const columns: { id: string; label: string; members: CritIssueNode[] }[] = [];
  const done = model.issues.filter(i => i.state === "closed").sort(cmp);
  if (done.length) columns.push({ id: "col_done", label: "Done", members: done });
  const open = model.issues.filter(i => i.state === "open");
  const grid = f.showUnlinked ? open.filter(i => unlinkedIds.has(i.id)).sort(cmp) : [];
  const rows: CritIssueNode[][] = [];
  for (let k = 0; k < grid.length; k += GRID_ROW) rows.push(grid.slice(k, k + GRID_ROW));
  const rankSet = new Set(open.filter(i => !i.unranked && i.rank !== null).map(i => i.rank!));
  const ranks = [...rankSet].sort((a, b) => a - b);
  if (hiddenCount > 0 && !rankSet.has(0)) ranks.unshift(0);
  for (const r of ranks) {
    const members = open.filter(i => !i.unranked && i.rank === r && !unlinkedIds.has(i.id)).sort(cmp);
    if (members.length === 0 && !(r === 0 && hiddenCount > 0)) continue;
    columns.push({ id: `col_r${r}`, label: columnLabel(r), members });
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

  // Wider label wrapping: a shortened title fits on one line, so nodes are
  // short and a column of them stays compact.
  const lines: string[] = [
    `%%{init: {"flowchart": {"wrappingWidth": ${WRAP_WIDTH}}}}%%`, "graph LR", ...classDefLines(opts.dark),
  ];
  const neutral = opts.dark ? "fill:#1f2937,color:#e5e7eb" : "fill:#ffffff,color:#1f2937";
  legendKeys.forEach((k, n) => {
    lines.push(`  classDef chip${n} ${neutral},stroke:${chipColor(trackIdx(k), opts.dark)},stroke-width:3px`);
  });
  // Status tints the fill only: the stroke stays the track colour.
  lines.push(opts.dark
    ? "  classDef statBlocked fill:#5b1d1d,color:#fecaca"
    : "  classDef statBlocked fill:#fee2e2,color:#7f1d1d");
  lines.push(opts.dark
    ? "  classDef statWaiting fill:#4d3a06,color:#fde68a"
    : "  classDef statWaiting fill:#fef3c7,color:#78350f");
  lines.push("  classDef dimmed stroke-dasharray:4 3,opacity:0.55");
  lines.push("  classDef outside stroke-dasharray:2 3");

  const SUMMARY = "u_hidden";
  for (const c of columns) {
    lines.push(`  subgraph ${c.id}["${text(c.label)}"]`, "    direction TB");
    for (const m of c.members) lines.push(`    ${ids.get(m.id)}`);
    if (c.id === "col_r0" && hiddenCount > 0) lines.push(`    ${SUMMARY}`);
    lines.push("  end");
  }
  const GRID = "col_unlinked";
  if (grid.length) {
    lines.push(`  subgraph ${GRID}["${text(`Startable now — no links (${grid.length})`)}"]`, "    direction LR");
    for (const m of grid) lines.push(`    ${ids.get(m.id)}`);
    lines.push("  end");
  }
  const drawnIssues = [...columns.flatMap(c => c.members), ...grid];

  const label = (i: CritIssueNode): string => {
    const head = i.state === "closed" ? "✓" : i.unranked || i.rank === null ? "?" : String(i.rank);
    const chip = `${i.trackBlocked ? "⛔ " : ""}${text(i.trackName)}${i.isRef ? " (ref)" : ""}`;
    const st = issueStatus(i);
    return `${head}${st === "blocked" ? " ⛔" : st === "waiting" ? " ⏳" : ""} · #${i.number} ${text(shorten(i.title))}<br/>▪ ${chip}`;
  };
  for (const m of drawnIssues) lines.push(`  ${ids.get(m.id)}["${label(m)}"]`);
  if (hiddenCount > 0) {
    lines.push(`  ${SUMMARY}(["${plural(hiddenCount, "startable issue", "startable issues")} with no links (hidden)"])`);
  }
  model.outside.forEach(o => lines.push(`  ${ids.get(o.id)}["${text(o.label)}"]`));
  model.connectors.forEach(c => lines.push(`  ${ids.get(c.id)}(["track ${text(c.dependencyTrack)} done"])`));
  model.stubs.forEach(s => lines.push(`  ${ids.get(`done:${s.target}`)}(["✓ ${s.count} done that blocked this"])`));

  const outsideIds = new Set(model.outside.map(o => o.id));
  let edgeCount = 0;
  const nodeLinks: [string, string][] = [];
  for (const e of model.edges) {
    const a = ids.get(e.from), b = ids.get(e.to);
    if (a === undefined || b === undefined) continue;
    nodeLinks.push([a, b]);
    const arrow = e.kind === "track-dep" ? "==>" : e.kind === "done-stub" || outsideIds.has(e.from) ? "-.->" : "-->";
    lines.push(`  ${a} ${arrow} ${b}`);
    edgeCount++;
  }

  // Mermaid's edge limit counts these invisible links too.
  for (let k = 0; k + 1 < columns.length; k++) lines.push(`  ${columns[k].id} ~~~ ${columns[k + 1].id}`);
  edgeCount += Math.max(columns.length - 1, 0);
  for (const row of rows) {
    if (row.length > 1) lines.push(`  ${row.map(m => ids.get(m.id)).join(" ~~~ ")}`);
    edgeCount += row.length - 1;
  }

  legendKeys.forEach((k, n) => {
    const members = model.issues.filter(i => i.trackKey === k).map(i => ids.get(i.id)!);
    lines.push(`  class ${members.join(",")} chip${n}`);
  });
  for (const st of ["blocked", "waiting"] as const) {
    const members = drawnIssues.filter(m => issueStatus(m) === st).map(m => ids.get(m.id)!);
    if (members.length) lines.push(`  class ${members.join(",")} ${st === "blocked" ? "statBlocked" : "statWaiting"}`);
  }
  const dimIds = [
    ...[...dimmed].map(id => ids.get(id)).filter((x): x is string => x !== undefined),
    ...(f.showClosed ? done.map(i => ids.get(i.id)!) : []),
  ].filter((x, k, a) => a.indexOf(x) === k);
  if (hiddenCount > 0) dimIds.push(SUMMARY);
  if (dimIds.length) lines.push(`  class ${dimIds.join(",")} dimmed`);
  if (model.outside.length) lines.push(`  class ${model.outside.map(o => ids.get(o.id)).join(",")} outside`);
  if (f.focusIssue !== null && ids.has(f.focusIssue)) lines.push(`  class ${ids.get(f.focusIssue)} selected`);

  const banner = bannerText(model);
  const mermaid = lines.join("\n");
  if (edgeCount > MAX_EDGES || mermaid.length > MAX_CHARS) {
    return {
      ...base, edgeCount, tooLarge: true, banner, legend, unlinkedCount: unlinked.length,
      tooLargeMessage:
        `Too large to draw (${plural(model.issues.length, "issue", "issues")}, ` +
        `${plural(edgeCount, "link", "links")}). Filter by track or focus on an issue.`,
    };
  }
  // Labels are shortened; the hover text carries the full title (raw text: the
  // webview sets it with textContent).
  const nodeTitles: Record<string, string> = {};
  {
    for (const m of drawnIssues) {
      const track = `${m.trackName}${m.isRef ? " (ref)" : ""}${m.trackBlocked ? " ⛔" : ""}`;
      const state = m.state === "closed" ? "closed" : m.inProgress ? "open, in progress" : "open";
      nodeTitles[ids.get(m.id)!] = `#${m.number} ${m.title}\nTrack: ${track}\nState: ${state}`;
    }
  }
  const nodeStatus: Record<string, IssueStatus> = {};
  for (const m of drawnIssues) {
    const st = issueStatus(m);
    if (st) nodeStatus[ids.get(m.id)!] = st;
  }
  return { ...base, mermaid, edgeCount, banner, legend, nodeTitles, nodeLinks, nodeStatus, unlinkedCount: unlinked.length };
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
  opts: {
    dark: boolean; suppressAutoFit?: boolean; visibleTracks?: ReadonlySet<TrackKey>;
    /** Display name of `selected` for the auto-fit note. */
    selectedName?: string;
  },
): { filter: CriticalFilter; render: CriticalRender; autoFiltered: string | null } {
  const first = renderCriticalPath(model, f, opts);
  if (!first.tooLarge || f.trackKey !== null || opts.suppressAutoFit) return { filter: f, render: first, autoFiltered: null };
  const filter = { ...f, trackKey: selected };
  const name = opts.selectedName ?? model.issues.find(i => i.trackKey === selected)?.trackName ?? selected;
  return {
    filter,
    render: renderCriticalPath(model, filter, opts),
    autoFiltered:
      `This repo is too large to draw at once (${plural(model.issues.length, "issue", "issues")}). ` +
      `Showing track ${name} — clear the filter to try another.`,
  };
}

// ---------------------------------------------------------------------------
// View state transitions (kept pure so panel.ts stays glue-only)
// ---------------------------------------------------------------------------

export interface CritState {
  mode: GraphMode;
  filter: CriticalFilter;
  repo: string | null;
  /** True once the user explicitly cleared the track filter: skip auto-fit so the too-large message shows. */
  autoFitSuppressed?: boolean;
}

export type CritEvent =
  | { type: "selectTrack"; repo: string | null }
  | {
      type: "refresh"; knownTracks: TrackKey[]; knownIssues: string[];
      /** Still in the data but hidden by the sidebar lens: changes the note, not the clearing. */
      hiddenTracks?: TrackKey[]; hiddenIssues?: string[];
    }
  | { type: "setMode"; mode: GraphMode }
  | { type: "setTrackFilter"; key: TrackKey | null }
  | { type: "autoFit"; trackKey: TrackKey }
  | { type: "setShowClosed"; show: boolean }
  | { type: "setShowUnlinked"; show: boolean }
  | { type: "setFocusIssue"; id: string | null };

/**
 * Next view state after a track selection, mode change, filter edit or data
 * refresh. Selecting in "full" resets to "focus" (today's behaviour); "critical"
 * survives. A new repo clears the track and issue filters (showClosed stays) and
 * the auto-fit suppression. A refresh clears any filter whose target vanished and
 * says so in `note`. An explicit track-filter clear sets autoFitSuppressed; any
 * mode change or repo change resets it so auto-fit works on a fresh open.
 */
export function nextCritState(
  prev: CritState,
  ev: CritEvent,
): Required<CritState> & { note: string | null } {
  const sup = prev.autoFitSuppressed ?? false;
  const out = (p: Partial<CritState>, note: string | null = null) => ({
    mode: prev.mode, filter: prev.filter, repo: prev.repo, autoFitSuppressed: sup, ...p, note,
  });
  switch (ev.type) {
    case "selectTrack": {
      const mode: GraphMode = prev.mode === "full" ? "focus" : prev.mode;
      if (ev.repo === prev.repo) return out({ mode });
      return out({
        mode, repo: ev.repo, autoFitSuppressed: false,
        filter: { ...prev.filter, trackKey: null, focusIssue: null },
      });
    }
    case "setMode":
      return out({ mode: ev.mode, autoFitSuppressed: false });
    case "setTrackFilter":
      return out({ filter: { ...prev.filter, trackKey: ev.key }, autoFitSuppressed: ev.key === null });
    case "autoFit":
      return out({ filter: { ...prev.filter, trackKey: ev.trackKey } });
    case "setShowClosed":
      return out({ filter: { ...prev.filter, showClosed: ev.show } });
    case "setShowUnlinked":
      return out({ filter: { ...prev.filter, showUnlinked: ev.show } });
    case "setFocusIssue":
      return out({ filter: { ...prev.filter, focusIssue: ev.id } });
    case "refresh": {
      let filter = prev.filter;
      const notes: string[] = [];
      if (filter.trackKey !== null && !ev.knownTracks.includes(filter.trackKey)) {
        const hidden = ev.hiddenTracks?.includes(filter.trackKey) ?? false;
        filter = { ...filter, trackKey: null };
        notes.push(hidden
          ? "The filtered track is hidden by the sidebar filter; showing all tracks."
          : "The filtered track no longer exists; showing all tracks.");
      }
      if (filter.focusIssue !== null && !ev.knownIssues.includes(filter.focusIssue)) {
        const hidden = ev.hiddenIssues?.includes(filter.focusIssue) ?? false;
        filter = { ...filter, focusIssue: null };
        notes.push(hidden
          ? "The focused issue is hidden by the sidebar filter; focus cleared."
          : "The focused issue no longer exists; focus cleared.");
      }
      return out({ filter }, notes.length ? notes.join(" ") : null);
    }
  }
}
