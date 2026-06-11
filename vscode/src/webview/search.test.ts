/**
 * Tests for src/webview/search.ts — wildcard grammar + issue matching.
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import type { Export } from "../model.ts";
import { wildcardToRegExp, searchIssues } from "./search.ts";

// ---------------------------------------------------------------------------
// wildcardToRegExp — grammar
// ---------------------------------------------------------------------------

describe("wildcardToRegExp — null cases", () => {
  it("returns null for an empty string", () => {
    assert.strictEqual(wildcardToRegExp(""), null);
  });
  it("returns null for whitespace only", () => {
    assert.strictEqual(wildcardToRegExp("   "), null);
  });
  it("returns null for a single %", () => {
    assert.strictEqual(wildcardToRegExp("%"), null);
  });
  it("returns null for %% (wildcards only, no literal)", () => {
    assert.strictEqual(wildcardToRegExp("%%"), null);
  });
});

describe("wildcardToRegExp — grammar rows", () => {
  it("%depends% → contains (matches anywhere)", () => {
    const re = wildcardToRegExp("%depends%")!;
    assert.ok(re.test("issue-level depends-on tagging"));
    assert.ok(re.test("depends at the start"));
    assert.ok(re.test("ends with depends"));
    assert.ok(!re.test("unrelated title"));
  });

  it("depends% → starts-with", () => {
    const re = wildcardToRegExp("depends%")!;
    assert.ok(re.test("depends-on audit"));
    assert.ok(re.test("DEPENDS heavily on X")); // case-insensitive prefix
    assert.ok(!re.test("Dependency review")); // "depende…" ≠ "depends…"
    assert.ok(!re.test("issue-level depends")); // not at the start
  });

  it("%depends → ends-with", () => {
    const re = wildcardToRegExp("%depends")!;
    assert.ok(re.test("issue-level depends"));
    assert.ok(!re.test("depends on this")); // not at the end
  });

  it("bare depends → contains (same as %depends%)", () => {
    const re = wildcardToRegExp("depends")!;
    assert.ok(re.test("issue-level depends-on"));
    assert.ok(re.test("depends here"));
    assert.ok(!re.test("unrelated"));
  });
});

describe("wildcardToRegExp — case-insensitivity", () => {
  it("matches regardless of case in either direction", () => {
    const re = wildcardToRegExp("DePeNdS")!;
    assert.ok(re.test("the DEPENDS keyword"));
    assert.ok(re.test("lowercase depends"));
  });
});

describe("wildcardToRegExp — regex metacharacters are literal", () => {
  it("treats . as a literal dot, not any-char", () => {
    const re = wildcardToRegExp("v1.0")!;
    assert.ok(re.test("v1.0"));
    assert.ok(!re.test("v1x0")); // '.' must not match 'x'
  });

  it("treats (, +, [ ] as literals", () => {
    const re = wildcardToRegExp("%fix (a+b) [x]%")!;
    assert.ok(re.test("a quick fix (a+b) [x] here"));
    assert.ok(!re.test("fix ab x"));
  });

  it("a query that is only metacharacters matches itself literally", () => {
    const re = wildcardToRegExp("c++")!;
    assert.ok(re.test("c++"));
    assert.ok(!re.test("cccc"));
  });
});

// ---------------------------------------------------------------------------
// searchIssues — over a fixture
// ---------------------------------------------------------------------------

const exp: Export = {
  schema: 1,
  generated_at: "2026-06-11T00:00:00Z",
  tracks: [
    {
      name: "platform-health",
      repo: "your-org/myproject",
      tier: "private",
      status: "active",
      launch_priority: "P0",
      milestone_alignment: null,
      visibility: "PRIVATE",
      blockers: [],
      next_up: [],
      depends_on: [],
      rollup: { open: 2, closed: 1 },
      issues: [
        { number: 487, title: "Auth rate limit", state: "open", assignee: "@alice", milestone: "M1" },
        { number: 488, title: "depends-on cleanup", state: "closed", assignee: "—", milestone: null },
      ],
    },
    {
      name: "viewer",
      repo: "your-org/myproject",
      tier: "private",
      status: "active",
      launch_priority: "P1",
      milestone_alignment: null,
      visibility: "PUBLIC",
      blockers: [],
      next_up: [],
      depends_on: [],
      rollup: { open: 1, closed: 0 },
      issues: [
        { number: 272, title: "issue search with depends", state: "open", assignee: "@bob", milestone: "v2.0.0" },
      ],
    },
  ],
  untracked: [
    {
      repo: "your-org/other",
      issues: [
        { number: 900, title: "DEPENDS graph rewrite", state: "open", assignee: "—", milestone: null },
        { number: 901, title: "unrelated chore", state: "open", assignee: "—", milestone: null },
      ],
    },
  ],
};

describe("searchIssues — matching across tracks + untracked", () => {
  it("returns [] for a null/empty query", () => {
    assert.deepStrictEqual(searchIssues(exp, ""), []);
    assert.deepStrictEqual(searchIssues(exp, "%"), []);
  });

  it("finds 'depends' across tracked and untracked issues, case-insensitive", () => {
    const hits = searchIssues(exp, "depends");
    const nums = hits.map(h => h.number).sort((a, b) => a - b);
    assert.deepStrictEqual(nums, [272, 488, 900]);
  });

  it("tags untracked hits with track=null and carries the right repo", () => {
    const hit = searchIssues(exp, "%graph rewrite").find(h => h.number === 900)!;
    assert.strictEqual(hit.track, null);
    assert.strictEqual(hit.repo, "your-org/other");
  });

  it("carries the owning track for tracked hits", () => {
    const hit = searchIssues(exp, "issue search%").find(h => h.number === 272)!;
    assert.strictEqual(hit.track, "viewer");
  });

  it("starts-with anchor excludes mid-title matches", () => {
    // Starts-with: #488 "depends-on cleanup" and #900 "DEPENDS graph rewrite"
    // (case-insensitive) qualify; #272 "issue search with depends" does NOT.
    const hits = searchIssues(exp, "depends%");
    assert.deepStrictEqual(hits.map(h => h.number).sort((a, b) => a - b), [488, 900]);
  });

  it("no matches → empty array (not an error)", () => {
    assert.deepStrictEqual(searchIssues(exp, "%nonexistent-term%"), []);
  });
});
