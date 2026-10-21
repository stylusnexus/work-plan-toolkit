/**
 * Pure critical-path rank engine (#445) over a work-plan Export.
 *
 * Rank = steps in the longest chain of open hard blockers behind an issue
 * (issue `blocked_by` links plus track `depends_on`). No vscode imports.
 * No Date / Math.random — output is fully deterministic.
 */

import type { Export, Issue, Track, TrackKey } from "../model.ts";
import { trackKey } from "../model.ts";

export interface CritIssueNode {
  id: string;                 // `${repo}#${number}`
  repo: string; number: number; title: string;
  state: "open" | "closed";
  trackKey: TrackKey; trackName: string; isRef: boolean; // chip: owner, or first referencer with isRef
  rank: number | null;        // null for closed and for unranked
  unranked: boolean;          // in or downstream of a cycle
  inProgress: boolean;
  downstreamDepth: number;    // longest open chain after this issue
  nextUpIndex: number | null; // position in its track's next_up
}
export interface CritOutsideNode { id: string; label: string }          // `repo#N` or `#N untracked`
export interface CritConnector { id: string; dependencyTrack: string; dependentTrack: string }
export interface CritEdge { from: string; to: string; kind: "blocks" | "track-dep" | "done-stub" }
export interface CritStub { target: string; count: number }
export interface CritCycle { members: string[]; waiting: number }
export interface CriticalPathModel {
  repo: string | null;
  issues: CritIssueNode[]; outside: CritOutsideNode[]; connectors: CritConnector[];
  edges: CritEdge[]; stubs: CritStub[]; cycles: CritCycle[];
  notes: string[];            // e.g. missing dependency track
  trackOrder: TrackKey[];
}

/** Same check as next_up.py's blocked_by gate: open and no open blockers. */
export function nextUpGateAllows(issue: Issue): boolean {
  return issue.state === "open" && issue.blocked_by.length === 0;
}

export function criticalPickItems(
  model: CriticalPathModel,
): { label: string; description?: string; id: string }[] {
  return model.issues.map(n => ({
    label: `#${n.number} ${n.title}`,
    description: n.state === "closed" ? `${n.trackName} · closed` : n.trackName,
    id: n.id,
  }));
}

function emptyModel(repo: string | null): CriticalPathModel {
  return {
    repo, issues: [], outside: [], connectors: [], edges: [],
    stubs: [], cycles: [], notes: [], trackOrder: [],
  };
}

export function computeCriticalPath(exp: Export, repo: string | null): CriticalPathModel {
  const model = emptyModel(repo);
  if (repo === null) return model;

  const scope = exp.tracks.filter(t => t.repo === repo);
  model.trackOrder = scope.map(t => trackKey(t));

  // --- Nodes: owned issues first, then references; first wins. -------------
  const nodes = new Map<string, CritIssueNode>();
  const issueById = new Map<string, Issue>();
  const add = (t: Track, issue: Issue, isRef: boolean): void => {
    const id = `${repo}#${issue.number}`;
    if (nodes.has(id)) return;
    const idx = t.next_up.indexOf(issue.number);
    nodes.set(id, {
      id, repo, number: issue.number, title: issue.title, state: issue.state,
      trackKey: trackKey(t), trackName: t.name, isRef,
      rank: null, unranked: false, inProgress: issue.in_progress,
      downstreamDepth: 0, nextUpIndex: idx >= 0 ? idx : null,
    });
    issueById.set(id, issue);
  };
  for (const t of scope) for (const i of t.issues) add(t, i, false);
  for (const t of scope) for (const i of t.references ?? []) add(t, i, true);
  const isOpen = (id: string): boolean => nodes.get(id)?.state === "open";

  // preds: blocker -> dependent edges stored as dependent -> blockers.
  const preds = new Map<string, Set<string>>();
  const succs = new Map<string, Set<string>>();
  const link = (from: string, to: string): void => {
    if (!preds.has(to)) preds.set(to, new Set());
    if (!succs.has(from)) succs.set(from, new Set());
    preds.get(to)!.add(from);
    succs.get(from)!.add(to);
  };
  const edgeSeen = new Set<string>();
  const pushEdge = (from: string, to: string, kind: CritEdge["kind"]): void => {
    const k = `${from}\u0000${to}\u0000${kind}`;
    if (edgeSeen.has(k)) return;
    edgeSeen.add(k);
    model.edges.push({ from, to, kind });
  };

  // --- Issue-level edges and outside nodes. --------------------------------
  const outsideIds = new Set<string>();
  for (const [id, node] of nodes) {
    if (node.state !== "open") continue;
    for (const b of issueById.get(id)!.blocked_by) {
      const bid = `${b.repo}#${b.number}`;
      if (nodes.has(bid)) {
        if (!isOpen(bid)) continue; // a closed blocker never blocks
      } else if (!outsideIds.has(bid)) {
        outsideIds.add(bid);
        model.outside.push({
          id: bid, label: b.repo === repo ? `#${b.number} untracked` : bid,
        });
      }
      link(bid, id);
      pushEdge(bid, id, "blocks");
    }
  }

  // --- Done stubs: closed in-scope issues whose `blocking` names an open one.
  const stubCount = new Map<string, number>();
  for (const [id, node] of nodes) {
    if (node.state !== "closed") continue;
    const seen = new Set<string>();
    for (const b of issueById.get(id)!.blocking) {
      const tid = `${b.repo}#${b.number}`;
      if (seen.has(tid) || !isOpen(tid)) continue;
      seen.add(tid);
      // Display-only: closed issues never feed rank, cycles or depth (no link()).
      pushEdge(id, tid, "blocks");
      stubCount.set(tid, (stubCount.get(tid) ?? 0) + 1);
    }
  }
  for (const [target, count] of stubCount) {
    model.stubs.push({ target, count });
    pushEdge(`done:${target}`, target, "done-stub");
  }

  // --- Track-level edges via connectors. -----------------------------------
  const ownedOpen = (t: Track): string[] =>
    t.issues.filter(i => isOpen(`${repo}#${i.number}`)).map(i => `${repo}#${i.number}`);
  const connectorIds: string[] = [];
  for (const t of scope) {
    for (const depName of t.depends_on) {
      const d = scope.find(x => x.name === depName);
      if (!d) {
        model.notes.push(`${t.name} depends on ${depName}, which isn't in this repo's data — not counted.`);
        continue;
      }
      if (d === t) continue;
      const dOpen = ownedOpen(d);
      if (dOpen.length === 0) continue; // met
      const dSet = new Set(dOpen);
      const waitedOn = new Set<string>();
      for (const id of dOpen) {
        for (const p of preds.get(id) ?? []) if (dSet.has(p)) waitedOn.add(p);
      }
      const ends = dOpen.filter(id => !waitedOn.has(id));
      const tOpen = ownedOpen(t);
      const tSet = new Set(tOpen);
      const starts = tOpen.filter(id => ![...(preds.get(id) ?? [])].some(p => tSet.has(p)));
      const cid = `track:${d.name}>${t.name}`;
      model.connectors.push({ id: cid, dependencyTrack: d.name, dependentTrack: t.name });
      connectorIds.push(cid);
      for (const e of ends) { link(e, cid); pushEdge(e, cid, "track-dep"); }
      for (const s of starts) { link(cid, s); pushEdge(cid, s, "track-dep"); }
    }
  }

  // --- Cycles: Tarjan SCC over open issues, outside nodes and connectors. --
  const openIds = [...nodes.keys()].filter(isOpen);
  const all = [...openIds, ...outsideIds, ...connectorIds];
  const index = new Map<string, number>();
  const low = new Map<string, number>();
  const onStack = new Set<string>();
  const stack: string[] = [];
  const sccs: string[][] = [];
  let counter = 0;
  const strong = (v: string): void => {
    index.set(v, counter); low.set(v, counter); counter++;
    stack.push(v); onStack.add(v);
    for (const w of succs.get(v) ?? []) {
      if (!index.has(w)) { strong(w); low.set(v, Math.min(low.get(v)!, low.get(w)!)); }
      else if (onStack.has(w)) low.set(v, Math.min(low.get(v)!, index.get(w)!));
    }
    if (low.get(v) === index.get(v)) {
      const comp: string[] = [];
      let w: string;
      do { w = stack.pop()!; onStack.delete(w); comp.push(w); } while (w !== v);
      sccs.push(comp);
    }
  };
  for (const v of all) if (!index.has(v)) strong(v);

  const order = new Map(openIds.map((id, i) => [id, i] as const));
  const cycleSets: Set<string>[] = [];
  for (const comp of sccs) {
    const selfLoop = comp.length === 1 && (succs.get(comp[0])?.has(comp[0]) ?? false);
    if (comp.length < 2 && !selfLoop) continue;
    const members = comp.filter(id => nodes.has(id)).sort((a, b) => order.get(a)! - order.get(b)!);
    if (members.length === 0) continue;
    cycleSets.push(new Set(comp));
    model.cycles.push({ members, waiting: 0 });
  }
  model.cycles.sort((a, b) => order.get(a.members[0])! - order.get(b.members[0])!);

  const downstreamOf = (starts: Iterable<string>): Set<string> => {
    const seen = new Set<string>(starts);
    const todo = [...seen];
    while (todo.length) {
      for (const w of succs.get(todo.pop()!) ?? []) {
        if (!seen.has(w)) { seen.add(w); todo.push(w); }
      }
    }
    return seen;
  };
  const unranked = new Set<string>();
  for (const cyc of model.cycles) {
    const reach = downstreamOf(cyc.members);
    const own = new Set(cyc.members);
    cyc.waiting = [...reach].filter(id => nodes.has(id) && !own.has(id)).length;
    for (const id of reach) unranked.add(id);
  }

  // --- Rank: longest chain, Kahn order over the ranked (acyclic) part. -----
  const value = new Map<string, number>(); // outside nodes are 0
  const live = all.filter(id => !unranked.has(id));
  const indeg = new Map<string, number>();
  for (const id of live) {
    indeg.set(id, [...(preds.get(id) ?? [])].filter(p => !unranked.has(p)).length);
  }
  const topo: string[] = [];
  const queue = live.filter(id => indeg.get(id) === 0);
  while (queue.length) {
    const v = queue.shift()!;
    topo.push(v);
    for (const w of succs.get(v) ?? []) {
      if (unranked.has(w)) continue;
      indeg.set(w, indeg.get(w)! - 1);
      if (indeg.get(w) === 0) queue.push(w);
    }
  }
  const isConnector = (id: string): boolean => id.startsWith("track:") && !nodes.has(id);
  for (const v of topo) {
    const ps = [...(preds.get(v) ?? [])];
    if (ps.length === 0) { value.set(v, 0); continue; }
    const best = Math.max(...ps.map(p => value.get(p)!));
    // A connector carries its dependency's highest rank; it adds no step itself.
    value.set(v, isConnector(v) ? best : best + 1);
  }
  const depth = new Map<string, number>();
  for (const v of [...topo].reverse()) {
    let d = 0;
    for (const w of succs.get(v) ?? []) {
      if (unranked.has(w)) continue;
      d = Math.max(d, (isConnector(w) ? 0 : 1) + depth.get(w)!);
    }
    depth.set(v, d);
  }

  for (const [id, node] of nodes) {
    if (node.state === "closed") continue;
    if (unranked.has(id)) { node.unranked = true; continue; }
    node.rank = value.get(id) ?? 0;
    node.downstreamDepth = depth.get(id) ?? 0;
  }
  model.issues = [...nodes.values()];
  return model;
}
