import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  isClosed,
  isBlocked,
  completionRatio,
  SCHEMA_VERSION,
} from "./model.ts";
import type { Issue, Track } from "./model.ts";

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
