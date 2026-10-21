import { describe, it } from "node:test";
import assert from "node:assert/strict";
import type { Export, Issue, IssueDep, Track } from "../model.ts";
import { trackKey } from "../model.ts";
import { makeIssue, makeTrack } from "../testFixtures.ts";
import { computeCriticalPath, criticalPickItems, nextUpGateAllows } from "./criticalPath.ts";

const R = "r";
const dep = (number: number, repo = R): IssueDep => ({ number, repo, title: `t${number}` });
const iss = (number: number, blockedBy: number[] = [], extra: Partial<Issue> = {}): Issue =>
  makeIssue({ number, title: `issue ${number}`, blocked_by: blockedBy.map(n => dep(n)), ...extra });
const trk = (name: string, issues: Issue[], extra: Partial<Track> = {}): Track =>
  makeTrack({ name, repo: R, issues, ...extra });
const exp = (...tracks: Track[]): Export =>
  ({ schema: 1, generated_at: "x", tracks }) as Export;
const rankOf = (m: ReturnType<typeof computeCriticalPath>, n: number) =>
  m.issues.find(i => i.number === n)!.rank;

describe("computeCriticalPath", () => {
  it("chain ranks 0,1,2", () => {
    const m = computeCriticalPath(exp(trk("A", [iss(1), iss(2, [1]), iss(3, [2])])), R);
    assert.deepEqual([1, 2, 3].map(n => rankOf(m, n)), [0, 1, 2]);
  });

  it("cross-track link", () => {
    const a = trk("A", [iss(1)]);
    const b = trk("B", [iss(2, [1])]);
    const m = computeCriticalPath(exp(a, b), R);
    const n2 = m.issues.find(i => i.number === 2)!;
    assert.equal(n2.rank, 1);
    assert.equal(n2.trackKey, trackKey(b));
    assert.equal(n2.trackName, "B");
    assert.ok(m.edges.some(e => e.from === "r#1" && e.to === "r#2" && e.kind === "blocks"));
  });

  it("depends_on raises rank", () => {
    const d = trk("D", [iss(1), iss(2, [1])]);
    const t = trk("T", [iss(9)], { depends_on: ["D"] });
    const m = computeCriticalPath(exp(d, t), R);
    assert.equal(rankOf(m, 9), 2);
    assert.equal(m.connectors.length, 1);
    assert.equal(m.connectors[0].dependencyTrack, "D");
    assert.equal(m.connectors[0].dependentTrack, "T");
    const cid = m.connectors[0].id;
    const td = m.edges.filter(e => e.kind === "track-dep");
    assert.deepEqual(td.map(e => [e.from, e.to]), [["r#2", cid], [cid, "r#9"]]);
  });

  it("met dependency has no effect", () => {
    const d = trk("D", [iss(1, [], { state: "closed" })]);
    const t = trk("T", [iss(9)], { depends_on: ["D"] });
    const m = computeCriticalPath(exp(d, t), R);
    assert.equal(rankOf(m, 9), 0);
    assert.equal(m.connectors.length, 0);
  });

  it("missing dependency track", () => {
    const t = trk("T", [iss(9)], { depends_on: ["D"] });
    const m = computeCriticalPath(exp(t), R);
    assert.ok(m.notes.includes("T depends on D, which isn't in this repo's data — not counted."));
    assert.equal(rankOf(m, 9), 0);
  });

  it("other-repo blocker", () => {
    const i5 = makeIssue({ number: 5, blocked_by: [dep(7, "o/other")] });
    const m = computeCriticalPath(exp(trk("A", [i5])), R);
    assert.equal(m.outside.length, 1);
    assert.equal(m.outside[0].label, "o/other#7");
    assert.equal(rankOf(m, 5), 1);
  });

  it("untracked same-repo blocker is labelled", () => {
    const m = computeCriticalPath(exp(trk("A", [iss(5, [77])])), R);
    assert.equal(m.outside[0].label, "#77 untracked");
  });

  it("closed issue does not block", () => {
    const closed = iss(1, [], { state: "closed", blocking: [dep(2)] });
    const m = computeCriticalPath(exp(trk("A", [closed, iss(2)])), R);
    assert.equal(rankOf(m, 2), 0);
    assert.deepEqual(m.stubs, [{ target: "r#2", count: 1 }]);
    assert.equal(m.issues.find(i => i.number === 1)!.rank, null);
  });

  it("closed issue gets a display edge to the open issue it blocked", () => {
    const closed = iss(1, [], { state: "closed", blocking: [dep(2)] });
    const m = computeCriticalPath(exp(trk("A", [closed, iss(2)])), R);
    assert.ok(m.edges.some(e => e.from === "r#1" && e.to === "r#2" && e.kind === "blocks"));
    assert.equal(rankOf(m, 2), 0);
    assert.equal(rankOf(m, 1), null);
  });

  it("in-progress blocked issue keeps rank", () => {
    const m = computeCriticalPath(exp(trk("A", [iss(1), iss(2, [1], { in_progress: true })])), R);
    assert.equal(rankOf(m, 2), 1);
    assert.equal(m.issues.find(i => i.number === 2)!.inProgress, true);
  });

  it("two-node cycle", () => {
    const m = computeCriticalPath(
      exp(trk("A", [iss(0), iss(1, [0, 2]), iss(2, [1]), iss(3, [2])])), R);
    assert.equal(m.cycles.length, 1);
    assert.ok(m.cycles[0].members.includes("r#1") && m.cycles[0].members.includes("r#2"));
    assert.equal(m.cycles[0].waiting, 1);
    for (const n of [1, 2, 3]) {
      const node = m.issues.find(i => i.number === n)!;
      assert.equal(node.unranked, true);
      assert.equal(node.rank, null);
    }
    assert.equal(rankOf(m, 0), 0);
  });

  it("self-blocking issue", () => {
    const m = computeCriticalPath(exp(trk("A", [iss(4, [4])])), R);
    assert.equal(m.cycles.length, 1);
    assert.deepEqual(m.cycles[0].members, ["r#4"]);
  });

  it("cycle through track dependency", () => {
    const d = trk("D", [iss(5, [3])]);
    const t = trk("T", [iss(3)], { depends_on: ["D"] });
    const m = computeCriticalPath(exp(d, t), R);
    assert.equal(m.cycles.length, 1);
    assert.deepEqual([...m.cycles[0].members].sort(), ["r#3", "r#5"]);
  });

  it("next_up only breaks ties", () => {
    const m = computeCriticalPath(exp(trk("A", [iss(1), iss(2)], { next_up: [2, 1] })), R);
    assert.equal(rankOf(m, 1), 0);
    assert.equal(rankOf(m, 2), 0);
    assert.equal(m.issues.find(i => i.number === 2)!.nextUpIndex, 0);
    assert.equal(m.issues.find(i => i.number === 1)!.nextUpIndex, 1);
  });

  it("owned and referenced", () => {
    const shared = iss(1);
    const a = trk("A", [shared]);
    const b = trk("B", [], { references: [shared] });
    const m = computeCriticalPath(exp(a, b), R);
    assert.equal(m.issues.length, 1);
    assert.equal(m.issues[0].trackName, "A");
    assert.equal(m.issues[0].isRef, false);
  });

  it("referenced only gets ref chip", () => {
    const b = trk("B", [], { references: [iss(1)] });
    const m = computeCriticalPath(exp(b), R);
    assert.equal(m.issues[0].isRef, true);
    assert.equal(m.issues[0].trackName, "B");
  });

  it("null repo returns an empty model", () => {
    const m = computeCriticalPath(exp(trk("A", [iss(1)])), null);
    assert.equal(m.issues.length, 0);
    assert.equal(m.repo, null);
  });

  it("guard: rank 0 equals next-up gate", () => {
    const issues = [
      iss(1), iss(2, [1]), iss(3, [99]),
      makeIssue({ number: 4, blocked_by: [dep(8, "o/x")] }),
      iss(5, [], { in_progress: true }), iss(6, [5]),
    ];
    const m = computeCriticalPath(exp(trk("A", issues)), R);
    for (const issue of issues) {
      const node = m.issues.find(i => i.number === issue.number)!;
      assert.equal(node.rank === 0, nextUpGateAllows(issue), `#${issue.number}`);
    }
  });

  it("criticalPickItems lists every issue node", () => {
    const m = computeCriticalPath(exp(trk("A", [iss(1), iss(2, [1])])), R);
    const items = criticalPickItems(m);
    assert.deepEqual(items.map(i => i.id), ["r#1", "r#2"]);
  });
});
