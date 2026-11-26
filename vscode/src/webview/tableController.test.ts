import { describe, it } from "node:test";
import assert from "node:assert/strict";
import type { Issue, Track } from "../model.ts";
import { makeTrack } from "../testFixtures.ts";
import { renderDetail } from "./detail.ts";
import { computeTableView } from "./tableView.ts";
import { setupIssueTable } from "./tableController.ts";
import { parseHtml, El, type Doc } from "./testDom.ts";

const issue = (number: number, p: Partial<Issue> = {}): Issue => ({
  number, title: `Issue ${number}`, state: "open", assignee: "—", milestone: null,
  in_progress: false, in_progress_label: false, blocked_by: [], blocking: [], ...p,
});
const TRACK = makeTrack({
  name: "t", repo: "o/r", milestone_alignment: "M1", rollup: { open: 3, closed: 1 },
  issues: [
    issue(1, { title: "beta map", assignee: "@amy", milestone: "M1" }),
    issue(2, { title: "alpha", milestone: "M1", blocking: [{ number: 9, repo: "o/r", title: "x" }] }),
    issue(3, { state: "closed", milestone: "M1" }),
    issue(4, { title: "gamma map", assignee: "@bob", milestone: "M2" }),
  ],
});

interface Opts { track?: Track; saved?: unknown; states?: { open: boolean; closed: boolean }; key?: string }
function mount(o: Opts = {}) {
  const doc = parseHtml(renderDetail(o.track ?? TRACK));
  const posted: any[] = [];
  let state: any = o.saved;
  const timers: (() => void)[] = [];
  setupIssueTable({
    document: doc,
    vscode: { getState: () => state, setState: (s: unknown) => { state = s; } },
    post: (m: unknown) => posted.push(m),
    states: o.states ?? { open: true, closed: false },
    trackKey: o.key ?? "k1",
    cap: 50,
    window: { setTimeout: (fn: () => void) => { timers.push(fn); return timers.length; }, clearTimeout: () => {}, addEventListener: () => {} },
  }, computeTableView);
  return { doc, posted, state: () => state, flush: () => timers.splice(0).forEach(f => f()) };
}

const q = (doc: Doc, sel: string): El => {
  const el = doc.querySelector(sel);
  assert.ok(el, `missing ${sel}`);
  return el;
};
const visible = (doc: Doc, table = "work-plan-issues"): number[] =>
  q(doc, `#${table}`).querySelectorAll(".issue-row").filter(r => !r.hidden && !r.closest("tbody")!.hidden)
    .map(r => Number(r.getAttribute("data-num")));
const text = (doc: Doc, id: string): string => q(doc, `#${id}`).textContent.trim();
const openFilter = (doc: Doc, col: string): El => {
  q(doc, `.th-filter[data-col="${col}"]`).click();
  return q(doc, "#work-plan-filter-pop");
};
const typeTitle = (doc: Doc, value: string): void => {
  const input = openFilter(doc, "title").querySelector("input")!;
  input.value = value;
  input.fire("input");
};

describe("setupIssueTable", () => {
  it("hides closed rows by default and summarises", () => {
    const { doc } = mount();
    assert.deepEqual(visible(doc), [1, 2, 4]);
    assert.equal(text(doc, "work-plan-summary-text"), "Showing 3 of 4 issues · State: Open");
    assert.equal(text(doc, "work-plan-table-status"), "Showing 3 of 4 owned issues");
    assert.equal(text(doc, "work-plan-issues").includes("(2 of 3)"), true);
    assert.equal(q(doc, "#work-plan-clear-filters").hidden, true);
  });

  it("uses defaults for old or malformed saved state and keeps flowFormat", () => {
    for (const saved of [{ flowFormat: "order" }, { table: "junk", flowFormat: "order" },
      { table: { sort: { col: "nope" }, titleText: 5, assignees: "x", openGroups: "y", openDeps: 3 }, flowFormat: "order" }]) {
      const m = mount({ saved });
      assert.deepEqual(visible(m.doc), [1, 2, 4]);
      q(m.doc, '.th-sort[data-col="title"]').click();
      assert.equal(m.state().flowFormat, "order");
    }
  });

  it("cycles sort and marks only the sorted heading, moving dependency rows too", () => {
    const { doc } = mount();
    const btn = q(doc, '.th-sort[data-col="title"]');
    btn.click();
    assert.deepEqual(visible(doc), [2, 1, 4]);
    const sorted = (): El[] => doc.querySelectorAll("th").filter(t => t.getAttribute("aria-sort") !== null);
    assert.deepEqual(sorted().map(t => t.getAttribute("aria-sort")), ["ascending"]);
    const dep = q(doc, ".dep-detail-row");
    const row2 = doc.querySelectorAll(".issue-row").find(r => r.getAttribute("data-num") === "2")!;
    assert.equal(row2.nextElementSibling, dep);
    assert.ok(text(doc, "work-plan-summary-text").includes("sorted within milestones"));
    btn.click();
    assert.deepEqual(visible(doc), [1, 2, 4]);
    assert.equal(sorted()[0].getAttribute("aria-sort"), "descending");
    btn.click();
    assert.equal(sorted().length, 0);
  });

  it("filters by title, hides empty groups, opens matches and restores on clear", () => {
    const m = mount();
    typeTitle(m.doc, "map");
    assert.deepEqual(visible(m.doc), [1, 4]);
    const bands = m.doc.querySelectorAll(".milestone-band");
    assert.ok(bands.every(b => !b.classList.contains("collapsed")));
    assert.equal(q(m.doc, '.th-filter[data-col="title"]').getAttribute("aria-label"), "Filter by Title, active");
    m.flush();
    assert.equal(text(m.doc, "work-plan-table-status"), "Showing 2 of 4 owned issues");
    assert.equal(m.posted.length, 0, "title filtering stays in the page");
    q(m.doc, "#work-plan-clear-filters").click();
    assert.deepEqual(visible(m.doc), [1, 2, 4]);
    assert.ok(bands[1].classList.contains("collapsed"), "the earlier open set returns");
    assert.equal(m.doc.activeElement, q(m.doc, '.th-filter[data-col="title"]'));
  });

  it("hides a dependency row with its issue and restores it", () => {
    const m = mount({ saved: { table: { trackKey: "k1", openDeps: ["2"] } } });
    const dep = q(m.doc, ".dep-detail-row");
    assert.equal(dep.hidden, false);
    typeTitle(m.doc, "map");
    assert.equal(dep.hidden, true);
    q(m.doc, "#work-plan-clear-filters").click();
    assert.equal(dep.hidden, false);
  });

  it("filters by assignee including Unassigned", () => {
    const m = mount();
    const pop = openFilter(m.doc, "assignee");
    const boxes = pop.querySelectorAll("input");
    assert.deepEqual(boxes.map(b => b.parentNode!.textContent.trim()), ["@amy", "@bob", "Unassigned"]);
    boxes[0].click();
    boxes[1].click();
    assert.deepEqual(visible(m.doc), [2]);
    assert.ok(text(m.doc, "work-plan-summary-text").includes("Assignee: Unassigned"));
  });

  it("posts the shared setting from the State menu and from Show both states", () => {
    const m = mount();
    openFilter(m.doc, "state").querySelectorAll("input")[1].click();
    assert.deepEqual(m.posted, [{ type: "setIssueStates", open: true, closed: true }]);
    const none = mount({ states: { open: false, closed: false } });
    assert.equal(text(none.doc, "work-plan-empty-text"), "No states are checked.");
    q(none.doc, "#work-plan-both-states").click();
    assert.deepEqual(none.posted, [{ type: "setIssueStates", open: true, closed: true }]);
  });

  it("explains each empty table", () => {
    const onlyClosed = makeTrack({ name: "c", repo: "o/r", issues: [issue(1, { state: "closed" })], rollup: { open: 0, closed: 1 } });
    assert.equal(text(mount({ track: onlyClosed }).doc, "work-plan-empty-text"), "No open owned issues. 1 closed are hidden.");
    const m = mount();
    typeTitle(m.doc, "zzz");
    assert.equal(text(m.doc, "work-plan-empty-text"), "No issues match these filters.");
    assert.equal(q(m.doc, "#work-plan-both-states").hidden, true);
    const empty = makeTrack({ name: "e", repo: "o/r", issues: [], rollup: { open: 0, closed: 0 } });
    assert.equal(text(mount({ track: empty }).doc, "work-plan-empty-text"), "No owned issues");
  });

  it("opens the first group that has matches until the user chooses", () => {
    const track = { ...TRACK, issues: [issue(3, { state: "closed", milestone: "M1" }), issue(4, { milestone: "M2" })] };
    const bands = mount({ track }).doc.querySelectorAll(".milestone-band");
    assert.equal(bands[0].hidden, true);
    assert.equal(bands[1].classList.contains("collapsed"), false);
  });

  it("limits matching rows and reveals the rest with Show all", () => {
    const track = makeTrack({ name: "big", repo: "o/r", rollup: { open: 60, closed: 0 }, issues: Array.from({ length: 60 }, (_, i) => issue(i + 1)) });
    const m = mount({ track });
    assert.equal(visible(m.doc).length, 50);
    assert.equal(text(m.doc, "work-plan-issues").includes("Show all 60 issues (10 more)"), true);
    q(m.doc, ".issue-cap-toggle").click();
    assert.equal(visible(m.doc).length, 60);
    assert.equal(q(m.doc, ".issue-cap-toggle").getAttribute("aria-expanded"), "true");
  });

  it("applies only the state setting to referenced issues", () => {
    const track = { ...TRACK, references: [issue(8), issue(9, { state: "closed" })], reference_rollup: { open: 1, closed: 1 } };
    const m = mount({ track });
    assert.deepEqual(visible(m.doc, "work-plan-refs"), [8]);
    assert.equal(text(m.doc, "work-plan-refs-note"), "1 referenced issue hidden by Issue state.");
  });

  it("keeps sort but resets title and assignee for a different track", () => {
    const saved = { table: { trackKey: "other", titleText: "map", assignees: ["@amy"], sort: { col: "title", dir: "asc" } } };
    assert.deepEqual(visible(mount({ saved }).doc), [2, 1, 4]);
    const same = { table: { trackKey: "k1", titleText: "map", assignees: ["@gone"], sort: null } };
    const m = mount({ saved: same });
    assert.deepEqual(visible(m.doc), [1, 4]);
    assert.equal(q(m.doc, '.th-filter[data-col="assignee"]').getAttribute("aria-label"), "Filter by Assignee");
  });

  it("moves focus into the pop-up and returns it on Escape and on Tab out", () => {
    const m = mount();
    const button = q(m.doc, '.th-filter[data-col="title"]');
    const pop = openFilter(m.doc, "title");
    assert.equal(pop.getAttribute("role"), "dialog");
    assert.equal(pop.getAttribute("aria-label"), "Filter by Title");
    assert.equal(button.getAttribute("aria-expanded"), "true");
    assert.equal(m.doc.activeElement, pop.querySelector("input"));
    pop.querySelector("input")!.fire("keydown", { key: "Escape" });
    assert.equal(m.doc.querySelector("#work-plan-filter-pop"), null);
    assert.equal(m.doc.activeElement, button);
    const again = openFilter(m.doc, "title");
    const e = again.querySelector("button")!.fire("keydown", { key: "Tab", shiftKey: false });
    assert.equal(e.defaultPrevented, true);
    assert.equal(button.getAttribute("aria-expanded"), "false");
  });

  it("restores focus after a redraw only if the page had it", () => {
    const table = { trackKey: "k1", focusId: "sort:title", focused: true };
    assert.equal(mount({ saved: { table } }).doc.activeElement?.getAttribute("data-col"), "title");
    assert.equal(mount({ saved: { table: { ...table, focused: false } } }).doc.activeElement, null);
    const hiddenRow = { trackKey: "k1", focusId: "row:3:move-btn", focused: true };
    const m = mount({ saved: { table: hiddenRow } });
    assert.equal(m.doc.activeElement, q(m.doc, '.th-filter[data-col="title"]'));
  });

  it("survives being inlined into the webview script", () => {
    const inlined = new Function("return " + setupIssueTable.toString())() as typeof setupIssueTable;
    const doc = parseHtml(renderDetail(TRACK));
    inlined({
      document: doc, vscode: null, post: () => {}, states: { open: true, closed: false },
      trackKey: "k", cap: 50, window: { setTimeout: () => 0, clearTimeout: () => {}, addEventListener: () => {} },
    }, computeTableView);
    assert.deepEqual(visible(doc), [1, 2, 4]);
  });
});
