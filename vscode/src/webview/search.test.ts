/**
 * Tests for src/webview/search.ts — wildcard grammar + issue matching.
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import type { Export } from "../model.ts";
import {
  wildcardToRegExp, searchIssues, parseSearchQuery, isLabelQuery, exportCarriesLabels,
} from "./search.ts";
import { makeIssue, makeTrack } from "../testFixtures.ts";

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
    makeTrack({
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
        makeIssue({ number: 487, title: "Auth rate limit", state: "open", assignee: "@alice", milestone: "M1" }),
        makeIssue({ number: 488, title: "depends-on cleanup", state: "closed", assignee: "—", milestone: null }),
      ],
    }),
    makeTrack({
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
        makeIssue({ number: 272, title: "issue search with depends", state: "open", assignee: "@bob", milestone: "v2.0.0" }),
      ],
    }),
  ],
  untracked: [
    {
      repo: "your-org/other",
      issues: [
        makeIssue({ number: 900, title: "DEPENDS graph rewrite", state: "open", assignee: "—", milestone: null }),
        makeIssue({ number: 901, title: "unrelated chore", state: "open", assignee: "—", milestone: null }),
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


// ---------------------------------------------------------------------------
// Label search (#429)
// ---------------------------------------------------------------------------

function issueWith(number: number, title: string, labels?: string[]) {
  return makeIssue({ number, title, ...(labels !== undefined && { labels }) });
}

function trackWith(name: string, repo: string, issues: ReturnType<typeof issueWith>[]) {
  return makeTrack({ name, repo, rollup: { open: issues.length, closed: 0 }, issues });
}

const labelled: Export = {
  schema: 1,
  generated_at: "2026-10-05T00:00:00Z",
  tracks: [
    trackWith("platform", "org/app", [
      issueWith(1, "Rotate signing keys", ["security", "priority/P0"]),
      issueWith(2, "Tidy docs", ["documentation"]),
      issueWith(3, "Security review notes", []),          // "security" only in the TITLE
    ]),
  ],
  untracked: [
    { repo: "org/app", issues: [
      issueWith(10, "Untriaged crash", ["Security", "needs-triage"]),
      issueWith(11, "Another", ["area/security-ui"]),
    ] },
  ],
};

describe("parseSearchQuery / isLabelQuery", () => {
  it("a bare query is a title search, untouched", () => {
    assert.deepEqual(parseSearchQuery("fix%"), { fields: ["title"], pattern: "fix%" });
    assert.equal(isLabelQuery("fix%"), false);
    assert.equal(isLabelQuery("my label: thing"), false); // not a prefix
  });

  it("label: scopes to labels; everything after it is the pattern", () => {
    assert.deepEqual(parseSearchQuery("label:security"), { fields: ["labels"], pattern: "security" });
    assert.deepEqual(parseSearchQuery("  LABEL:good first issue"), { fields: ["labels"], pattern: "good first issue" });
    assert.equal(isLabelQuery("Label:x"), true);
  });
});

describe("searchIssues — label search", () => {
  const nums = (q: string) => searchIssues(labelled, q).map(h => h.number);

  it("covers tracked AND untracked issues, case-insensitively", () => {
    assert.deepEqual(nums("label:security"), [1, 10, 11]);
    assert.deepEqual(nums("label:SECURITY"), [1, 10, 11]);
  });

  it("honors the % wildcards on each label", () => {
    assert.deepEqual(nums("label:priority/%"), [1]);        // starts-with
    assert.deepEqual(nums("label:%/P0"), [1]);              // ends-with
    assert.deepEqual(nums("label:%triage%"), [10]);         // contains
    assert.deepEqual(nums("label:sec%"), [1, 10]);          // starts-with: not "area/security-ui"
  });

  it("matches one whole label pattern, not words spread across labels", () => {
    assert.deepEqual(nums("label:security P0"), []);
  });

  it("a label query never matches titles, and a bare query never matches labels", () => {
    assert.ok(!nums("label:security").includes(3));          // title-only "Security review notes"
    assert.deepEqual(nums("%notes%"), [3]);
    assert.deepEqual(nums("needs-triage"), []);              // label text, bare query → title only
  });

  it("bare queries behave exactly as before", () => {
    assert.deepEqual(nums("security"), [3]);
    assert.deepEqual(nums("tidy%"), [2]);
  });

  it("an empty or wildcard-only label pattern matches nothing", () => {
    for (const q of ["label:", "label:   ", "label:%", "label:%%"]) assert.deepEqual(nums(q), [], q);
  });

  it("regex metacharacters in a label pattern are literal", () => {
    assert.deepEqual(nums("label:a.b"), []);
    assert.deepEqual(nums("label:(security"), []);
  });

  it("hits carry the labels", () => {
    const hit = searchIssues(labelled, "label:priority/%")[0];
    assert.deepEqual(hit.labels, ["security", "priority/P0"]);
    assert.equal(hit.track, "platform");
    assert.equal(searchIssues(labelled, "label:needs-triage")[0].track, null);
  });

  it("an explicit fields argument still overrides query parsing", () => {
    assert.deepEqual(searchIssues(labelled, "security", ["labels"]).map(h => h.number), [1, 10, 11]);
    assert.deepEqual(searchIssues(labelled, "label:security", ["title"]).map(h => h.number), []);
  });
});

describe("searchIssues — an export from an older CLI", () => {
  const old: Export = {
    schema: 1, generated_at: "t",
    tracks: [trackWith("t", "org/app", [issueWith(1, "Rotate keys"), issueWith(2, "Fix auth")])],
  };

  it("keeps bare title search working", () => {
    assert.deepEqual(searchIssues(old, "auth").map(h => h.number), [2]);
  });

  it("a label query finds nothing and never throws", () => {
    assert.deepEqual(searchIssues(old, "label:security"), []);
  });

  it("hits omit labels rather than inventing an empty list", () => {
    assert.equal("labels" in searchIssues(old, "auth")[0], false);
  });

  it("exportCarriesLabels tells 'no labels exported' from 'issues have no labels'", () => {
    assert.equal(exportCarriesLabels(old), false);
    assert.equal(exportCarriesLabels({ ...old, tracks: [trackWith("t", "o/r", [issueWith(1, "x", [])])] }), true);
    assert.equal(exportCarriesLabels({ ...old, tracks: [], untracked: [{ repo: "o/r", issues: [issueWith(1, "x", ["a"])] }] }), true);
    assert.equal(exportCarriesLabels({ schema: 1, generated_at: "t", tracks: [] }), false);
  });
});
