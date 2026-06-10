import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  statusCategory,
  trackHint,
  buildTree,
  shouldExpandRepos,
  sortTracks,
  repoDescription,
} from "./treeModel.ts";
import type { RepoNode, TrackNode } from "./treeModel.ts";
import type { Export, Track, Issue } from "./model.ts";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeIssue(overrides: Partial<Issue> = {}): Issue {
  return {
    number: 1,
    title: "test issue",
    state: "open",
    assignee: "@eve",
    milestone: null,
    ...overrides,
  };
}

function makeTrack(overrides: Partial<Track> = {}): Track {
  return {
    name: "platform-health",
    repo: "your-org/myproject",
    tier: "private",
    status: "active",
    launch_priority: "P2",
    milestone_alignment: "v1",
    visibility: "PRIVATE",
    blockers: [],
    next_up: [],
    rollup: { open: 0, closed: 0 },
    issues: [],
    ...overrides,
  };
}

/** Mockup fixture: two repos, three tracks. */
const MOCKUP_EXPORT: Export = {
  schema: 1,
  generated_at: "2026-06-07T00:00:00Z",
  tracks: [
    {
      name: "platform-health",
      repo: "your-org/myproject",
      tier: "private",
      status: "blocked",
      launch_priority: "P1",
      milestone_alignment: "v1",
      visibility: "PRIVATE",
      blockers: [4821],
      next_up: [487, 1556],
      rollup: { open: 12, closed: 8 },
      issues: [makeIssue({ number: 4821 })],
    },
    {
      name: "idea-mode",
      repo: "your-org/myproject",
      tier: "private",
      status: "active",
      launch_priority: "P2",
      milestone_alignment: "v2",
      visibility: "PRIVATE",
      blockers: [],
      next_up: [4821],
      rollup: { open: 3, closed: 5 },
      issues: [makeIssue({ number: 4821 })],
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
      rollup: { open: 2, closed: 6 },
      issues: [makeIssue({ number: 87 })],
    },
  ],
};

// ---------------------------------------------------------------------------
// statusCategory
// ---------------------------------------------------------------------------

describe("statusCategory", () => {
  test("blocked status → 'blocked'", () => {
    const track = makeTrack({ status: "blocked", blockers: [] });
    assert.equal(statusCategory(track), "blocked");
  });

  test("non-empty blockers array overrides status → 'blocked'", () => {
    const track = makeTrack({ status: "active", blockers: [4821] });
    assert.equal(statusCategory(track), "blocked");
  });

  test("active status WITH a blocker → 'blocked' (override)", () => {
    const track = makeTrack({ status: "active", blockers: [99] });
    assert.equal(statusCategory(track), "blocked");
  });

  test("shipped status → 'shipped'", () => {
    const track = makeTrack({ status: "shipped", blockers: [] });
    assert.equal(statusCategory(track), "shipped");
  });

  test("parked status → 'parked'", () => {
    const track = makeTrack({ status: "parked", blockers: [] });
    assert.equal(statusCategory(track), "parked");
  });

  test("abandoned status → 'parked'", () => {
    const track = makeTrack({ status: "abandoned", blockers: [] });
    assert.equal(statusCategory(track), "parked");
  });

  test("active status with no blockers → 'active'", () => {
    const track = makeTrack({ status: "active", blockers: [] });
    assert.equal(statusCategory(track), "active");
  });

  test("in-progress status → 'active'", () => {
    const track = makeTrack({ status: "in-progress", blockers: [] });
    assert.equal(statusCategory(track), "active");
  });

  test("unknown status → 'active' (fallback)", () => {
    const track = makeTrack({ status: "something-new", blockers: [] });
    assert.equal(statusCategory(track), "active");
  });
});

// ---------------------------------------------------------------------------
// trackHint
// ---------------------------------------------------------------------------

describe("trackHint", () => {
  test("blockers non-empty → '⛔ #<first blocker>'", () => {
    const track = makeTrack({ blockers: [4821, 99], next_up: [487] });
    assert.equal(trackHint(track), "⛔ #4821");
  });

  test("no blockers, next_up non-empty → '→ #<first next_up>'", () => {
    const track = makeTrack({ blockers: [], next_up: [87] });
    assert.equal(trackHint(track), "→ #87");
  });

  test("no blockers, no next_up → null", () => {
    const track = makeTrack({ blockers: [], next_up: [] });
    assert.equal(trackHint(track), null);
  });

  test("blockers take precedence over next_up", () => {
    const track = makeTrack({ blockers: [100], next_up: [200] });
    assert.equal(trackHint(track), "⛔ #100");
  });
});

// ---------------------------------------------------------------------------
// buildTree — mockup fixture assertions
// ---------------------------------------------------------------------------

describe("buildTree", () => {
  test("returns 2 repo nodes in first-seen order", () => {
    const tree = buildTree(MOCKUP_EXPORT);
    assert.equal(tree.length, 2);
    assert.equal(tree[0].repo, "your-org/myproject");
    assert.equal(tree[1].repo, "stylusnexus/work-plan-toolkit");
  });

  test("myproject isPublic:false (all PRIVATE tracks)", () => {
    const tree = buildTree(MOCKUP_EXPORT);
    assert.equal(tree[0].isPublic, false);
  });

  test("work-plan-toolkit isPublic:true (has PUBLIC track)", () => {
    const tree = buildTree(MOCKUP_EXPORT);
    assert.equal(tree[1].isPublic, true);
  });

  test("myproject has 2 tracks in first-seen order", () => {
    const tree = buildTree(MOCKUP_EXPORT);
    const myproject = tree[0];
    assert.equal(myproject.tracks.length, 2);
    assert.equal(myproject.tracks[0].name, "platform-health");
    assert.equal(myproject.tracks[1].name, "idea-mode");
  });

  test("work-plan-toolkit has 1 track", () => {
    const tree = buildTree(MOCKUP_EXPORT);
    assert.equal(tree[1].tracks.length, 1);
    assert.equal(tree[1].tracks[0].name, "org-sharing");
  });

  test("platform-health: category 'blocked', open 12, hint '⛔ #4821'", () => {
    const tree = buildTree(MOCKUP_EXPORT);
    const platformHealth = tree[0].tracks[0];
    assert.equal(platformHealth.name, "platform-health");
    assert.equal(platformHealth.category, "blocked");
    assert.equal(platformHealth.open, 12);
    assert.equal(platformHealth.hint, "⛔ #4821");
  });

  test("idea-mode: category 'active', hint '→ #4821'", () => {
    const tree = buildTree(MOCKUP_EXPORT);
    const ideaMode = tree[0].tracks[1];
    assert.equal(ideaMode.name, "idea-mode");
    assert.equal(ideaMode.category, "active");
    assert.equal(ideaMode.hint, "→ #4821");
  });

  test("org-sharing: category 'active', hint '→ #87'", () => {
    const tree = buildTree(MOCKUP_EXPORT);
    const orgSharing = tree[1].tracks[0];
    assert.equal(orgSharing.name, "org-sharing");
    assert.equal(orgSharing.category, "active");
    assert.equal(orgSharing.hint, "→ #87");
  });

  test("track with empty blockers + next_up → hint null", () => {
    const exp: Export = {
      schema: 1,
      generated_at: "2026-06-07T00:00:00Z",
      tracks: [
        makeTrack({ name: "empty-track", blockers: [], next_up: [] }),
      ],
    };
    const tree = buildTree(exp);
    assert.equal(tree[0].tracks[0].hint, null);
  });

  test("track with repo:null buckets under '(no repo)' node", () => {
    const exp: Export = {
      schema: 1,
      generated_at: "2026-06-07T00:00:00Z",
      tracks: [
        makeTrack({ name: "orphan-track", repo: null as unknown as string, blockers: [], next_up: [] }),
      ],
    };
    const tree = buildTree(exp);
    assert.equal(tree.length, 1);
    assert.equal(tree[0].repo, "(no repo)");
    assert.equal(tree[0].isPublic, false);
    assert.equal(tree[0].tracks[0].name, "orphan-track");
  });

  test("track with empty string repo buckets under '(no repo)' node", () => {
    const exp: Export = {
      schema: 1,
      generated_at: "2026-06-07T00:00:00Z",
      tracks: [
        makeTrack({ name: "empty-repo-track", repo: "", blockers: [], next_up: [] }),
      ],
    };
    const tree = buildTree(exp);
    assert.equal(tree[0].repo, "(no repo)");
  });

  test("repo node isPublic:true if ANY track has visibility PUBLIC", () => {
    const exp: Export = {
      schema: 1,
      generated_at: "2026-06-07T00:00:00Z",
      tracks: [
        makeTrack({ name: "t1", repo: "org/repo", visibility: "PRIVATE" }),
        makeTrack({ name: "t2", repo: "org/repo", visibility: "PUBLIC" }),
      ],
    };
    const tree = buildTree(exp);
    assert.equal(tree[0].isPublic, true);
  });

  test("repo node tier from first track, fallback 'private'", () => {
    const exp: Export = {
      schema: 1,
      generated_at: "2026-06-07T00:00:00Z",
      tracks: [
        makeTrack({ name: "t1", repo: "org/repo", tier: "enterprise" }),
      ],
    };
    const tree = buildTree(exp);
    assert.equal(tree[0].tier, "enterprise");
  });

  test("TrackNode kind is 'track', RepoNode kind is 'repo'", () => {
    const tree = buildTree(MOCKUP_EXPORT);
    assert.equal(tree[0].kind, "repo");
    assert.equal(tree[0].tracks[0].kind, "track");
  });

  test("TrackNode.track points back to the raw Track object", () => {
    const tree = buildTree(MOCKUP_EXPORT);
    const platformHealth = tree[0].tracks[0];
    assert.strictEqual(platformHealth.track, MOCKUP_EXPORT.tracks[0]);
  });

  test("preserves first-seen repo order, NOT alphabetical", () => {
    // Add repos in Z, A order — should stay Z, A
    const exp: Export = {
      schema: 1,
      generated_at: "2026-06-07T00:00:00Z",
      tracks: [
        makeTrack({ name: "z-track", repo: "org/z-repo" }),
        makeTrack({ name: "a-track", repo: "org/a-repo" }),
      ],
    };
    const tree = buildTree(exp);
    assert.equal(tree[0].repo, "org/z-repo");
    assert.equal(tree[1].repo, "org/a-repo");
  });

  test("empty export → empty tree", () => {
    const exp: Export = { schema: 1, generated_at: "2026-06-07T00:00:00Z", tracks: [] };
    const tree = buildTree(exp);
    assert.equal(tree.length, 0);
  });

  // --- untracked ---

  test("MOCKUP_EXPORT (no untracked key) → all repo nodes have untracked:[]", () => {
    const tree = buildTree(MOCKUP_EXPORT);
    for (const node of tree) {
      assert.deepEqual(node.untracked, []);
    }
  });

  test("untracked key present: matched repo gets its issues; unmatched repo gets []", () => {
    const untrackedIssue = makeIssue({ number: 99, title: "orphan", state: "open" });
    const exp: Export = {
      schema: 1,
      generated_at: "2026-06-07T00:00:00Z",
      tracks: [
        makeTrack({ name: "t1", repo: "your-org/myproject" }),
        makeTrack({ name: "t2", repo: "stylusnexus/work-plan-toolkit" }),
      ],
      untracked: [
        { repo: "your-org/myproject", issues: [untrackedIssue] },
      ],
    };
    const tree = buildTree(exp);
    const myproject = tree.find(n => n.repo === "your-org/myproject")!;
    const wpt = tree.find(n => n.repo === "stylusnexus/work-plan-toolkit")!;
    assert.equal(myproject.untracked.length, 1);
    assert.strictEqual(myproject.untracked[0], untrackedIssue);
    assert.deepEqual(wpt.untracked, []);
  });

  test("null-repo bucket always gets untracked:[]", () => {
    const exp: Export = {
      schema: 1,
      generated_at: "2026-06-07T00:00:00Z",
      tracks: [
        makeTrack({ name: "orphan", repo: null as unknown as string }),
      ],
      // Even if someone mis-keyed "(no repo)" in the export, bucket stays []
      untracked: [{ repo: "(no repo)", issues: [makeIssue()] }],
    };
    const tree = buildTree(exp);
    assert.equal(tree[0].repo, "(no repo)");
    assert.deepEqual(tree[0].untracked, []);
  });

  test("untracked issues preserve the full Issue shape", () => {
    const issue: Issue = {
      number: 42,
      title: "Fix the thing",
      state: "open",
      assignee: "@bob",
      milestone: "v2",
    };
    const exp: Export = {
      schema: 1,
      generated_at: "2026-06-07T00:00:00Z",
      tracks: [makeTrack({ repo: "org/repo" })],
      untracked: [{ repo: "org/repo", issues: [issue] }],
    };
    const tree = buildTree(exp);
    assert.deepEqual(tree[0].untracked[0], issue);
  });
});

describe("repoDescription", () => {
  function repoNode(overrides: Partial<RepoNode> = {}): RepoNode {
    return { kind: "repo", repo: "your-org/myproject", isPublic: false, tier: "private", tracks: [], untracked: [], ...overrides };
  }

  test("private repo → the tier text", () => {
    assert.equal(repoDescription(repoNode({ isPublic: false, tier: "private" })), "private");
  });

  test("public repo → '⚠ public' only (no tier prefix)", () => {
    // Regression guard for #112: a public repo must NOT read "private ⚠ public".
    const desc = repoDescription(repoNode({ isPublic: true, tier: "private" }));
    assert.equal(desc, "⚠ public");
    assert.ok(!desc.includes("private"), "public repo description must not contain the tier word");
  });

  test("drives off the live tier so a future non-'private' tier is reflected", () => {
    assert.equal(repoDescription(repoNode({ isPublic: false, tier: "shared" })), "shared");
  });

  test("the MOCKUP fixture's public repo reads '⚠ public'", () => {
    const tree = buildTree(MOCKUP_EXPORT);
    assert.equal(repoDescription(tree[0]), "private");   // myproject (private)
    assert.equal(repoDescription(tree[1]), "⚠ public");  // work-plan-toolkit (public)
  });
});

describe("shouldExpandRepos", () => {
  test("collapses by default with multiple repos", () => {
    assert.equal(shouldExpandRepos(2, false), false);
    assert.equal(shouldExpandRepos(23, false), false);
  });
  test("expands when the setting is on", () => {
    assert.equal(shouldExpandRepos(5, true), true);
  });
  test("always expands a single repo regardless of setting", () => {
    assert.equal(shouldExpandRepos(1, false), true);
    assert.equal(shouldExpandRepos(0, false), true);
  });
});

// ---------------------------------------------------------------------------
// sortTracks
// ---------------------------------------------------------------------------

/**
 * Builds a minimal TrackNode for sort tests.
 * Only category, open, and name matter; other fields use placeholder values.
 */
function makeSortTrack(
  name: string,
  category: TrackNode["category"],
  open: number,
): TrackNode {
  return {
    kind: "track",
    name,
    repo: "org/repo",
    status: category,
    category,
    open,
    hint: null,
    track: makeTrack({ name, status: category === "blocked" ? "blocked" : category }),
  };
}

// Fixture: varied category, open count, and name to exercise all modes.
// Discovery order: alpha(blocked,5), charlie(active,10), bravo(blocked,5), delta(active,3)
const SORT_FIXTURE: TrackNode[] = [
  makeSortTrack("alpha",   "blocked", 5),
  makeSortTrack("charlie", "active",  10),
  makeSortTrack("bravo",   "blocked", 5),
  makeSortTrack("delta",   "active",  3),
];

describe("sortTracks", () => {
  test("default — returns same order, new array", () => {
    const result = sortTracks(SORT_FIXTURE, "default");
    const names = result.map(t => t.name);
    assert.deepEqual(names, ["alpha", "charlie", "bravo", "delta"]);
    // Must be a new array
    assert.notStrictEqual(result, SORT_FIXTURE);
  });

  test("default — input is not mutated", () => {
    const original = SORT_FIXTURE.map(t => t.name);
    sortTracks(SORT_FIXTURE, "default");
    assert.deepEqual(SORT_FIXTURE.map(t => t.name), original);
  });

  test("name — alphabetical ascending", () => {
    const result = sortTracks(SORT_FIXTURE, "name");
    assert.deepEqual(result.map(t => t.name), ["alpha", "bravo", "charlie", "delta"]);
  });

  test("open — descending by open count, tie-break by name asc", () => {
    // charlie(10) → alpha(5) → bravo(5) → delta(3)
    // alpha and bravo are both open=5 → tie-break by name: alpha before bravo
    const result = sortTracks(SORT_FIXTURE, "open");
    assert.deepEqual(result.map(t => t.name), ["charlie", "alpha", "bravo", "delta"]);
  });

  test("blocked — blocked group first, within group open desc then name asc", () => {
    // blocked: alpha(5), bravo(5) — both open=5 → alpha before bravo (name tie-break)
    // non-blocked: charlie(10), delta(3)
    const result = sortTracks(SORT_FIXTURE, "blocked");
    assert.deepEqual(result.map(t => t.name), ["alpha", "bravo", "charlie", "delta"]);
  });

  test("blocked — higher-open blocked track sorts first within group", () => {
    const tracks: TrackNode[] = [
      makeSortTrack("low-blocker",  "blocked", 2),
      makeSortTrack("high-blocker", "blocked", 9),
      makeSortTrack("active-a",     "active",  5),
    ];
    const result = sortTracks(tracks, "blocked");
    assert.deepEqual(result.map(t => t.name), ["high-blocker", "low-blocker", "active-a"]);
  });

  test("blocked — non-blocked tracks sorted by open desc then name within their group", () => {
    const tracks: TrackNode[] = [
      makeSortTrack("blocker",   "blocked", 1),
      makeSortTrack("beta",      "active",  7),
      makeSortTrack("alpha",     "active",  7),
      makeSortTrack("low",       "active",  2),
    ];
    const result = sortTracks(tracks, "blocked");
    // blocker first; then active: beta(7) and alpha(7) — tie → alpha before beta; low last
    assert.deepEqual(result.map(t => t.name), ["blocker", "alpha", "beta", "low"]);
  });

  test("input array is not mutated after any sort", () => {
    const original = SORT_FIXTURE.map(t => t.name);
    sortTracks(SORT_FIXTURE, "blocked");
    sortTracks(SORT_FIXTURE, "open");
    sortTracks(SORT_FIXTURE, "name");
    assert.deepEqual(SORT_FIXTURE.map(t => t.name), original);
  });

  test("single-element array — all modes return a copy with that element", () => {
    const single = [makeSortTrack("solo", "active", 3)];
    for (const mode of ["default", "blocked", "open", "name"] as const) {
      const result = sortTracks(single, mode);
      assert.equal(result.length, 1);
      assert.equal(result[0].name, "solo");
      assert.notStrictEqual(result, single);
    }
  });

  test("empty array — returns empty array", () => {
    for (const mode of ["default", "blocked", "open", "name"] as const) {
      assert.deepEqual(sortTracks([], mode), []);
    }
  });
});
