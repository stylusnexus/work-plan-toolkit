import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { computeTableView, type TableRow, type TableQuery } from "./tableView.ts";

const row = (num: number, p: Partial<TableRow> = {}): TableRow =>
  ({ num, title: `T${num}`, state: "open", inProgress: false, assignees: [], group: 0, ...p });
const q = (p: Partial<TableQuery> = {}): TableQuery =>
  ({ states: { open: true, closed: false }, titleText: "", assignees: null, sort: null, showAll: false, ...p });
const both = { open: true, closed: true };
const run = (rows: TableRow[], p: Partial<TableQuery> = {}, cap = 50) => computeTableView(rows, q(p), cap);
const shownNums = (rows: TableRow[], p: Partial<TableQuery> = {}, cap = 50) => {
  const r = run(rows, p, cap);
  return r.order.filter(i => r.shown[i]).map(i => rows[i].num);
};

describe("computeTableView", () => {
  it("filters by state", () => {
    const rows = [row(1), row(2, { state: "closed" })];
    assert.deepEqual(shownNums(rows), [1]);
    assert.equal(run(rows, { states: { open: false, closed: false } }).matched, 0);
  });

  it("matches title text literally, ignoring case", () => {
    const rows = [row(1, { title: "Show full map" }), row(2, { title: 'a<b "q" c:\\x (.*)' }), row(3, { title: "abc" })];
    assert.deepEqual(shownNums(rows, { titleText: "MAP" }), [1]);
    for (const t of ["a<b", '"q"', "c:\\x", "(.*)"]) assert.deepEqual(shownNums(rows, { titleText: t }), [2], t);
  });

  it("filters by assignee and combines filters with AND", () => {
    const rows = [row(1, { assignees: ["@a", "@b"] }), row(2), row(3, { assignees: ["@b"], title: "zzz" })];
    assert.deepEqual(shownNums(rows, { assignees: ["@b"] }), [1, 3]);
    assert.deepEqual(shownNums(rows, { assignees: ["__unassigned__"] }), [2]);
    assert.deepEqual(shownNums(rows, { assignees: ["@b"], titleText: "zz" }), [3]);
  });

  it("drops stale assignees, turning the filter off when none remain", () => {
    const rows = [row(1, { assignees: ["@a"] }), row(2)];
    assert.deepEqual(shownNums(rows, { assignees: ["@gone"] }), [1, 2]);
    assert.deepEqual(shownNums(rows, { assignees: ["@gone", "@a"] }), [1]);
    assert.deepEqual(shownNums(rows, { assignees: [] }), []);
  });

  it("keeps input order without a sort", () => {
    assert.deepEqual(shownNums([row(3), row(1), row(2)]), [3, 1, 2]);
  });

  it("sorts state as open in progress, open, closed", () => {
    const rows = [row(1, { state: "closed", inProgress: true }), row(2), row(3, { inProgress: true }), row(4, { state: "closed" })];
    assert.deepEqual(shownNums(rows, { states: both, sort: { col: "state", dir: "asc" } }), [3, 2, 1, 4]);
  });

  it("sorts title and first assignee ignoring case, unassigned last both ways, ties by number", () => {
    const rows = [row(5, { assignees: ["@Bob"] }), row(2), row(4, { assignees: ["@amy", "@zed"] }), row(3, { assignees: ["@bob"] })];
    assert.deepEqual(shownNums(rows, { sort: { col: "assignee", dir: "asc" } }), [4, 3, 5, 2]);
    assert.deepEqual(shownNums(rows, { sort: { col: "assignee", dir: "desc" } }), [3, 5, 4, 2]);
    const titled = [row(2, { title: "beta" }), row(1, { title: "Beta" }), row(3, { title: "alpha" })];
    assert.deepEqual(shownNums(titled, { sort: { col: "title", dir: "asc" } }), [3, 1, 2]);
    assert.deepEqual(shownNums(titled, { sort: { col: "title", dir: "desc" } }), [1, 2, 3]);
    assert.deepEqual(shownNums(titled, { sort: { col: "num", dir: "desc" } }), [3, 2, 1]);
  });

  it("never moves a row across groups and counts each group", () => {
    const rows = [row(9, { group: 0 }), row(1, { group: 1 }), row(8, { group: 0, state: "closed" })];
    assert.deepEqual(shownNums(rows, { sort: { col: "num", dir: "asc" } }), [9, 1]);
    assert.deepEqual(run(rows).groups, [{ total: 2, matched: 1 }, { total: 1, matched: 1 }]);
  });

  it("applies the limit after filter and sort", () => {
    const rows = Array.from({ length: 70 }, (_, i) => row(i + 1, { state: i < 10 ? "closed" : "open" }));
    const r = run(rows, { sort: { col: "num", dir: "desc" } });
    assert.equal(r.matched, 60);
    assert.equal(r.total, 70);
    assert.equal(r.overLimit, 10);
    const shown = r.order.filter(i => r.shown[i]).map(i => rows[i].num);
    assert.equal(shown.length, 50);
    assert.equal(shown[0], 70);
    assert.equal(shown[49], 21);
    const all = run(rows, { showAll: true });
    assert.equal(all.shown.filter(Boolean).length, 60);
    assert.equal(all.overLimit, 0);
  });

  it("survives being inlined into the webview script", () => {
    const src = computeTableView.toString();
    assert.ok(!src.includes("\\") && !src.includes('"'));
    const inlined = new Function("return " + src)() as typeof computeTableView;
    const rows = [row(1, { assignees: ["@a"] }), row(2, { inProgress: true })];
    const query = q({ sort: { col: "state", dir: "asc" } });
    assert.deepEqual(inlined(rows, query, 50), computeTableView(rows, query, 50));
  });
});
