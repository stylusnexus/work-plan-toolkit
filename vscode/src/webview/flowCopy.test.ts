import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { buildFlowText } from "./flowCopy.ts";
import { buildHtml } from "./html.ts";

const t = (n: number, title: string, state = "open") => `#${n} ${title}\nTrack: A\nState: ${state}`;
// #9893 and #9894 feed #9900, which feeds #9905; #9899 feeds #9905 too.
const titles: Record<string, string> = {
  a: t(9893, "pricing"), b: t(9894, "name the game", "open, in progress"),
  c: t(9900, "flip access"), d: t(9905, "send email"), e: t(9899, "capture UTM"), x: t(1, "unrelated"),
};
const links: [string, string][] = [["a", "c"], ["b", "c"], ["c", "d"], ["e", "d"], ["x", "x2"]];
const T = { ...titles, x2: t(2, "also unrelated") };

describe("buildFlowText", () => {
  it("paths: one numbers-only chain per path plus a work-order line", () => {
    assert.equal(
      buildFlowText(links, T, "d", "paths"),
      "#9893 → #9900 → #9905\n#9894 → #9900 → #9905\n#9899 → #9905\nOrder: #9893, #9894, #9899, #9900, #9905",
    );
  });

  it("paths from a middle issue spans what it waits on and what it unblocks", () => {
    assert.equal(
      buildFlowText(links, T, "c", "paths"),
      "#9893 → #9900 → #9905\n#9894 → #9900 → #9905\nOrder: #9893, #9894, #9900, #9905",
    );
  });

  it("tasks: markdown checklist in work order, marks the pick and in-progress work", () => {
    assert.equal(
      buildFlowText(links, T, "c", "tasks"),
      [
        "- [ ] #9893 pricing",
        "- [ ] #9894 name the game (in progress)",
        "- [ ] #9900 flip access (this)",
        "- [ ] #9905 send email",
      ].join("\n"),
    );
  });

  it("order: numbered list with titles", () => {
    assert.equal(
      buildFlowText(links, T, "d", "order").split("\n")[0],
      "1. #9893 pricing",
    );
  });

  it("a single path has no Order line; an unlinked pick copies just itself", () => {
    assert.equal(buildFlowText([["a", "c"]], T, "c", "paths"), "#9893 → #9900");
    assert.equal(buildFlowText([], T, "d", "paths"), "#9905");
  });

  it("closed issues are left out", () => {
    const withClosed = { ...T, a: t(9893, "pricing", "closed") };
    assert.equal(buildFlowText(links, withClosed, "c", "paths"), "#9894 → #9900 → #9905");
  });

  it("falls back to the work-order list when there are too many paths", () => {
    const ls: [string, string][] = [];
    const ts: Record<string, string> = { top: t(1000, "top"), end: t(2000, "end") };
    for (let k = 0; k < 40; k++) { ts[`m${k}`] = t(k + 1, `m${k}`); ls.push(["top", `m${k}`], [`m${k}`, "end"]); }
    const out = buildFlowText(ls, ts, "top", "paths");
    assert.ok(out.startsWith("1. #1000 top"), out.slice(0, 40));
    assert.equal(out.split("\n").length, 42);
  });

  it("tolerates a missing title and a loop", () => {
    assert.equal(buildFlowText([["p", "q"], ["q", "p"]], {}, "p", "tasks").split("\n").length, 2);
    assert.equal(buildFlowText([["p", "q"]], {}, "q", "paths"), "p → q");
  });

  it("is inlined into the critical page, with the copy control and message", () => {
    const html = buildHtml({
      cspSource: "x:", nonce: "n".repeat(32), mermaidUri: "x:/m.js", graphDef: "graph LR\n a --> b", detailHtml: "",
      trackName: "t", isModule: false, mode: "critical", isDark: true, hasTrackFile: true,
      critical: {
        trackFilter: null, focusIssueLabel: null, showClosed: false, showUnlinked: false, unlinkedCount: 0, banner: null,
        legend: [], tooLargeMessage: null, autoFilterNote: null, emptyMessage: null, trackOptions: [],
      },
    });
    assert.ok(html.includes("var buildFlowText = function buildFlowText") || html.includes("var buildFlowText = function"));
    assert.ok(html.includes('id="flow-copy"') && html.includes("type: 'copyText'"));
    assert.ok(!/innerHTML/.test(html));
  });
});
