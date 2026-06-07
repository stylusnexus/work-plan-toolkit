import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  statusCategory,
  trackHint,
  buildTree,
} from "./treeModel.ts";
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
    repo: "stylusnexus/CritForge",
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
      repo: "stylusnexus/CritForge",
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
      repo: "stylusnexus/CritForge",
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
    assert.equal(tree[0].repo, "stylusnexus/CritForge");
    assert.equal(tree[1].repo, "stylusnexus/work-plan-toolkit");
  });

  test("CritForge isPublic:false (all PRIVATE tracks)", () => {
    const tree = buildTree(MOCKUP_EXPORT);
    assert.equal(tree[0].isPublic, false);
  });

  test("work-plan-toolkit isPublic:true (has PUBLIC track)", () => {
    const tree = buildTree(MOCKUP_EXPORT);
    assert.equal(tree[1].isPublic, true);
  });

  test("CritForge has 2 tracks in first-seen order", () => {
    const tree = buildTree(MOCKUP_EXPORT);
    const critforge = tree[0];
    assert.equal(critforge.tracks.length, 2);
    assert.equal(critforge.tracks[0].name, "platform-health");
    assert.equal(critforge.tracks[1].name, "idea-mode");
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
});
