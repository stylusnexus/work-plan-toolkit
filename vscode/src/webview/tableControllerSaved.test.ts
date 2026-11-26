import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { makeTrack, makeIssue } from "../testFixtures.ts";
import { renderDetail } from "./detail.ts";
import { computeTableView } from "./tableView.ts";
import { setupIssueTable } from "./tableController.ts";
import { parseHtml } from "./testDom.ts";

const TRACK = makeTrack({
  name: "t", repo: "o/r", rollup: { open: 1, closed: 0 },
  issues: [makeIssue({ number: 1, title: "one", state: "open" })],
  references: [makeIssue({ number: 1, title: "ref one", state: "open" }), makeIssue({ number: 8, title: "ref", state: "open" })],
  reference_rollup: { open: 2, closed: 0 },
});

function load(table: Record<string, unknown>) {
  let state: any = { table: { trackKey: "k", focused: true, ...table } };
  const doc = parseHtml(renderDetail(TRACK));
  const seen: string[] = [];
  const spy = (el: any): void => {
    const real = el.querySelector.bind(el);
    el.querySelector = (sel: string) => { seen.push(sel); return real(sel); };
  };
  spy(doc.getElementById("work-plan-issues"));
  setupIssueTable({
    document: doc, vscode: { getState: () => state, setState: (s: unknown) => { state = s; } }, post: () => {},
    states: { open: true, closed: false }, trackKey: "k", cap: 50,
    window: { setTimeout: () => 0, clearTimeout: () => {}, addEventListener: () => {} },
  }, computeTableView);
  return { doc, seen, state: () => state };
}

describe("saved table choices (#598)", () => {
  it("restores focus to a link in the Referenced table, not the owned row with the same number", () => {
    for (const num of [1, 8]) {
      const first = load({});
      const link = (doc: typeof first.doc) => doc.querySelector(`#work-plan-refs a[data-issue="${num}"]`)!;
      link(first.doc).focus();
      const next = load({ focusId: first.state().table.focusId });
      // A boolean: printing two page elements on failure never finishes.
      assert.ok(next.doc.activeElement === link(next.doc), String(num));
    }
  });

  it("never builds a selector from a malformed saved focus name", () => {
    for (const focusId of ["sort:x]", "row:5:", "filter:[", "row:1:a]b"]) {
      const { seen } = load({ focusId });
      assert.deepEqual(seen.filter(s => /x\]|filter:\[|\.$|a\]b|=\[\]/.test(s)), [], focusId);
    }
  });
});
