/**
 * Tests for src/webview/lenses.ts — pure lens derivation and filtering.
 *
 * Fixture:
 *   repo A (your-org/myproject):
 *     • platform-health  — blocked, blockers:[4821], issues with milestones "M1"
 *     • idea-mode        — active, no blockers, no milestones
 *   repo B (stylusnexus/work-plan-toolkit):
 *     • org-sharing      — active, no blockers, issues with milestone "v0.4.0"
 *     • docs-refresh     — active, no blockers, issues with milestones "M1" + "v0.4.0"
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import type { Export } from "../model.ts";
import { availableLenses, applyLens } from "./lenses.ts";
import type { Lens } from "./lenses.ts";

// ---------------------------------------------------------------------------
// Fixture
// ---------------------------------------------------------------------------

const exp: Export = {
  schema: 1,
  generated_at: "2026-06-07T00:00:00Z",
  tracks: [
    {
      name: "platform-health",
      repo: "your-org/myproject",
      tier: "private",
      status: "blocked",
      launch_priority: "P0",
      milestone_alignment: "M1",
      visibility: "PRIVATE",
      blockers: [4821],
      next_up: [487, 1556],
      rollup: { open: 12, closed: 8 },
      issues: [
        { number: 487,  title: "auth rate limit", state: "open",   assignee: "@alice", milestone: "M1" },
        { number: 1556, title: "session cache",   state: "open",   assignee: "@bob",   milestone: "M1" },
        { number: 2196, title: "RLS audit",       state: "closed", assignee: "—",      milestone: null },
      ],
    },
    {
      name: "idea-mode",
      repo: "your-org/myproject",
      tier: "private",
      status: "active",
      launch_priority: "P1",
      milestone_alignment: null,
      visibility: "PRIVATE",
      blockers: [],
      next_up: [4821],
      rollup: { open: 5, closed: 3 },
      issues: [
        { number: 4821, title: "OAuth scopes", state: "open",   assignee: "@carol", milestone: null },
        { number: 4830, title: "scope UI",     state: "open",   assignee: "@carol", milestone: null },
      ],
    },
    {
      name: "org-sharing",
      repo: "stylusnexus/work-plan-toolkit",
      tier: "private",
      status: "active",
      launch_priority: "P2",
      milestone_alignment: null,
      visibility: "PUBLIC",
      blockers: [],
      next_up: [87],
      rollup: { open: 3, closed: 2 },
      issues: [
        { number: 87, title: "VS Code viewer", state: "open",   assignee: "@dave", milestone: "v0.4.0" },
        { number: 74, title: "plan-status",    state: "closed", assignee: "—",     milestone: null },
      ],
    },
    {
      name: "docs-refresh",
      repo: "stylusnexus/work-plan-toolkit",
      tier: "private",
      status: "active",
      launch_priority: null,
      milestone_alignment: null,
      visibility: "PUBLIC",
      blockers: [],
      next_up: [],
      rollup: { open: 2, closed: 1 },
      issues: [
        { number: 91, title: "public repo docs", state: "closed", assignee: "@dave", milestone: "v0.4.0" },
        { number: 92, title: "contrib guide",    state: "open",   assignee: "@dave", milestone: "M1" },
      ],
    },
  ],
};

// A minimal export with NO blockers — used to verify "Blocked" category is omitted.
const expNoBlockers: Export = {
  schema: 1,
  generated_at: "2026-06-07T00:00:00Z",
  tracks: [
    {
      name: "alpha",
      repo: "stylusnexus/alpha",
      tier: "private",
      status: "active",
      launch_priority: null,
      milestone_alignment: null,
      visibility: null,
      blockers: [],
      next_up: [],
      rollup: { open: 1, closed: 0 },
      issues: [
        { number: 1, title: "thing", state: "open", assignee: "@x", milestone: null },
      ],
    },
  ],
};

// A fixture spanning every StatusCategory:
//   • blk      — blocked (blockers non-empty)
//   • blk2     — blocked (status === "blocked", no blockers array)
//   • act      — active
//   • inprog   — in-progress (maps to "active")
//   • ship     — shipped
//   • park     — parked
//   • aband    — abandoned (maps to "parked")
function mkTrack(name: string, status: string, blockers: number[]): Export["tracks"][number] {
  return {
    name,
    repo: "stylusnexus/status-fixture",
    tier: "private",
    status,
    launch_priority: null,
    milestone_alignment: null,
    visibility: null,
    blockers,
    next_up: [],
    rollup: { open: 1, closed: 0 },
    issues: [{ number: 1, title: "x", state: "open", assignee: "—", milestone: null }],
  };
}

const expStatuses: Export = {
  schema: 1,
  generated_at: "2026-06-07T00:00:00Z",
  tracks: [
    mkTrack("blk", "active", [42]),
    mkTrack("blk2", "blocked", []),
    mkTrack("act", "active", []),
    mkTrack("inprog", "in-progress", []),
    mkTrack("ship", "shipped", []),
    mkTrack("park", "parked", []),
    mkTrack("aband", "abandoned", []),
  ],
};

// ---------------------------------------------------------------------------
// availableLenses — structure & ordering
// ---------------------------------------------------------------------------

describe("availableLenses — always starts with All", () => {
  it("first choice has id='all' and kind='all'", () => {
    const choices = availableLenses(exp);
    assert.strictEqual(choices[0].id, "all");
    assert.strictEqual(choices[0].label, "All tracks");
    assert.deepStrictEqual(choices[0].lens, { kind: "all" });
  });
});

describe("availableLenses — repo lenses", () => {
  it("includes one entry per distinct repo, in first-seen order", () => {
    const choices = availableLenses(exp);
    const repoChoices = choices.filter(c => c.lens.kind === "repo");
    assert.strictEqual(repoChoices.length, 2);
    assert.deepStrictEqual(
      repoChoices.map(c => (c.lens as { kind: "repo"; repo: string }).repo),
      ["your-org/myproject", "stylusnexus/work-plan-toolkit"],
    );
  });

  it("repo labels are prefixed with 'Repo: '", () => {
    const choices = availableLenses(exp);
    const repoChoices = choices.filter(c => c.lens.kind === "repo");
    assert.ok(repoChoices.every(c => c.label.startsWith("Repo: ")));
  });

  it("repo entries appear before milestone entries", () => {
    const choices = availableLenses(exp);
    const firstRepo = choices.findIndex(c => c.lens.kind === "repo");
    const firstMilestone = choices.findIndex(c => c.lens.kind === "milestone");
    assert.ok(firstRepo < firstMilestone, "repos should come before milestones");
  });
});

describe("availableLenses — milestone lenses", () => {
  it("includes distinct milestones in first-seen (track/issue) order", () => {
    const choices = availableLenses(exp);
    const milestoneChoices = choices.filter(c => c.lens.kind === "milestone");
    const milestones = milestoneChoices.map(
      c => (c.lens as { kind: "milestone"; milestone: string }).milestone,
    );
    // M1 appears first (platform-health/issue 487), v0.4.0 appears later (org-sharing/issue 87)
    assert.deepStrictEqual(milestones, ["M1", "v0.4.0"]);
  });

  it("no duplicate milestones even when the same milestone appears in multiple tracks", () => {
    const choices = availableLenses(exp);
    const milestoneChoices = choices.filter(c => c.lens.kind === "milestone");
    const milestones = milestoneChoices.map(
      c => (c.lens as { kind: "milestone"; milestone: string }).milestone,
    );
    const unique = [...new Set(milestones)];
    assert.deepStrictEqual(milestones, unique);
  });

  it("milestone labels are prefixed with 'Milestone: '", () => {
    const choices = availableLenses(exp);
    const milestoneChoices = choices.filter(c => c.lens.kind === "milestone");
    assert.ok(milestoneChoices.every(c => c.label.startsWith("Milestone: ")));
  });

  it("null milestones are excluded", () => {
    const choices = availableLenses(exp);
    const milestoneChoices = choices.filter(c => c.lens.kind === "milestone");
    const milestones = milestoneChoices.map(
      c => (c.lens as { kind: "milestone"; milestone: string }).milestone,
    );
    assert.ok(!milestones.includes("null"), "null milestone should not appear");
    assert.ok(milestones.every(m => m !== null), "no null values in milestone list");
  });
});

describe("availableLenses — blocked lens", () => {
  it("includes 'Blocked tracks' when at least one track has blockers", () => {
    const choices = availableLenses(exp);
    const blockedChoice = choices.find(c => c.lens.kind === "blocked");
    assert.ok(blockedChoice !== undefined, "Expected a 'blocked' lens choice");
    assert.strictEqual(blockedChoice.label, "Blocked tracks");
  });

  it("'Blocked tracks' is the LAST entry", () => {
    const choices = availableLenses(exp);
    const last = choices[choices.length - 1];
    assert.strictEqual(last.lens.kind, "blocked");
  });

  it("OMITS 'Blocked tracks' when no track has blockers", () => {
    const choices = availableLenses(expNoBlockers);
    const blockedChoice = choices.find(c => c.lens.kind === "blocked");
    assert.strictEqual(
      blockedChoice,
      undefined,
      "Should not include blocked lens when no track has blockers",
    );
  });
});

describe("availableLenses — status lenses", () => {
  it("includes Status: Active/Shipped/Parked in that order when all categories have members", () => {
    const choices = availableLenses(expStatuses);
    const statusChoices = choices.filter(c => c.lens.kind === "status");
    assert.deepStrictEqual(
      statusChoices.map(c => (c.lens as { kind: "status"; status: string }).status),
      ["active", "shipped", "parked"],
    );
    assert.deepStrictEqual(
      statusChoices.map(c => c.label),
      ["Status: Active", "Status: Shipped", "Status: Parked"],
    );
    assert.deepStrictEqual(
      statusChoices.map(c => c.id),
      ["status:active", "status:shipped", "status:parked"],
    );
  });

  it("never surfaces a 'blocked' status lens (blocked has its own standalone lens)", () => {
    const choices = availableLenses(expStatuses);
    const blockedStatus = choices.find(
      c => c.lens.kind === "status" && (c.lens as { status: string }).status === "blocked",
    );
    assert.strictEqual(blockedStatus, undefined);
  });

  it("status lenses appear after milestone lenses and before the standalone Blocked lens", () => {
    const choices = availableLenses(exp);
    const lastMilestone = choices.map(c => c.lens.kind).lastIndexOf("milestone");
    const firstStatus = choices.findIndex(c => c.lens.kind === "status");
    const blockedIdx = choices.findIndex(c => c.lens.kind === "blocked");
    assert.ok(firstStatus > lastMilestone, "status should come after milestones");
    assert.ok(firstStatus < blockedIdx, "status should come before the standalone Blocked lens");
  });

  it("omits a status category when no track falls in it (only-shipped fixture)", () => {
    const onlyShipped: Export = {
      schema: 1,
      generated_at: "2026-06-07T00:00:00Z",
      tracks: [mkTrack("s1", "shipped", []), mkTrack("s2", "shipped", [])],
    };
    const choices = availableLenses(onlyShipped);
    const statusKinds = choices
      .filter(c => c.lens.kind === "status")
      .map(c => (c.lens as { status: string }).status);
    assert.deepStrictEqual(statusKinds, ["shipped"]);
  });

  it("omits all status lenses when every track is blocked", () => {
    const allBlocked: Export = {
      schema: 1,
      generated_at: "2026-06-07T00:00:00Z",
      tracks: [mkTrack("b1", "active", [7]), mkTrack("b2", "blocked", [])],
    };
    const choices = availableLenses(allBlocked);
    const statusChoices = choices.filter(c => c.lens.kind === "status");
    assert.strictEqual(statusChoices.length, 0);
  });
});

describe("availableLenses — determinism", () => {
  it("returns identical output on repeated calls", () => {
    const a = availableLenses(exp);
    const b = availableLenses(exp);
    assert.deepStrictEqual(a, b);
  });

  it("returns exactly all + 2 repos + 2 milestones + 1 status(active) + 1 blocked = 7 choices for main fixture", () => {
    const choices = availableLenses(exp);
    assert.strictEqual(choices.length, 7);
  });

  it("returns exactly all + 1 repo + 1 status(active) = 3 choices for no-blocker, no-milestone fixture", () => {
    const choices = availableLenses(expNoBlockers);
    assert.strictEqual(choices.length, 3);
  });
});

// ---------------------------------------------------------------------------
// applyLens — correctness
// ---------------------------------------------------------------------------

describe("applyLens — kind:all", () => {
  it("returns all tracks unchanged", () => {
    const result = applyLens(exp, { kind: "all" });
    assert.strictEqual(result.tracks.length, exp.tracks.length);
    assert.deepStrictEqual(
      result.tracks.map(t => t.name),
      exp.tracks.map(t => t.name),
    );
  });

  it("preserves schema and generated_at", () => {
    const result = applyLens(exp, { kind: "all" });
    assert.strictEqual(result.schema, exp.schema);
    assert.strictEqual(result.generated_at, exp.generated_at);
  });

  it("returns a new object (does not mutate input)", () => {
    const result = applyLens(exp, { kind: "all" });
    assert.ok(result !== exp, "applyLens should return a new Export object");
  });

  it("the input tracks array is unchanged after call", () => {
    const originalTrackCount = exp.tracks.length;
    applyLens(exp, { kind: "all" });
    assert.strictEqual(exp.tracks.length, originalTrackCount);
  });
});

describe("applyLens — kind:repo", () => {
  it("keeps only tracks with matching repo", () => {
    const lens: Lens = { kind: "repo", repo: "your-org/myproject" };
    const result = applyLens(exp, lens);
    assert.strictEqual(result.tracks.length, 2);
    assert.ok(result.tracks.every(t => t.repo === "your-org/myproject"));
  });

  it("returns empty tracks for an unknown repo", () => {
    const lens: Lens = { kind: "repo", repo: "stylusnexus/does-not-exist" };
    const result = applyLens(exp, lens);
    assert.strictEqual(result.tracks.length, 0);
  });

  it("tracks include all their issues (no per-issue surgery)", () => {
    const lens: Lens = { kind: "repo", repo: "your-org/myproject" };
    const result = applyLens(exp, lens);
    const platformHealth = result.tracks.find(t => t.name === "platform-health");
    assert.ok(platformHealth !== undefined);
    assert.strictEqual(platformHealth.issues.length, 3);
  });

  it("does not mutate exp.tracks", () => {
    const before = exp.tracks.map(t => t.name);
    applyLens(exp, { kind: "repo", repo: "your-org/myproject" });
    assert.deepStrictEqual(exp.tracks.map(t => t.name), before);
  });
});

describe("applyLens — kind:milestone", () => {
  it("keeps only tracks that have at least one issue with the matching milestone", () => {
    const lens: Lens = { kind: "milestone", milestone: "M1" };
    const result = applyLens(exp, lens);
    // platform-health has M1 issues; docs-refresh also has M1; idea-mode and org-sharing do NOT
    assert.strictEqual(result.tracks.length, 2);
    const names = result.tracks.map(t => t.name);
    assert.ok(names.includes("platform-health"), "platform-health should be included");
    assert.ok(names.includes("docs-refresh"), "docs-refresh should be included");
    assert.ok(!names.includes("idea-mode"), "idea-mode should be excluded (no M1 issues)");
    assert.ok(!names.includes("org-sharing"), "org-sharing should be excluded (no M1 issues)");
  });

  it("tracks matching v0.4.0 milestone are kept whole", () => {
    const lens: Lens = { kind: "milestone", milestone: "v0.4.0" };
    const result = applyLens(exp, lens);
    // org-sharing and docs-refresh both have v0.4.0 issues
    const names = result.tracks.map(t => t.name);
    assert.ok(names.includes("org-sharing"), "org-sharing has v0.4.0");
    assert.ok(names.includes("docs-refresh"), "docs-refresh has v0.4.0");
    // issues are kept whole even if some don't match the milestone
    const orgSharing = result.tracks.find(t => t.name === "org-sharing");
    assert.ok(orgSharing !== undefined);
    assert.strictEqual(orgSharing.issues.length, 2, "all issues kept, not just milestone-matching ones");
  });

  it("returns empty tracks for unknown milestone", () => {
    const lens: Lens = { kind: "milestone", milestone: "nonexistent" };
    const result = applyLens(exp, lens);
    assert.strictEqual(result.tracks.length, 0);
  });

  it("does not mutate exp.tracks", () => {
    const before = exp.tracks.map(t => t.name);
    applyLens(exp, { kind: "milestone", milestone: "M1" });
    assert.deepStrictEqual(exp.tracks.map(t => t.name), before);
  });
});

describe("applyLens — kind:blocked", () => {
  it("keeps only tracks with non-empty blockers array", () => {
    const lens: Lens = { kind: "blocked" };
    const result = applyLens(exp, lens);
    // Only platform-health has blockers in main fixture
    assert.strictEqual(result.tracks.length, 1);
    assert.strictEqual(result.tracks[0].name, "platform-health");
  });

  it("excluded tracks have no blockers", () => {
    const result = applyLens(exp, { kind: "blocked" });
    assert.ok(result.tracks.every(t => t.blockers.length > 0));
  });

  it("returns empty tracks when no track has blockers", () => {
    const result = applyLens(expNoBlockers, { kind: "blocked" });
    assert.strictEqual(result.tracks.length, 0);
  });

  it("does not mutate exp.tracks", () => {
    const before = exp.tracks.map(t => t.name);
    applyLens(exp, { kind: "blocked" });
    assert.deepStrictEqual(exp.tracks.map(t => t.name), before);
  });
});

describe("applyLens — kind:status", () => {
  it("status:shipped keeps only shipped tracks", () => {
    const result = applyLens(expStatuses, { kind: "status", status: "shipped" });
    assert.deepStrictEqual(result.tracks.map(t => t.name), ["ship"]);
  });

  it("status:parked keeps parked AND abandoned tracks", () => {
    const result = applyLens(expStatuses, { kind: "status", status: "parked" });
    assert.deepStrictEqual(result.tracks.map(t => t.name), ["park", "aband"]);
  });

  it("status:active keeps active AND in-progress, but excludes blocked", () => {
    const result = applyLens(expStatuses, { kind: "status", status: "active" });
    // act + inprog are active; blk/blk2 are blocked → excluded
    assert.deepStrictEqual(result.tracks.map(t => t.name), ["act", "inprog"]);
  });

  it("status:blocked matches the same tracks as the standalone blocked classifier", () => {
    const result = applyLens(expStatuses, { kind: "status", status: "blocked" });
    // blk (blockers non-empty) + blk2 (status === "blocked")
    assert.deepStrictEqual(result.tracks.map(t => t.name), ["blk", "blk2"]);
  });

  it("keeps matching tracks whole (all issues retained)", () => {
    const result = applyLens(expStatuses, { kind: "status", status: "shipped" });
    assert.strictEqual(result.tracks[0].issues.length, 1);
  });

  it("preserves schema and generated_at", () => {
    const result = applyLens(expStatuses, { kind: "status", status: "active" });
    assert.strictEqual(result.schema, expStatuses.schema);
    assert.strictEqual(result.generated_at, expStatuses.generated_at);
  });

  it("does not mutate the input export's tracks", () => {
    const before = JSON.stringify(expStatuses.tracks);
    applyLens(expStatuses, { kind: "status", status: "active" });
    applyLens(expStatuses, { kind: "status", status: "shipped" });
    applyLens(expStatuses, { kind: "status", status: "parked" });
    assert.strictEqual(JSON.stringify(expStatuses.tracks), before);
  });
});

describe("applyLens — immutability", () => {
  it("returned Export is a new object for all lens kinds", () => {
    const lenses: Lens[] = [
      { kind: "all" },
      { kind: "repo", repo: "your-org/myproject" },
      { kind: "milestone", milestone: "M1" },
      { kind: "status", status: "active" },
      { kind: "blocked" },
    ];
    for (const lens of lenses) {
      const result = applyLens(exp, lens);
      assert.ok(result !== exp, `applyLens with kind=${lens.kind} should return a new object`);
    }
  });

  it("exp.tracks is unchanged after multiple applyLens calls", () => {
    const before = JSON.stringify(exp.tracks);
    applyLens(exp, { kind: "all" });
    applyLens(exp, { kind: "repo", repo: "your-org/myproject" });
    applyLens(exp, { kind: "milestone", milestone: "M1" });
    applyLens(exp, { kind: "blocked" });
    assert.strictEqual(JSON.stringify(exp.tracks), before);
  });
});

describe("applyLens — untracked forwarding (#99 regression)", () => {
  // The tree always renders from the lens-filtered export, so applyLens MUST
  // forward the additive `untracked` field — otherwise the Untracked bucket
  // vanishes under every lens, including "all".
  const withUntracked: Export = {
    ...exp,
    untracked: [
      {
        repo: "your-org/myproject",
        issues: [
          { number: 999, title: "stray", state: "open", assignee: "—", milestone: null },
        ],
      },
    ],
  };

  it("forwards untracked unchanged under the 'all' lens", () => {
    const result = applyLens(withUntracked, { kind: "all" });
    assert.deepStrictEqual(result.untracked, withUntracked.untracked);
  });

  it("forwards untracked unchanged under a 'repo' lens", () => {
    const result = applyLens(withUntracked, { kind: "repo", repo: "your-org/myproject" });
    assert.deepStrictEqual(result.untracked, withUntracked.untracked);
  });

  it("leaves untracked undefined when the source export has none", () => {
    const result = applyLens(exp, { kind: "all" });
    assert.strictEqual(result.untracked, undefined);
  });
});

describe("applyLens — vscode-free import check", () => {
  it("applyLens and availableLenses return values (basic smoke test for import)", () => {
    // This test implicitly verifies that lenses.ts has no vscode imports:
    // if it did, node:test would fail to load the module.
    assert.ok(typeof applyLens === "function");
    assert.ok(typeof availableLenses === "function");
  });
});
