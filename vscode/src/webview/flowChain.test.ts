import { describe, it } from "node:test";
import assert from "node:assert/strict";
import type { TrackKey } from "../model.ts";
import type { CritIssueNode, CriticalPathModel } from "./criticalPath.ts";
import { renderCriticalPath } from "./criticalPathRender.ts";
import { buildFlowText } from "./flowCopy.ts";
import { buildHtml } from "./html.ts";

// A chain through every drawn item that is not an issue (#609).
const issue: CritIssueNode = {
  id: "r#1", repo: "r", number: 1, title: "First", state: "open", trackKey: "ta" as TrackKey,
  trackName: "Alpha", isRef: false, memberTrackKeys: ["ta" as TrackKey], trackBlocked: false,
  rank: 1, unranked: false, inProgress: false, inReview: false, assignee: "—", milestone: null,
  downstreamDepth: 0, nextUpIndex: null,
};
const model: CriticalPathModel = {
  repo: "r", issues: [issue],
  outside: [{ id: "r#7", label: "#7 untracked" }, { id: "o/other#5", label: "o/other#5" }],
  connectors: [{ id: "c", dependencyTrack: "Core Services", dependentTrack: "Alpha" }],
  edges: [
    { from: "c", to: "r#1", kind: "track-dep" },
    { from: "r#7", to: "r#1", kind: "blocks" },
    { from: "o/other#5", to: "r#1", kind: "blocks" },
    { from: "done:r#1", to: "r#1", kind: "done-stub" },
  ],
  stubs: [{ target: "r#1", count: 2 }], cycles: [], notes: [], trackOrder: ["ta" as TrackKey],
};
const out = renderCriticalPath(model, {
  trackKey: null, owner: null, milestone: null, status: null, focusIssue: null,
  showClosed: false, showUnlinked: true,
}, { dark: false });

const NAMES = ["track Core Services done", "o/other#5", "✓ 2 done that blocked this"];

describe("issue chain names every linked item (#609)", () => {
  it("copies full names in the task and order formats", () => {
    for (const format of ["tasks", "order"] as const) {
      const lines = buildFlowText(out.nodeLinks, out.nodeTitles, "i_1", format).split("\n")
        .map(l => l.replace(/^(- \[ \] |\d+\. )/, ""));
      assert.deepEqual([...lines].sort(), [...NAMES, "#7 untracked", "#1 First (this)"].sort());
    }
  });

  it("copies full names in paths, with issues as numbers", () => {
    const lines = buildFlowText(out.nodeLinks, out.nodeTitles, "i_1", "paths").split("\n");
    assert.deepEqual(lines.slice(0, -1).sort(), [...NAMES, "#7"].map(n => `${n} → #1`).sort());
    assert.doesNotMatch(lines.join("\n"), /\b[kos]_\d/);
  });

  it("shows full names in the on-screen chain", () => {
    const html = buildHtml({
      cspSource: "x:", nonce: "n".repeat(32), mermaidUri: "x:/m.js", graphDef: out.mermaid, detailHtml: "",
      trackName: "t", isModule: false, mode: "critical", isDark: false, hasTrackFile: true,
      issueStates: { open: true, closed: false }, graphNote: null, trackKey: "k",
      critical: {
        trackFilter: null, owner: null, milestone: null, status: null, ownerOptions: [], milestoneOptions: [],
        filterNote: null, focusIssueLabel: null, showUnlinked: true, unlinkedCount: 0, banner: null,
        legend: [], tooLargeMessage: null, autoFilterNote: null, emptyMessage: null, trackOptions: [],
        nodeTitles: out.nodeTitles, nodeLinks: out.nodeLinks,
      },
    });
    // Run the page's own splitter: the chain row is its num followed by its title.
    const src = html.slice(html.indexOf("function flowParts("), html.indexOf("// Owner, milestone and work status"));
    const flowParts = new Function("nodeTitles", `${src}; return flowParts;`)(out.nodeTitles) as
      (id: string) => { num: string; title: string };
    const rows = out.nodeLinks.map(([from]) => flowParts(from));
    assert.deepEqual(rows.map(r => r.num).sort(), [...NAMES, "#7"].sort());
    assert.deepEqual(rows.filter(r => r.title).map(r => r.title), ["untracked"]);
  });
});

describe("names that are not issues are read as names only (#609)", () => {
  it("names the hidden-issues box", () => {
    const hidden = renderCriticalPath({ ...model, issues: [issue, { ...issue, id: "r#2", number: 2, rank: 0 }] }, {
      trackKey: null, owner: null, milestone: null, status: null, focusIssue: null,
      showClosed: false, showUnlinked: false,
    }, { dark: false });
    assert.equal(
      buildFlowText(hidden.nodeLinks, hidden.nodeTitles, "u_hidden", "paths"),
      "1 startable issue with no links (hidden)",
    );
  });

  it("takes no status from a track name", () => {
    const titles = { k_0: "track work in progress done" };
    assert.equal(buildFlowText([], titles, "k_0", "order"), "1. track work in progress done (this)");
  });

  it("takes no issue number from a repo owner that starts with a digit", () => {
    const titles = { i_5: "#5 five", i_20: "#20 twenty", o_0: "9to5/app#1", i_30: "#30 last" };
    const links: [string, string][] = [["i_5", "i_30"], ["i_20", "i_30"], ["o_0", "i_30"]];
    assert.equal(buildFlowText(links, titles, "i_30", "paths").split("\n").at(-1), "Order: 9to5/app#1, #5, #20, #30");
  });
});
