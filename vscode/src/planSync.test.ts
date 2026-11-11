import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { parseSyncResult, syncArgs, syncToast } from "./planSync.ts";

const json = (o: object): string => JSON.stringify({
  repo: "r", plan_branch: "p", ahead: 0, behind: 0, incoming: [], dirty_paths: [], moved: false, message: "", ...o,
});

describe("planSync", () => {
  it("builds the CLI args", () => {
    assert.deepEqual(syncArgs("demo"), ["plan-branch", "sync", "demo", "--json"]);
  });

  it("parses a result and tolerates missing fields", () => {
    const r = parseSyncResult(json({ state: "fast-forwarded", moved: true, incoming: ["a one", "b two"] }))!;
    assert.deepEqual([r.state, r.moved, r.incoming.length], ["fast-forwarded", true, 2]);
    assert.equal(parseSyncResult('{"state":"dirty"}')!.incoming.length, 0);
  });

  it("an unknown state reads as an error; non-sync output is null", () => {
    assert.equal(parseSyncResult(json({ state: "surprise" }))!.state, "error");
    assert.equal(parseSyncResult("usage: work_plan.py plan-branch <init|status|push>"), null);
    assert.equal(parseSyncResult("[]"), null);
    assert.equal(parseSyncResult('{"x":1}'), null);
  });

  it("toasts: success, no-ops, refusals", () => {
    const t = (o: object) => syncToast(parseSyncResult(json(o)), "o/r");
    assert.match(t({ state: "fast-forwarded", incoming: ["a"] }).text, /1 new plan commit from your team/);
    assert.match(t({ state: "fast-forwarded", incoming: ["a", "b"] }).text, /2 new plan commits/);
    assert.equal(t({ state: "up-to-date" }).level, "info");
    assert.equal(t({ state: "ahead" }).level, "info");
    assert.equal(t({ state: "unpublished" }).level, "info");
    const dirty = t({ state: "dirty", message: "Uncommitted changes in /wt. Commit or stash them." });
    assert.equal(dirty.level, "warning");
    assert.match(dirty.text, /Commit or stash/);
    assert.equal(t({ state: "diverged", message: "run git rebase" }).level, "warning");
    assert.equal(t({ state: "offline", message: "Could not reach origin." }).level, "warning");
    assert.equal(t({ state: "missing", message: "Run init." }).level, "error");
  });

  it("an older CLI gets an update prompt", () => {
    const x = syncToast(null, "o/r");
    assert.equal(x.level, "error");
    assert.match(x.text, /newer work-plan CLI/);
  });
});
