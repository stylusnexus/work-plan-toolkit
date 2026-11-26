import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { makeTrack, makeIssue } from "../testFixtures.ts";
import { renderDetail } from "./detail.ts";
import { computeTableView } from "./tableView.ts";
import { setupIssueTable } from "./tableController.ts";
import { parseHtml } from "./testDom.ts";

const TRACK = makeTrack({
  name: "t", repo: "o/r", rollup: { open: 2, closed: 0 },
  issues: [makeIssue({ number: 1, title: "map", state: "open" }), makeIssue({ number: 2, title: "other", state: "open" })],
});

/** One page per call, sharing saved state, like a webview.html replacement. */
function pages() {
  let state: any;
  return () => {
    const doc = parseHtml(renderDetail(TRACK));
    setupIssueTable({
      document: doc, vscode: { getState: () => state, setState: (s: unknown) => { state = s; } }, post: () => {},
      states: { open: true, closed: false }, trackKey: "k", cap: 50,
      window: { setTimeout: () => 0, clearTimeout: () => {}, addEventListener: () => {} },
    }, computeTableView);
    return doc;
  };
}

describe("filter pop-up across a page redraw (#598)", () => {
  it("reopens the State menu with focus on the same checkbox", () => {
    const load = pages();
    const first = load();
    first.querySelector('.th-filter[data-col="state"]')!.click();
    const closed = first.querySelector("#work-plan-filter-pop")!.querySelectorAll("input")[1];
    closed.focus();
    closed.click();
    const next = load();
    const pop = next.querySelector("#work-plan-filter-pop");
    assert.ok(pop, "pop-up should be open again");
    assert.equal(pop.getAttribute("aria-label"), "Filter by State");
    assert.equal(next.activeElement, pop.querySelectorAll("input")[1]);
  });

  it("reopens the Title menu with the typed text so typing can continue", () => {
    const load = pages();
    const first = load();
    first.querySelector('.th-filter[data-col="title"]')!.click();
    const input = first.querySelector("#work-plan-filter-pop")!.querySelector("input")!;
    input.value = "ma";
    input.fire("input");
    const next = load();
    const again = next.querySelector("#work-plan-filter-pop")?.querySelector("input");
    assert.ok(again);
    assert.equal(again.value, "ma");
    assert.equal(next.activeElement, again);
  });

  it("stays closed after the user closed it", () => {
    const load = pages();
    const first = load();
    first.querySelector('.th-filter[data-col="title"]')!.click();
    first.querySelector("#work-plan-filter-pop")!.querySelector("input")!.fire("keydown", { key: "Escape" });
    assert.equal(load().querySelector("#work-plan-filter-pop"), null);
  });
});
