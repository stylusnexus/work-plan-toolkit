import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  statusCategory,
  trackHint,
  buildTree,
  mergeFetchedUntracked,
  badgeCounts,
  shouldExpandRepos,
  sortTracks,
  repoDescription,
  visibilityTierBadge,
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
    in_progress: false,
    ...overrides,
  };
}

function makeTrack(overrides: Partial<Track> = {}): Track {
  return {
    name: "platform-health",
    repo: "your-org/myproject",
    path: "/tmp/notes/platform-health.md",
    folder: "myrepo",
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

  // --- tier_duplicates (#361) ---

  test("MOCKUP_EXPORT (no tier_duplicates key) → all repo nodes have tierDuplicates:[]", () => {
    const tree = buildTree(MOCKUP_EXPORT);
    for (const node of tree) {
      assert.deepEqual(node.tierDuplicates, []);
    }
  });

  test("tier_duplicates: matched repo gets its entries; unmatched repo gets []", () => {
    const dup = {
      repo: "your-org/myproject", folder: "myproject", name: "auth-flow",
      shared_path: "/p/myproject/.work-plan/auth-flow.md",
      private_path: "/notes/myproject/auth-flow.md", safe: true,
    };
    const exp: Export = {
      schema: 1,
      generated_at: "2026-06-15T00:00:00Z",
      tracks: [
        makeTrack({ name: "t1", repo: "your-org/myproject" }),
        makeTrack({ name: "t2", repo: "stylusnexus/work-plan-toolkit" }),
      ],
      tier_duplicates: [dup],
    };
    const tree = buildTree(exp);
    const myproject = tree.find(n => n.repo === "your-org/myproject")!;
    const wpt = tree.find(n => n.repo === "stylusnexus/work-plan-toolkit")!;
    assert.equal(myproject.tierDuplicates.length, 1);
    assert.strictEqual(myproject.tierDuplicates[0], dup);
    assert.deepEqual(wpt.tierDuplicates, []);
  });

  // --- configured repos (#288): seeded even with zero tracks ---

  test("a config repo with no tracks produces a repo node with empty tracks", () => {
    const exp: Export = {
      schema: 1,
      generated_at: "2026-06-12T00:00:00Z",
      tracks: [],
      repos: [
        { folder: "agent-armor", repo: "stylusnexus/agent-armor", local: "/p/agent-armor", has_local: true, visibility: "PRIVATE" },
      ],
    };
    const tree = buildTree(exp);
    assert.equal(tree.length, 1);
    assert.equal(tree[0].repo, "stylusnexus/agent-armor");
    assert.deepEqual(tree[0].tracks, []);
    assert.equal(tree[0].folder, "agent-armor");
    assert.equal(tree[0].hasLocal, true);
    assert.equal(tree[0].isPublic, false);
    assert.equal(tree[0].tier, "private");
  });

  test("an empty PUBLIC config repo still flags isPublic for the ⚠ badge", () => {
    const exp: Export = {
      schema: 1,
      generated_at: "2026-06-12T00:00:00Z",
      tracks: [],
      repos: [
        { folder: "wpt", repo: "stylusnexus/work-plan-toolkit", local: null, has_local: false, visibility: "PUBLIC" },
      ],
    };
    const tree = buildTree(exp);
    assert.equal(tree[0].isPublic, true);
    assert.equal(tree[0].hasLocal, false);
    assert.equal(repoDescription(tree[0]), "⚠ public");
  });

  test("config repos come first, then track-only repos, in that order", () => {
    const exp: Export = {
      schema: 1,
      generated_at: "2026-06-12T00:00:00Z",
      tracks: [
        makeTrack({ name: "t1", repo: "org/track-only" }),
      ],
      repos: [
        { folder: "cfg", repo: "org/configured", local: null, has_local: false, visibility: "PRIVATE" },
      ],
    };
    const tree = buildTree(exp);
    assert.equal(tree.length, 2);
    assert.equal(tree[0].repo, "org/configured"); // config-first
    assert.equal(tree[1].repo, "org/track-only");
  });

  test("a config repo that ALSO has tracks merges (not duplicated); tracks attach", () => {
    const exp: Export = {
      schema: 1,
      generated_at: "2026-06-12T00:00:00Z",
      tracks: [
        makeTrack({ name: "t1", repo: "org/shared", tier: "private", visibility: "PUBLIC" }),
      ],
      repos: [
        { folder: "shared", repo: "org/shared", local: "/p/shared", has_local: true, visibility: "PRIVATE" },
      ],
    };
    const tree = buildTree(exp);
    assert.equal(tree.length, 1);
    assert.equal(tree[0].repo, "org/shared");
    assert.equal(tree[0].tracks.length, 1);
    assert.equal(tree[0].tracks[0].name, "t1");
    assert.equal(tree[0].folder, "shared");
    assert.equal(tree[0].hasLocal, true);
    // The PUBLIC track flips the badge even though the config repo was PRIVATE.
    assert.equal(tree[0].isPublic, true);
  });

  test("config repos preserve their emitted order, NOT alphabetical", () => {
    const exp: Export = {
      schema: 1,
      generated_at: "2026-06-12T00:00:00Z",
      tracks: [],
      repos: [
        { folder: "z", repo: "org/z-repo", local: null, has_local: false, visibility: "PRIVATE" },
        { folder: "a", repo: "org/a-repo", local: null, has_local: false, visibility: "PRIVATE" },
      ],
    };
    const tree = buildTree(exp);
    assert.equal(tree[0].repo, "org/z-repo");
    assert.equal(tree[1].repo, "org/a-repo");
  });

  test("config repo with a null slug is skipped (can't key to tracks)", () => {
    const exp: Export = {
      schema: 1,
      generated_at: "2026-06-12T00:00:00Z",
      tracks: [],
      repos: [
        { folder: "no-gh", repo: null, local: "/p/no-gh", has_local: true, visibility: null },
      ],
    };
    const tree = buildTree(exp);
    assert.equal(tree.length, 0);
  });

  test("track-only repos (no exp.repos) get folder:null, hasLocal:false", () => {
    const tree = buildTree(MOCKUP_EXPORT);
    for (const node of tree) {
      assert.equal(node.folder, null);
      assert.equal(node.hasLocal, false);
    }
  });
});

describe("repoDescription", () => {
  function repoNode(overrides: Partial<RepoNode> = {}): RepoNode {
    return { kind: "repo", repo: "your-org/myproject", isPublic: false, tier: "private", tracks: [], untracked: [], folder: null, hasLocal: false, ...overrides };
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

describe("visibilityTierBadge — the visibility × tier 2×2 (#259)", () => {
  test("public + shared is the only EXPOSED state (warning glyph + world-visible)", () => {
    const b = visibilityTierBadge(makeTrack({ tier: "shared", visibility: "PUBLIC" }));
    assert.equal(b.exposed, true);
    assert.equal(b.descriptionPrefix, "⚠️🌐☁️");
    assert.match(b.tooltipMarkdown, /world-visible/);
  });

  test("public + unshared is NOT exposed (globe, no warning, no cloud)", () => {
    const b = visibilityTierBadge(makeTrack({ tier: "private", visibility: "PUBLIC" }));
    assert.equal(b.exposed, false);
    assert.equal(b.descriptionPrefix, "🌐");
    assert.ok(!b.descriptionPrefix.includes("⚠️"));
  });

  test("private + shared shows lock + cloud, not exposed", () => {
    const b = visibilityTierBadge(makeTrack({ tier: "shared", visibility: "PRIVATE" }));
    assert.equal(b.exposed, false);
    assert.equal(b.descriptionPrefix, "🔒☁️");
  });

  test("private + unshared shows just a lock", () => {
    const b = visibilityTierBadge(makeTrack({ tier: "private", visibility: "PRIVATE" }));
    assert.equal(b.exposed, false);
    assert.equal(b.descriptionPrefix, "🔒");
  });

  test("null visibility is treated as PRIVATE (safe default — never under-warns)", () => {
    const b = visibilityTierBadge(makeTrack({ tier: "shared", visibility: null }));
    assert.equal(b.exposed, false, "unknown visibility must not be treated as public");
    assert.equal(b.descriptionPrefix, "🔒☁️");
  });

  test("only colour-independent signals: every state differs by glyph + text", () => {
    const states = [
      visibilityTierBadge(makeTrack({ tier: "shared", visibility: "PUBLIC" })),
      visibilityTierBadge(makeTrack({ tier: "private", visibility: "PUBLIC" })),
      visibilityTierBadge(makeTrack({ tier: "shared", visibility: "PRIVATE" })),
      visibilityTierBadge(makeTrack({ tier: "private", visibility: "PRIVATE" })),
    ].map(b => b.descriptionPrefix);
    assert.equal(new Set(states).size, 4, "all four states must be visually distinct");
  });
});

// ---------------------------------------------------------------------------
// mergeFetchedUntracked (#303)
// ---------------------------------------------------------------------------

describe("mergeFetchedUntracked", () => {
  const repoNode = (repo: string, untracked: Issue[] = []): RepoNode => ({
    kind: "repo", repo, isPublic: false, tier: "private",
    tracks: [], untracked, folder: repo, hasLocal: true,
  });
  const issue = (n: number): Issue => ({
    number: n, title: `#${n}`, state: "open", assignee: "—", milestone: null, in_progress: false,
  });

  test("empty fetch map returns the same array reference", () => {
    const repos = [repoNode("o/a")];
    assert.equal(mergeFetchedUntracked(repos, new Map()), repos);
  });

  test("fills untracked for a fetched trackless repo", () => {
    const repos = [repoNode("o/a"), repoNode("o/b")];
    const fetched = new Map([["o/a", [issue(49), issue(40)]]]);
    const out = mergeFetchedUntracked(repos, fetched);
    assert.deepEqual(out[0].untracked.map(i => i.number), [49, 40]);
    assert.equal(out[1].untracked.length, 0);           // o/b untouched
  });

  test("does NOT override a repo that HAS tracks — export stays authoritative (#303 follow-up)", () => {
    const tracked: RepoNode = {
      ...repoNode("o/a", [issue(5)]),       // export-provided untracked = [#5]
      tracks: [{ kind: "track", name: "t", repo: "o/a", status: "active",
                 category: "active", open: 1, closed: 0, hint: null,
                 track: {} as unknown as Track }],
    };
    // A stale fetch snapshot that (wrongly) includes a now-tracked issue.
    const out = mergeFetchedUntracked([tracked], new Map([["o/a", [issue(287), issue(5)]]]));
    assert.deepEqual(out[0].untracked.map(i => i.number), [5]); // export wins, #287 not shown
    assert.equal(out[0], tracked);          // passed through unchanged
  });

  test("does not mutate the input nodes", () => {
    const repos = [repoNode("o/a")];
    mergeFetchedUntracked(repos, new Map([["o/a", [issue(1)]]]));
    assert.equal(repos[0].untracked.length, 0);          // original unchanged
  });

  test("a repo absent from the fetch map passes through by reference", () => {
    const a = repoNode("o/a");
    const out = mergeFetchedUntracked([a], new Map([["o/other", [issue(1)]]]));
    assert.equal(out[0], a);
  });
});

// ---------------------------------------------------------------------------
// badgeCounts (#215)
// ---------------------------------------------------------------------------

describe("badgeCounts", () => {
  const t = (over: Partial<Track> = {}): Track => ({
    name: "t", repo: "o/r", path: null, folder: "f", tier: "private",
    status: "active", launch_priority: null, milestone_alignment: null,
    visibility: null, blockers: [], next_up: [], depends_on: [],
    rollup: { open: 0, closed: 0 }, issues: [], ...over,
  });

  test("counts blocked tracks + sums open issues", () => {
    const tracks = [
      t({ status: "blocked", rollup: { open: 3, closed: 1 } }),
      t({ blockers: [9], rollup: { open: 2, closed: 0 } }),   // blocked via blockers
      t({ status: "active", rollup: { open: 4, closed: 2 } }),
    ];
    assert.deepEqual(badgeCounts(tracks), { blocked: 2, open: 9 });
  });

  test("zero blocked, zero open", () => {
    assert.deepEqual(badgeCounts([t({ status: "shipped" })]), { blocked: 0, open: 0 });
  });

  test("empty tracks", () => {
    assert.deepEqual(badgeCounts([]), { blocked: 0, open: 0 });
  });
});

describe("buildTree — TrackNode.closed (#220)", () => {
  test("carries rollup.closed onto the node", () => {
    const tree = buildTree(MOCKUP_EXPORT);
    const ph = tree[0].tracks[0];   // platform-health: rollup 12/8
    assert.equal(ph.open, 12);
    assert.equal(ph.closed, 8);
  });
});
