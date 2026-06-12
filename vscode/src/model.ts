/** Schema version for the work-plan export JSON surface. */
export const SCHEMA_VERSION = 1;

/** A single GitHub issue as returned by `work-plan export --json`. */
export interface Issue {
  number: number;
  title: string;
  state: "open" | "closed";
  /** "@login", "@a, @b", or "—" */
  assignee: string;
  /** Short milestone label or null. */
  milestone: string | null;
}

/** Aggregate open/closed counts for a track. */
export interface Rollup {
  open: number;
  closed: number;
}

/**
 * A single work-plan track with its associated issues.
 * `status` is a free string: active | in-progress | blocked | parked | shipped | abandoned.
 */
export interface Track {
  name: string;
  repo: string;
  /**
   * Absolute path to the track's `.md` on disk, or null when the track has no
   * backing file (#211). Assumes the CLI and extension share a filesystem view
   * — true for a local install, but NOT for remote-SSH/WSL/devcontainer setups
   * where the extension host runs elsewhere; consumers must stat before opening.
   */
  path: string | null;
  /** "private" today; forward-compat for a future shared tier. */
  tier: string;
  status: string;
  launch_priority: string | null;
  milestone_alignment: string | null;
  /** "PUBLIC" | "PRIVATE" | null (best-effort). */
  visibility: "PUBLIC" | "PRIVATE" | null;
  /** Issue numbers that are blocking this track. */
  blockers: number[];
  /** Issue numbers queued as next-up. */
  next_up: number[];
  /** Track slugs that this track explicitly depends on (#102). */
  depends_on: string[];
  rollup: Rollup;
  issues: Issue[];
}

/** Root shape emitted by `work-plan export --json`. */
export interface Export {
  schema: number;
  generated_at: string;
  tracks: Track[];
  /** Open issues referenced by no track, grouped by repo (CLI schema 1, additive). */
  untracked?: { repo: string; issues: Issue[] }[];
}

/** A plan/spec doc with its plan-status verdict (#164). */
export interface PlanDoc {
  rel: string;
  kind: "plan" | "spec" | "adhoc";
  verdict: "shipped" | "partial" | "dead" | "foreign" | "manifest-less";
  glyph: string;
  rationale: string;
  files_present: number;
  files_declared: number;
  checkboxes_done: number;
  checkboxes_total: number;
  last_touched: string | null;
  manifest_last_touched: string | null;
  stalled: boolean;
  lie_gap: boolean;
  unchecked_items: string[];
  stall_days: number;
}

/** `plan-status --repo=<key> --json` result. */
export interface PlanStatus {
  repo: string;
  docs: PlanDoc[];
}

// ---------------------------------------------------------------------------
// Pure helpers (vscode-free — safe to import in tests)
// ---------------------------------------------------------------------------

/** Returns true when the issue is closed. */
export function isClosed(issue: Issue): boolean {
  return issue.state === "closed";
}

/** Returns true when the track has one or more blocker issues. */
export function isBlocked(track: Track): boolean {
  return track.blockers.length > 0;
}

/** Returns the fraction of issues that are closed (0–1), or 0 for empty tracks. */
export function completionRatio(track: Track): number {
  const total = track.rollup.open + track.rollup.closed;
  return total === 0 ? 0 : track.rollup.closed / total;
}
