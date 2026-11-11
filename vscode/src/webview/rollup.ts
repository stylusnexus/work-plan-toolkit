/**
 * Roll-up summary per track and per milestone (#557), derived from the
 * critical-path model — no new CLI data. Pure: no vscode imports.
 *
 * Counts follow the graph's marks (`issueStatus`): waiting is one step from
 * startable, blocked is two or more steps or in a loop. An issue already in
 * progress is counted on its own, so startable + inProgress + waiting + blocked
 * always equals open.
 */

import type { TrackKey } from "../model.ts";
import type { CritIssueNode, CriticalPathModel } from "./criticalPath.ts";
import { issueStatus } from "./criticalPathRender.ts";

export interface RollupIssueRef { number: number; title: string }
export interface RollupRow {
  /** Track name or milestone label (or "No milestone"). */
  label: string;
  open: number;
  closed: number;
  /** Open, not started, and nothing in the way. */
  startable: number;
  inProgress: number;
  waiting: number;
  blocked: number;
  /** Next issues to start, in the graph's work order. */
  next: RollupIssueRef[];
  /** Issues that hold up the most other open work, with how many they hold up. */
  gating: (RollupIssueRef & { blocks: number })[];
}
export interface Rollup { tracks: RollupRow[]; milestones: RollupRow[] }

/** Most issues listed under "next" and "gating" for one row. */
const TOP = 3;
export const NO_MILESTONE_LABEL = "No milestone";

/** Open issues that wait, directly or not, on each open issue. */
function dependentCounts(model: CriticalPathModel): Map<string, number> {
  const open = new Set(model.issues.filter(i => i.state === "open").map(i => i.id));
  const succ = new Map<string, string[]>();
  for (const e of model.edges) {
    if (e.kind === "done-stub") continue;
    (succ.get(e.from) ?? succ.set(e.from, []).get(e.from)!).push(e.to);
  }
  const out = new Map<string, number>();
  for (const id of open) {
    const seen = new Set<string>([id]);
    const todo = [id];
    while (todo.length) {
      for (const next of succ.get(todo.pop()!) ?? []) {
        if (!seen.has(next)) { seen.add(next); todo.push(next); }
      }
    }
    let n = 0;
    for (const s of seen) if (s !== id && open.has(s)) n++;
    out.set(id, n);
  }
  return out;
}

function row(
  label: string,
  issues: CritIssueNode[],
  cmp: (a: CritIssueNode, b: CritIssueNode) => number,
  blocks: Map<string, number>,
): RollupRow {
  const open = issues.filter(i => i.state === "open");
  const status = (i: CritIssueNode) => issueStatus(i);
  const waiting = open.filter(i => status(i) === "waiting").length;
  const blocked = open.filter(i => status(i) === "blocked").length;
  const inProgress = open.filter(i => i.inProgress).length;
  const next = open
    .filter(i => !i.unranked && i.rank === 0 && !i.inProgress)
    .sort(cmp).slice(0, TOP).map(i => ({ number: i.number, title: i.title }));
  const gating = open
    .filter(i => (blocks.get(i.id) ?? 0) > 0)
    .sort((a, b) => (blocks.get(b.id)! - blocks.get(a.id)!) || a.number - b.number)
    .slice(0, TOP).map(i => ({ number: i.number, title: i.title, blocks: blocks.get(i.id)! }));
  return {
    label, open: open.length, closed: issues.length - open.length,
    startable: open.length - waiting - blocked - inProgress, inProgress, waiting, blocked, next, gating,
  };
}

export function computeRollup(
  model: CriticalPathModel,
  visibleTracks?: ReadonlySet<TrackKey>,
): Rollup {
  const blocks = dependentCounts(model);
  const trackIdx = (k: TrackKey): number => model.trackOrder.indexOf(k);
  // The graph's work order: longest chain after, next-up position, track, number.
  const key = (i: CritIssueNode): number[] => [
    -i.downstreamDepth, i.nextUpIndex ?? Number.MAX_SAFE_INTEGER,
    trackIdx(i.trackKey) < 0 ? Number.MAX_SAFE_INTEGER : trackIdx(i.trackKey), i.number,
  ];
  const cmp = (a: CritIssueNode, b: CritIssueNode): number => {
    const x = key(a), y = key(b);
    for (let k = 0; k < x.length; k++) if (x[k] !== y[k]) return x[k] - y[k];
    return 0;
  };

  // A referenced issue belongs to its owning track only, so it is counted once.
  const tracks = model.trackOrder
    .filter(k => !visibleTracks || visibleTracks.has(k))
    .map(k => ({ k, own: model.issues.filter(i => i.trackKey === k && !i.isRef) }))
    .filter(t => t.own.length > 0)
    .map(t => row(model.issues.find(i => i.trackKey === t.k)!.trackName, t.own, cmp, blocks));

  // Milestones follow the same sidebar lens as tracks, so the two tables agree.
  const inLens = (i: CritIssueNode): boolean =>
    !visibleTracks || i.memberTrackKeys.some(k => visibleTracks.has(k));
  const scoped = model.issues.filter(inLens);
  const labels = [...new Set(scoped.map(i => i.milestone))];
  const milestones = labels
    .sort((a, b) => (a === null ? 1 : b === null ? -1 : a.localeCompare(b, undefined, { numeric: true })))
    .map(m => row(m ?? NO_MILESTONE_LABEL, scoped.filter(i => i.milestone === m), cmp, blocks));

  return { tracks, milestones };
}
