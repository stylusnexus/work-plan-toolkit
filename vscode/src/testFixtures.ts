/**
 * Shared test fixtures (#530). Test files are typechecked, so every Issue /
 * Track a test builds must satisfy the production types. These helpers fill
 * the required fields with neutral defaults; pass `overrides` for what the
 * test cares about. Imported only by *.test.ts — never by shipped code.
 */
import type { Issue, Track } from "./model.ts";

export function makeIssue(overrides: Partial<Issue> = {}): Issue {
  return {
    number: 1,
    title: "test issue",
    state: "open",
    assignee: "@eve",
    milestone: null,
    in_progress: false,
    in_progress_label: false,
    blocked_by: [],
    blocking: [],
    ...overrides,
  };
}

export function makeTrack(overrides: Partial<Track> = {}): Track {
  return {
    name: "platform-health",
    repo: "your-org/myproject",
    path: null,
    folder: null,
    tier: "private",
    status: "active",
    launch_priority: null,
    milestone_alignment: null,
    visibility: null,
    blockers: [],
    next_up: [],
    depends_on: [],
    rollup: { open: 0, closed: 0 },
    issues: [],
    ...overrides,
  };
}
