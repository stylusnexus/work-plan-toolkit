import { describe, it } from "node:test";
import assert from "node:assert/strict";
import type { TrackKey } from "../model.ts";
import type { CritIssueNode, CriticalPathModel } from "./criticalPath.ts";
import { filterCriticalPath, fitToCap, nextCritState, renderCriticalPath, visibleTrackOrder } from "./criticalPathRender.ts";

const R = "r";
const TA = "ta" as TrackKey;
const TB = "tb" as TrackKey;
const F = { trackKey: null, focusIssue: null, showClosed: false };
const LIGHT = { dark: false };

const node = (number: number, rank: number | null, extra: Partial<CritIssueNode> = {}): CritIssueNode => ({
  id: `${R}#${number}`, repo: R, number, title: `issue ${number}`,
  state: "open", trackKey: TA, trackName: "Alpha", isRef: false,
  memberTrackKeys: [extra.trackKey ?? TA],
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
    assert.ok(withClosed.indexOf('"Done"') < withClosed.indexOf('"Startable now"'));
    assert.ok(withClosed.indexOf('"Startable now"') < withClosed.indexOf('"1 step from startable"'));

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

  it("column labels say steps from startable, never Rank", () => {
    const m = model({
      issues: [node(1, 0), node(2, 1), node(3, 2), node(4, 3)],
      edges: [blocks(1, 2), blocks(2, 3), blocks(3, 4)],
    });
    const out = renderCriticalPath(m, F, LIGHT).mermaid;
    const cols = [...out.matchAll(/subgraph \w+\["([^"]*)"\]/g)].map(x => x[1]);
    assert.deepEqual(cols, [
      "Startable now", "1 step from startable", "2 steps from startable", "3 steps from startable",
    ]);
    for (const c of cols) assert.ok(!/rank/i.test(c), c);
    // the node keeps its number at the start
    assert.ok(labels(out).some(l => l.startsWith("3 · #4")));
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
    assert.equal(rc.edgeCount, 3); // 2 edges + 1 column link
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

  it("cap counts column links: long rank chain is too large", () => {
    const chain = (n: number): CriticalPathModel => model({
      issues: Array.from({ length: n }, (_, i) => node(i + 1, i)),
      edges: Array.from({ length: n - 1 }, (_, i) => blocks(i + 1, i + 2)),
    });
    const big = renderCriticalPath(chain(300), F, LIGHT);
    assert.equal(big.tooLarge, true);
    assert.equal(big.edgeCount, 299 + 299);
    assert.ok(big.tooLargeMessage!.startsWith("Too large to draw (300 issues, 598 links)"));
    // 225 issues: 224 real + 224 links = 448 <= 450
    const ok = renderCriticalPath(chain(225), F, LIGHT);
    assert.equal(ok.tooLarge, false);
    assert.equal(ok.edgeCount, 448);
    // 227 issues: 226 + 226 = 452 > 450
    assert.equal(renderCriticalPath(chain(227), F, LIGHT).tooLarge, true);
  });

  it("cap: 460 edges is too large, 450 total is not", () => {
    const big = renderCriticalPath(star(460), F, LIGHT);
    assert.equal(big.tooLarge, true);
    assert.ok(!big.mermaid.includes("i_1"));
    assert.ok(big.tooLargeMessage!.startsWith("Too large to draw (461 issues, 461 links)"));
    const ok = renderCriticalPath(star(449), F, LIGHT); // 449 edges + 1 column link
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

  it("by track: matches referenced issues and every owner, chip unchanged", () => {
    const TX = "tx" as TrackKey;
    const mm = model({
      trackOrder: [TA, TB, TX],
      issues: [
        // owned by B, referenced by X
        node(1, 0, { trackKey: TB, trackName: "Beta", memberTrackKeys: [TB, TX] }),
        // owned by A and B
        node(2, 0, { trackKey: TA, trackName: "Alpha", memberTrackKeys: [TA, TB] }),
        node(3, 0, { trackKey: TA, trackName: "Alpha" }),
      ],
    });
    const ids = (k: TrackKey) => filterCriticalPath(mm, { ...F, trackKey: k }).model.issues.map(i => i.number);
    assert.deepEqual(ids(TX), [1]);
    assert.deepEqual(ids(TB), [1, 2]);
    assert.deepEqual(ids(TA), [2, 3]);
    assert.deepEqual(filterCriticalPath(mm, { ...F, trackKey: TX }).dimmed.size, 0);
    const out = renderCriticalPath(mm, { ...F, trackKey: TX }, LIGHT).mermaid;
    assert.ok(labels(out).some(l => l.includes("#1") && l.includes("Beta")));
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

describe("sidebar lens (visibleTracks)", () => {
  // A: #1 (rank 0), #3 blocked by B's #2 (rank 1). B: #2 (rank 0), #4 (rank 0).
  const m = model({
    issues: [
      node(1, 0),
      node(2, 0, { trackKey: TB, trackName: "Beta" }),
      node(3, 1),
      node(4, 0, { trackKey: TB, trackName: "Beta" }),
    ],
    edges: [blocks(2, 3)],
  });
  const onlyA: ReadonlySet<TrackKey> = new Set([TA]);
  const aLabels = (mermaid: string) => labels(mermaid).filter(l => l.includes("Alpha"));

  it("hides the lensed-out track's issues; ranks of the rest are unchanged", () => {
    const plain = renderCriticalPath(m, F, LIGHT);
    const lens = renderCriticalPath(m, F, { ...LIGHT, visibleTracks: onlyA });
    assert.ok(!lens.mermaid.includes("#4"), "B's #4 should be hidden");
    assert.deepEqual(aLabels(lens.mermaid), aLabels(plain.mermaid));
    assert.ok(labels(lens.mermaid).some(l => l.startsWith("1 · #3")));
  });

  it("keeps the other track's direct blocker of a visible issue, dimmed", () => {
    const f = filterCriticalPath(m, F, onlyA);
    assert.deepEqual(f.model.issues.map(i => i.number), [1, 2, 3]);
    assert.deepEqual([...f.dimmed], ["r#2"]);
    assert.match(renderCriticalPath(m, F, { ...LIGHT, visibleTracks: onlyA }).mermaid, /class i_2 dimmed/);
  });

  it("the track dropdown lists only visible tracks", () => {
    assert.deepEqual(visibleTrackOrder(m, onlyA), [TA]);
    assert.deepEqual(visibleTrackOrder(m, undefined), [TA, TB]);
  });

  it("no lens (every track visible) renders exactly as without one", () => {
    const all: ReadonlySet<TrackKey> = new Set([TA, TB]);
    assert.equal(
      renderCriticalPath(m, F, { ...LIGHT, visibleTracks: all }).mermaid,
      renderCriticalPath(m, F, LIGHT).mermaid,
    );
  });

  it("a connector between two visible tracks is not dimmed; one from a filtered-out track is", () => {
    const TC = "tc" as TrackKey;
    const cm = model({
      trackOrder: [TA, TB, TC],
      issues: [node(1, 0), node(2, 1, { trackKey: TB, trackName: "Beta" }), node(5, 0, { trackKey: TC, trackName: "Gamma" })],
      connectors: [{ id: "track:Alpha>Beta", dependencyTrack: "Alpha", dependentTrack: "Beta" }],
      edges: [
        { from: "r#1", to: "track:Alpha>Beta", kind: "track-dep" },
        { from: "track:Alpha>Beta", to: "r#2", kind: "track-dep" },
      ],
    });
    const lensed = filterCriticalPath(cm, F, new Set([TA, TB]));
    assert.deepEqual(lensed.model.issues.map(i => i.number), [1, 2]);
    assert.equal(lensed.dimmed.size, 0);
    const byTrack = filterCriticalPath(cm, { ...F, trackKey: TB });
    assert.deepEqual([...byTrack.dimmed], ["track:Alpha>Beta"]);
  });

  it("combines with the track filter and passes through fitToCap", () => {
    const f = filterCriticalPath(m, { ...F, trackKey: TB }, onlyA);
    assert.deepEqual(f.model.issues.map(i => i.number), []);
    const r = fitToCap(m, F, TA, { ...LIGHT, visibleTracks: onlyA });
    assert.ok(!r.render.mermaid.includes("#4"));
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

describe("nextCritState", () => {
  const prev = (over: Record<string, unknown> = {}) => ({
    mode: "critical" as const,
    filter: { trackKey: TA, focusIssue: `${R}#1`, showClosed: true },
    repo: R as string | null,
    ...over,
  });

  it("refresh keeps mode and filter when everything still exists", () => {
    const s = nextCritState(prev(), { type: "refresh", knownTracks: [TA, TB], knownIssues: [`${R}#1`] });
    assert.equal(s.mode, "critical");
    assert.deepEqual(s.filter, prev().filter);
    assert.equal(s.note, null);
  });

  it("selectTrack in critical mode keeps critical", () => {
    assert.equal(nextCritState(prev(), { type: "selectTrack", repo: R }).mode, "critical");
  });

  it("selecting a track in a different repo clears track and issue but keeps showClosed", () => {
    const s = nextCritState(prev(), { type: "selectTrack", repo: "other" });
    assert.deepEqual(s.filter, { trackKey: null, focusIssue: null, showClosed: true });
    assert.equal(s.repo, "other");
  });

  it("selectTrack in the same repo keeps the filter", () => {
    assert.deepEqual(nextCritState(prev(), { type: "selectTrack", repo: R }).filter, prev().filter);
  });

  it("selectTrack in full mode resets to focus", () => {
    assert.equal(nextCritState(prev({ mode: "full" }), { type: "selectTrack", repo: R }).mode, "focus");
  });

  it("refresh clears a vanished filtered track and notes it", () => {
    const s = nextCritState(prev(), { type: "refresh", knownTracks: [TB], knownIssues: [`${R}#1`] });
    assert.equal(s.filter.trackKey, null);
    assert.equal(s.filter.focusIssue, `${R}#1`);
    assert.ok(s.note && !s.note.includes("\n"));
  });

  it("refresh clears a vanished focused issue and notes it", () => {
    const s = nextCritState(prev(), { type: "refresh", knownTracks: [TA], knownIssues: [] });
    assert.equal(s.filter.focusIssue, null);
    assert.equal(s.filter.trackKey, TA);
    assert.ok(s.note && !s.note.includes("\n"));
  });
});

describe("auto-fit then explicit clear", () => {
  const big = () => {
    const m = star(460);
    m.issues.forEach((i, idx) => { if (idx > 230) { i.trackKey = TB; i.trackName = "Beta"; } });
    return m;
  };
  const start = { mode: "critical" as const, filter: F, repo: R as string | null, autoFitSuppressed: false };

  it("open over cap saves auto-fit; clear shows too-large with no auto filter; pick re-applies; repo change resets", () => {
    // open: auto-fit applies the selected track and the host saves it
    const fit1 = fitToCap(big(), start.filter, TA, { ...LIGHT, suppressAutoFit: start.autoFitSuppressed });
    assert.equal(fit1.filter.trackKey, TA);
    const s1 = nextCritState(start, { type: "autoFit", trackKey: TA });
    assert.equal(s1.filter.trackKey, TA);
    assert.equal(s1.autoFitSuppressed, false);

    // user clears -> suppressed; no auto filter; too-large message
    const s2 = nextCritState(s1, { type: "setTrackFilter", key: null });
    assert.equal(s2.filter.trackKey, null);
    assert.equal(s2.autoFitSuppressed, true);
    const fit2 = fitToCap(star(460), s2.filter, TA, { ...LIGHT, suppressAutoFit: s2.autoFitSuppressed });
    assert.equal(fit2.autoFiltered, null);
    assert.equal(fit2.filter.trackKey, null);
    assert.equal(fit2.render.tooLarge, true);
    assert.ok(fit2.render.tooLargeMessage!.startsWith("Too large to draw (461 issues"));

    // user picks another track -> applied, suppression off
    const s3 = nextCritState(s2, { type: "setTrackFilter", key: TB });
    assert.equal(s3.filter.trackKey, TB);
    assert.equal(s3.autoFitSuppressed, false);

    // clear again, then a repo change resets suppression
    const s4 = nextCritState(s3, { type: "setTrackFilter", key: null });
    assert.equal(s4.autoFitSuppressed, true);
    assert.equal(nextCritState(s4, { type: "selectTrack", repo: "other" }).autoFitSuppressed, false);
    // same-repo select keeps it; leaving and re-entering critical resets it
    assert.equal(nextCritState(s4, { type: "selectTrack", repo: R }).autoFitSuppressed, true);
    const out = nextCritState(s4, { type: "setMode", mode: "focus" });
    assert.equal(nextCritState(out, { type: "setMode", mode: "critical" }).autoFitSuppressed, false);
  });

  it("showClosed and focus events update only their field", () => {
    const a = nextCritState(start, { type: "setShowClosed", show: true });
    assert.equal(a.filter.showClosed, true);
    const b = nextCritState(a, { type: "setFocusIssue", id: `${R}#1` });
    assert.equal(b.filter.focusIssue, `${R}#1`);
    assert.equal(b.filter.showClosed, true);
  });
});
