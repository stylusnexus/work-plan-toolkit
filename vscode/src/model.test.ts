import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  isClosed,
  isBlocked,
  completionRatio,
  trackedIssueNumbers,
  collectMilestones,
  blockerIssue,
  trackRepoQualifier,
  trackKey,
  trackKeyFromParts,
  issueKey,
  parseTrackKey,
  parseIssueKey,
  resolveTrack,
  SCHEMA_VERSION,
} from "./model.ts";
import type { Issue, Track, Export } from "./model.ts";
import { actionToArgs } from "./write.ts";

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

// ---------------------------------------------------------------------------
// isClosed
// ---------------------------------------------------------------------------

describe("isClosed", () => {
  test("returns true when issue state is closed", () => {
    const issue = makeIssue({ state: "closed" });
    assert.equal(isClosed(issue), true);
  });

  test("returns false when issue state is open", () => {
    const issue = makeIssue({ state: "open" });
    assert.equal(isClosed(issue), false);
  });
});

// ---------------------------------------------------------------------------
// isBlocked
// ---------------------------------------------------------------------------

describe("isBlocked", () => {
  test("returns false when blockers array is empty", () => {
    const track = makeTrack({ blockers: [] });
    assert.equal(isBlocked(track), false);
  });

  test("returns true when track has one or more blockers", () => {
    const track = makeTrack({ blockers: [4821] });
    assert.equal(isBlocked(track), true);
  });
});

// ---------------------------------------------------------------------------
// completionRatio
// ---------------------------------------------------------------------------

describe("completionRatio", () => {
  test("returns 0 for an empty track (no issues)", () => {
    const track = makeTrack({ rollup: { open: 0, closed: 0 } });
    assert.equal(completionRatio(track), 0);
  });

  test("returns 0.5 when half the issues are closed", () => {
    const track = makeTrack({ rollup: { open: 4, closed: 4 } });
    assert.equal(completionRatio(track), 0.5);
  });

  test("returns 1 when all issues are closed", () => {
    const track = makeTrack({ rollup: { open: 0, closed: 10 } });
    assert.equal(completionRatio(track), 1);
  });
});

// ---------------------------------------------------------------------------
// SCHEMA_VERSION constant
// ---------------------------------------------------------------------------

test("SCHEMA_VERSION is 1", () => {
  assert.equal(SCHEMA_VERSION, 1);
});

// ---------------------------------------------------------------------------
// Canonical repo-qualified identity (#430)
// ---------------------------------------------------------------------------

describe("canonical track and issue keys", () => {
  test("track keys are deterministic JSON tuples of folder + name", () => {
    const track = makeTrack({ folder: "local-key", repo: "o/r", name: "api" });
    assert.equal(trackKey(track), '["local-key","api"]');
    assert.equal(trackKey(track), trackKeyFromParts("local-key", "api"));
    assert.deepEqual(parseTrackKey(trackKey(track)), ["local-key", "api"]);
  });

  test("track repo qualifier falls back from folder to the GitHub slug", () => {
    const track = makeTrack({ folder: null, repo: "o/r", name: "api" });
    assert.equal(trackRepoQualifier(track), "o/r");
    assert.equal(trackKey(track), '["o/r","api"]');
  });

  test("unfiled tracks receive a stable no-repo identity instead of throwing", () => {
    const track = makeTrack({ folder: null, repo: null, name: "scratch" });
    assert.equal(trackRepoQualifier(track), "");
    assert.equal(trackKey(track), '["","scratch"]');
  });

  test("unfiled identity cannot alias a literal '(no repo)' folder", () => {
    const configured = makeTrack({ folder: "(no repo)", repo: "o/r", name: "same" });
    const unfiled = makeTrack({ folder: null, repo: null, name: "same" });
    assert.notEqual(trackKey(configured), trackKey(unfiled));
    assert.equal(resolveTrack([configured, unfiled], trackKey(unfiled)), unfiled);
  });

  test("issue keys are deterministic repo + number JSON tuples", () => {
    assert.equal(issueKey("o/r", 42), '["o/r",42]');
    assert.equal(issueKey("o/r", 42), issueKey("o/r", 42));
    assert.deepEqual(parseIssueKey(issueKey("o/r", 42)), ["o/r", 42]);
  });

  test("parsers reject malformed or non-canonical keys", () => {
    assert.equal(parseTrackKey('["o/r"]'), null);
    assert.equal(parseTrackKey('["o/r","api",true]'), null);
    assert.equal(parseTrackKey('["o/r",42]'), null);
    assert.equal(parseTrackKey('[ "o/r", "api" ]'), null);
    assert.equal(parseIssueKey('["o/r","42"]'), null);
    assert.equal(parseIssueKey('["o/r",0]'), null);
  });
});

describe("resolveTrack", () => {
  const first = makeTrack({ folder: "one", repo: "o/one", name: "shared" });
  const second = makeTrack({ folder: "two", repo: "o/two", name: "shared" });
  const unique = makeTrack({ folder: "one", repo: "o/one", name: "unique" });
  const tracks = [first, second, unique];

  test("resolves duplicate names by composite track key", () => {
    assert.equal(resolveTrack(tracks, trackKey(second)), second);
  });

  test("selected repo-B duplicate routes destructive delete only to repo B", () => {
    const selected = resolveTrack(tracks, trackKey(second));
    assert.equal(selected, second);
    const args = actionToArgs({
      kind: "deleteTrack",
      track: selected!.name,
      repoKey: trackRepoQualifier(selected!),
    });
    assert.deepEqual(args, ["delete-track", "--repo=two", "--", "shared"]);
    assert.ok(!args.includes("--repo=one"));
  });

  test("preserves legacy unique-name resolution", () => {
    assert.equal(resolveTrack(tracks, "unique"), unique);
  });

  test("does not guess when a legacy name is ambiguous", () => {
    assert.equal(resolveTrack(tracks, "shared"), undefined);
  });
});

// ---------------------------------------------------------------------------
// trackedIssueNumbers (#303 fix)
// ---------------------------------------------------------------------------

describe("trackedIssueNumbers", () => {
  const exp = (tracks: Track[]): Export => ({
    schema: SCHEMA_VERSION, generated_at: "t", tracks,
  });

  test("unions issues + next_up + blockers for the repo's tracks", () => {
    const t1 = makeTrack({ repo: "o/r", issues: [makeIssue({ number: 287 })], next_up: [213], blockers: [9] });
    const t2 = makeTrack({ name: "b", repo: "o/r", issues: [makeIssue({ number: 5 })] });
    assert.deepEqual(
      trackedIssueNumbers(exp([t1, t2]), "o/r").sort((a, b) => a - b),
      [5, 9, 213, 287],
    );
  });

  test("ignores tracks in other repos", () => {
    const here = makeTrack({ repo: "o/r", issues: [makeIssue({ number: 1 })] });
    const other = makeTrack({ name: "x", repo: "o/other", issues: [makeIssue({ number: 99 })] });
    assert.deepEqual(trackedIssueNumbers(exp([here, other]), "o/r"), [1]);
  });

  test("empty when the repo has no tracks", () => {
    assert.deepEqual(trackedIssueNumbers(exp([makeTrack({ repo: "o/other" })]), "o/r"), []);
  });

  test("dedups a number that appears in multiple fields/tracks", () => {
    const t1 = makeTrack({ repo: "o/r", issues: [makeIssue({ number: 7 })], next_up: [7] });
    const t2 = makeTrack({ name: "b", repo: "o/r", blockers: [7] });
    assert.deepEqual(trackedIssueNumbers(exp([t1, t2]), "o/r"), [7]);
  });

  test("a free-text blocker contributes no issue number to the exclude set", () => {
    // Otherwise the whole sentence lands in a Set<number> and pollutes the
    // `gh --exclude` list; a pure "#5550" ref still counts.
    const t = makeTrack({
      repo: "o/r",
      issues: [makeIssue({ number: 12 })],
      blockers: ["#34", "gated on the cost go/no-go verdict (#5548 telemetry)"],
    });
    assert.deepEqual(trackedIssueNumbers(exp([t]), "o/r").sort((a, b) => a - b), [12, 34]);
  });
});

// ---------------------------------------------------------------------------
// blockerIssue — the issue-ref / free-text normalizer
// ---------------------------------------------------------------------------

describe("blockerIssue", () => {
  test("a bare number is its own issue ref", () => {
    assert.equal(blockerIssue(5550), 5550);
  });

  test('pure ID strings resolve — "5550" and "#5550", whitespace-tolerant', () => {
    assert.equal(blockerIssue("5550"), 5550);
    assert.equal(blockerIssue("#5550"), 5550);
    assert.equal(blockerIssue("  #5550 "), 5550);
  });

  test("prose is free-text (null) — even when it embeds a #ref", () => {
    // We must NOT extract 5550 here: it's an active next_up item the author is
    // describing, not the blocker itself.
    assert.equal(
      blockerIssue("#5550 selective routing is gated on the verdict, needs #5548"),
      null,
    );
    assert.equal(blockerIssue("waiting on design review"), null);
  });

  test("non-integer / empty edge cases are free-text", () => {
    assert.equal(blockerIssue(""), null);
    assert.equal(blockerIssue("#"), null);
    assert.equal(blockerIssue(3.5), null);
  });

  test("leading-zero and overflow digit strings are free-text, not bogus refs", () => {
    // "007" would Number()→7 (wrong issue); a 20-digit paste exceeds
    // MAX_SAFE_INTEGER and rounds. Neither is a real GitHub issue number.
    assert.equal(blockerIssue("007"), null);
    assert.equal(blockerIssue("99999999999999999999"), null);
    // …but a normal ref is unaffected.
    assert.equal(blockerIssue("#5550"), 5550);
  });
});

// ---------------------------------------------------------------------------
// collectMilestones (#213)
// ---------------------------------------------------------------------------

describe("collectMilestones", () => {
  const exp = (tracks: Track[]): Export => ({
    schema: SCHEMA_VERSION, generated_at: "t", tracks,
  });

  test("unions track milestone_alignment + issue milestone, sorted + deduped", () => {
    const t1 = makeTrack({ milestone_alignment: "v1.0.0", issues: [makeIssue({ milestone: "v1.1.0" })] });
    const t2 = makeTrack({ name: "b", milestone_alignment: "v1.0.0", issues: [makeIssue({ milestone: "v2.0.0" })] });
    assert.deepEqual(collectMilestones(exp([t1, t2])), ["v1.0.0", "v1.1.0", "v2.0.0"]);
  });

  test("drops null/empty milestone values", () => {
    const t = makeTrack({ milestone_alignment: null, issues: [makeIssue({ milestone: null }), makeIssue({ milestone: "v1" })] });
    assert.deepEqual(collectMilestones(exp([t])), ["v1"]);
  });

  test("empty when no milestones present", () => {
    const t = makeTrack({ milestone_alignment: null, issues: [] });
    assert.deepEqual(collectMilestones(exp([t])), []);
  });
});
