import { describe, it } from "node:test";
import assert from "node:assert/strict";
import type { TrackKey } from "../model.ts";
import type { CritIssueNode, CriticalPathModel } from "./criticalPath.ts";
import { computeRollup } from "./rollup.ts";

const R = "r";
const TA = "ta" as TrackKey;
const TB = "tb" as TrackKey;
const node = (number: number, rank: number | null, extra: Partial<CritIssueNode> = {}): CritIssueNode => ({
  id: `${R}#${number}`, repo: R, number, title: `issue ${number}`,
  state: "open", trackKey: TA, trackName: "Alpha", isRef: false,
  memberTrackKeys: [extra.trackKey ?? TA], trackBlocked: false,
  rank, unranked: rank === null, inProgress: false, inReview: false, assignee: "—", milestone: null,
  downstreamDepth: 0, nextUpIndex: null, ...extra,
});
const model = (issues: CritIssueNode[], edges: [number, number][] = []): CriticalPathModel => ({
  repo: R, issues, outside: [], connectors: [],
  edges: edges.map(([a, b]) => ({ from: `${R}#${a}`, to: `${R}#${b}`, kind: "blocks" as const })),
  stubs: [], cycles: [], notes: [], trackOrder: [TA, TB],
});
const closed = (n: number, extra: Partial<CritIssueNode> = {}) =>
  node(n, null, { state: "closed", unranked: false, ...extra });

describe("computeRollup", () => {
  it("counts open and closed per track", () => {
    const r = computeRollup(model([closed(1), closed(2), closed(3), node(4, 0)]));
    assert.deepEqual([r.tracks[0].closed, r.tracks[0].open], [3, 1]);
    assert.equal(r.tracks[0].label, "Alpha");
  });

  it("startable, waiting and blocked follow the graph marks", () => {
    // #1 startable, #2 one step, #3 two steps, #4 in a loop, #5 in progress at rank 2.
    const r = computeRollup(model([
      node(1, 0), node(2, 1), node(3, 2), node(4, null), node(5, 2, { inProgress: true }),
    ]));
    const t = r.tracks[0];
    assert.deepEqual([t.startable, t.inProgress, t.waiting, t.blocked], [1, 1, 1, 2]);
    assert.equal(t.startable + t.inProgress + t.waiting + t.blocked, t.open);
  });

  it("next startable: rank 0, not started, graph work order, at most 3", () => {
    const r = computeRollup(model([
      node(1, 0, { downstreamDepth: 0 }),
      node(2, 0, { downstreamDepth: 3 }),
      node(3, 0, { downstreamDepth: 1 }),
      node(4, 0, { downstreamDepth: 1, nextUpIndex: 0 }),
      node(5, 0, { inProgress: true, downstreamDepth: 9 }),
      node(6, 1),
    ]));
    assert.deepEqual(r.tracks[0].next.map(n => n.number), [2, 4, 3]);
  });

  it("gating: the issues holding up the most other open work", () => {
    // 1 -> 2 -> 3 and 1 -> 4: #1 holds up three, #2 holds up one. Closed #9 is never counted.
    const r = computeRollup(model(
      [node(1, 0), node(2, 1), node(3, 2), node(4, 1), closed(9)],
      [[1, 2], [2, 3], [1, 4], [9, 4]],
    ));
    assert.deepEqual(r.tracks[0].gating, [
      { number: 1, title: "issue 1", blocks: 3 },
      { number: 2, title: "issue 2", blocks: 1 },
    ]);
  });

  it("a referenced issue is counted under its owning track only", () => {
    const r = computeRollup(model([
      node(1, 0), node(2, 0, { trackKey: TB, trackName: "Beta", isRef: true }),
    ]));
    assert.deepEqual(r.tracks.map(t => [t.label, t.open]), [["Alpha", 1]]);
  });

  it("the sidebar lens narrows tracks and milestones alike", () => {
    const m = model([node(1, 0, { milestone: "v1" }), node(2, 0, { trackKey: TB, trackName: "Beta", milestone: "v1" })]);
    const r = computeRollup(m, new Set([TB]));
    assert.deepEqual(r.tracks.map(t => t.label), ["Beta"]);
    assert.equal(r.milestones[0].open, 1);
  });

  it("milestones sort numerically: v2 before v10", () => {
    const r = computeRollup(model([
      node(1, 0, { milestone: "v10" }), node(2, 0, { milestone: "v2" }),
    ]));
    assert.deepEqual(r.milestones.map(x => x.label), ["v2", "v10"]);
  });

  it("milestones: sorted, with No milestone last", () => {
    const r = computeRollup(model([
      node(1, 0), node(2, 0, { milestone: "v2" }), node(3, 0, { milestone: "v1" }), closed(4, { milestone: "v1" }),
    ]));
    assert.deepEqual(r.milestones.map(m => [m.label, m.open, m.closed]),
      [["v1", 1, 1], ["v2", 1, 0], ["No milestone", 1, 0]]);
  });

  it("nothing to summarise", () => {
    assert.deepEqual(computeRollup(model([])), { tracks: [], milestones: [] });
  });
});
