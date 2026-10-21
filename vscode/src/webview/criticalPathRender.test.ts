import { describe, it } from "node:test";
import assert from "node:assert/strict";
import type { TrackKey } from "../model.ts";
import type { CritIssueNode, CriticalPathModel } from "./criticalPath.ts";
import { filterCriticalPath, fitToCap, renderCriticalPath } from "./criticalPathRender.ts";

const R = "r";
const TA = "ta" as TrackKey;
const TB = "tb" as TrackKey;
const F = { trackKey: null, focusIssue: null, showClosed: false };
const LIGHT = { dark: false };

const node = (number: number, rank: number | null, extra: Partial<CritIssueNode> = {}): CritIssueNode => ({
  id: `${R}#${number}`, repo: R, number, title: `issue ${number}`,
  state: "open", trackKey: TA, trackName: "Alpha", isRef: false,
  rank, unranked: rank === null, inProgress: false,
  downstreamDepth: 0, nextUpIndex: null, ...extra,
});
const model = (extra: Partial<CriticalPathModel> = {}): CriticalPathModel => ({
  repo: R, issues: [], outside: [], connectors: [], edges: [],
  stubs: [], cycles: [], notes: [], trackOrder: [TA, TB], ...extra,
});
const blocks = (a: number, b: number) =>
  ({ from: `${R}#${a}`, to: `${R}#${b}`, kind: "blocks" as const });
const labels = (mermaid: string): string[] =>
  [...mermaid.matchAll(/\["([^\n]*?)"\]/g)].map(m => m[1]);

/** A star: #1 blocks `n` dependents, so exactly `n` edges. */
const star = (n: number): CriticalPathModel => model({
  issues: [node(1, 0), ...Array.from({ length: n }, (_, i) => node(i + 2, 1))],
  edges: Array.from({ length: n }, (_, i) => blocks(1, i + 2)),
});

describe("renderCriticalPath", () => {
  it("columns: Done only with showClosed, ranks in order, loop column only on cycle", () => {
    const closed = node(9, null, { state: "closed", unranked: false });
    const m = model({ issues: [node(1, 0), node(2, 1), closed], edges: [blocks(1, 2)] });
    const plain = renderCriticalPath(m, F, LIGHT).mermaid;
    assert.ok(!plain.includes('"Done"'));
    assert.ok(!plain.includes("dependency loop"));
    const withClosed = renderCriticalPath(m, { ...F, showClosed: true }, LIGHT).mermaid;
    assert.ok(withClosed.includes('"Done"'));
    assert.ok(withClosed.indexOf('"Done"') < withClosed.indexOf('"Rank 0"'));
    assert.ok(withClosed.indexOf('"Rank 0"') < withClosed.indexOf('"Rank 1"'));

    const cyc = model({
      issues: [node(1, null), node(2, null)],
      edges: [blocks(1, 2), blocks(2, 1)],
      cycles: [{ members: ["r#1", "r#2"], waiting: 0 }],
    });
    const out = renderCriticalPath(cyc, F, LIGHT).mermaid;
    assert.ok(out.includes("Can't rank — dependency loop"));
    assert.ok(out.indexOf("Can't rank") > out.indexOf("subgraph"));
    // every open node label starts with its rank number or ?
    for (const l of labels(renderCriticalPath(m, F, LIGHT).mermaid).filter(x => x.includes("#"))) {
      assert.match(l, /^[0-9?] /);
    }
    for (const l of labels(out).filter(x => x.includes("#"))) assert.match(l, /^\? /);
  });

  it("columns are chained with invisible links", () => {
    const m = model({ issues: [node(1, 0), node(2, 1)], edges: [blocks(1, 2)] });
    assert.match(renderCriticalPath(m, F, LIGHT).mermaid, /col_r0 ~~~ col_r1/);
  });

  it("nodes carry chip and label", () => {
    const m = model({ issues: [node(1, 0, { trackName: "Alpha" }), node(2, 1, { trackKey: TB, trackName: "Beta", isRef: true })], edges: [blocks(1, 2)] });
    const r = renderCriticalPath(m, F, LIGHT);
    const ls = labels(r.mermaid);
    assert.ok(ls.some(l => l.includes("#1") && l.includes("Alpha")));
    assert.ok(ls.some(l => l.includes("#2") && l.includes("Beta") && l.includes("ref")));
    assert.deepEqual(r.legend.map(l => l.label), ["Alpha", "Beta"]);
    assert.notEqual(r.legend[0].color, r.legend[1].color);
  });

  it("stub: one node and one edge; replaced by dimmed closed nodes with showClosed", () => {
    const closed = [node(8, null, { state: "closed", unranked: false }), node(9, null, { state: "closed", unranked: false })];
    const m = model({
      issues: [node(1, 0), ...closed],
      stubs: [{ target: "r#1", count: 2 }],
      edges: [{ from: "done:r#1", to: "r#1", kind: "done-stub" }, blocks(8, 1), blocks(9, 1)],
    });
    const r = renderCriticalPath(m, F, LIGHT);
    assert.equal(r.mermaid.split("✓ 2 done that blocked this").length - 1, 1);
    assert.equal(r.edgeCount, 1);
    assert.ok(!r.mermaid.includes("#8"));
    const rc = renderCriticalPath(m, { ...F, showClosed: true }, LIGHT);
    assert.ok(!rc.mermaid.includes("done that blocked this"));
    assert.ok(rc.mermaid.includes("#8") && rc.mermaid.includes("#9"));
    assert.equal(rc.edgeCount, 2);
    assert.match(rc.mermaid, /class [^\n]*dimmed/);
  });

  it("connector: one node 'track D done' between D's end and T's start", () => {
    const m = model({
      issues: [node(1, 0), node(2, 0, { trackKey: TB, trackName: "T" })],
      connectors: [{ id: "track:D>T", dependencyTrack: "D", dependentTrack: "T" }],
      edges: [
        { from: "r#1", to: "track:D>T", kind: "track-dep" },
        { from: "track:D>T", to: "r#2", kind: "track-dep" },
      ],
    });
    const r = renderCriticalPath(m, F, LIGHT);
    assert.equal(r.mermaid.split('"track D done"').length - 1, 1);
    assert.equal(r.edgeCount, 2);
  });

  it("outside node is drawn unnumbered with its repo#N label, outside any column", () => {
    const m = model({
      issues: [node(1, 1)],
      outside: [{ id: "o/x#7", label: "o/x#7" }],
      edges: [{ from: "o/x#7", to: "r#1", kind: "blocks" }],
    });
    const r = renderCriticalPath(m, F, LIGHT);
    const l = labels(r.mermaid).find(x => x.includes("o/x#7"))!;
    assert.ok(l && !/^[0-9?] /.test(l));
    const decl = r.mermaid.split("\n").findIndex(x => x.includes("o/x#7"));
    const subEnd = r.mermaid.split("\n").map(x => x.trim()).lastIndexOf("end");
    assert.ok(decl > subEnd);
  });

  it("banner pluralises", () => {
    const cyc = (waiting: number) => model({
      issues: [node(1, null), node(2, null)],
      edges: [blocks(1, 2), blocks(2, 1)],
      cycles: [{ members: ["r#1", "r#2"], waiting }],
    });
    assert.equal(
      renderCriticalPath(cyc(1), F, LIGHT).banner,
      "These block each other: #1 → #2 → #1. 1 more issue waits on them. Fix the links on GitHub.",
    );
    assert.equal(
      renderCriticalPath(cyc(4), F, LIGHT).banner,
      "These block each other: #1 → #2 → #1. 4 more issues wait on them. Fix the links on GitHub.",
    );
    assert.equal(renderCriticalPath(model({ issues: [node(1, 0)] }), F, LIGHT).banner, null);
  });

  it("escaping: hostile and long titles", () => {
    const nasty = 'He said "hi" [x] | `y`';
    const long = "x".repeat(200);
    const m = model({ issues: [node(1, 0, { title: nasty }), node(2, 0, { title: long })] });
    const r = renderCriticalPath(m, F, LIGHT);
    const ls = labels(r.mermaid).filter(l => l.includes("#"));
    assert.equal(ls.length, 2);
    for (const l of ls) {
      assert.ok(!/["[|]/.test(l), l);
      assert.ok(l.length <= 90, l);
    }
    assert.ok(ls.some(l => l.includes("…")));
    assert.ok(!r.mermaid.includes("x".repeat(60)));
  });

  it("deterministic", () => {
    const m = model({ issues: [node(1, 0), node(2, 1)], edges: [blocks(1, 2)] });
    assert.equal(renderCriticalPath(m, F, LIGHT).mermaid, renderCriticalPath(m, F, LIGHT).mermaid);
  });

  it("display order inside a column", () => {
    const m = model({
      issues: [
        node(4, 0, { downstreamDepth: 0 }),
        node(3, 0, { downstreamDepth: 1, nextUpIndex: null }),
        node(2, 0, { downstreamDepth: 1, nextUpIndex: 0 }),
        node(1, 0, { downstreamDepth: 2, trackKey: TB, trackName: "Beta" }),
      ],
    });
    const out = renderCriticalPath(m, F, LIGHT).mermaid;
    const sub = out.slice(out.indexOf("subgraph"), out.indexOf("end"));
    assert.deepEqual([...sub.matchAll(/i_(\d+)/g)].map(x => x[1]), ["1", "2", "3", "4"]);
  });

  it("empty repo", () => {
    const r = renderCriticalPath(model(), F, LIGHT);
    assert.ok(r.empty && r.empty.startsWith("No open issues"));
    assert.equal(r.mermaid, "");
  });

  it("cap: 460 edges is too large, 450 is not", () => {
    const big = renderCriticalPath(star(460), F, LIGHT);
    assert.equal(big.tooLarge, true);
    assert.ok(!big.mermaid.includes("i_1"));
    assert.ok(big.tooLargeMessage!.startsWith("Too large to draw (461 issues, 460 links)"));
    const ok = renderCriticalPath(star(450), F, LIGHT);
    assert.equal(ok.tooLarge, false);
    assert.equal(ok.edgeCount, 450);
    assert.ok(ok.mermaid.includes("i_1"));
  });
});

describe("filterCriticalPath", () => {
  const m = model({
    issues: [
      node(1, 0, { trackKey: TB, trackName: "Beta" }),
      node(2, 1),
      node(3, 2),
      node(4, 0, { trackKey: TB, trackName: "Beta" }),
    ],
    edges: [blocks(1, 2), blocks(2, 3)],
  });

  it("by track: own issues plus direct blockers, dimmed; ranks unchanged", () => {
    const f = filterCriticalPath(m, { ...F, trackKey: TA });
    assert.deepEqual(f.model.issues.map(i => i.number), [1, 2, 3]);
    assert.deepEqual([...f.dimmed], ["r#1"]);
    assert.deepEqual(f.model.issues.map(i => i.rank), [0, 1, 2]);
    assert.equal(f.model.edges.length, 2);
  });

  it("focus issue: full upstream and downstream closure only", () => {
    const chain = model({
      issues: [1, 2, 3, 4, 5, 6, 7].map(n => node(n, 0)),
      edges: [blocks(1, 2), blocks(2, 5), blocks(5, 6), blocks(6, 7), blocks(3, 4)],
    });
    const f = filterCriticalPath(chain, { ...F, focusIssue: "r#5" });
    assert.deepEqual(f.model.issues.map(i => i.number).sort(), [1, 2, 5, 6, 7]);
    assert.equal(f.model.edges.length, 4);
  });
});

describe("fitToCap", () => {
  it("under cap: unchanged", () => {
    const r = fitToCap(star(10), F, TA, LIGHT);
    assert.equal(r.filter.trackKey, null);
    assert.equal(r.autoFiltered, null);
    assert.equal(r.render.tooLarge, false);
  });

  it("over cap: filters to the selected track and says so", () => {
    const m = star(460);
    m.issues.forEach((i, idx) => { if (idx > 230) { i.trackKey = TB; i.trackName = "Beta"; } });
    const r = fitToCap(m, F, TA, LIGHT);
    assert.equal(r.filter.trackKey, TA);
    assert.ok(r.autoFiltered!.includes("too large to draw at once (461 issues)"));
    assert.ok(r.autoFiltered!.includes("Alpha"));
  });

  it("still over cap after filtering: tooLarge stays true", () => {
    const r = fitToCap(star(460), F, TA, LIGHT);
    assert.equal(r.filter.trackKey, TA);
    assert.ok(r.autoFiltered !== null);
    assert.equal(r.render.tooLarge, true);
  });
});
