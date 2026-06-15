/** Schema version for the work-plan export JSON surface. */
export const SCHEMA_VERSION = 1;

/** A dependency edge from `blocked_by` / `blocking` arrays on an Issue (#257). */
export interface IssueDep { number: number; repo: string; title: string; }

/** A single GitHub issue as returned by `work-plan export --json`. */
export interface Issue {
  number: number;
  title: string;
  state: "open" | "closed";
  /** "@login", "@a, @b", or "—" */
  assignee: string;
  /** Short milestone label or null. */
  milestone: string | null;
  /** True when the issue has an active hot branch OR the work-plan:in-progress
   *  label (the UNION signal). Drives the in-progress BADGE. */
  in_progress: boolean;
  /** True iff the work-plan:in-progress label is actually present on the issue
   *  (label-only signal, independent of hot-branch state). Drives the toggle
   *  button so Mark/Clear accurately reflects label presence, not the union. */
  in_progress_label: boolean;
  /** Open issues this issue is blocked by (GitHub-native dependency edges, #257). */
  blocked_by: IssueDep[];
  /** Open issues this issue is blocking (GitHub-native dependency edges, #257). */
  blocking: IssueDep[];
}

/** Aggregate open/closed counts for a track. */
export interface Rollup {
  open: number;
  closed: number;
}

/**
 * A track's declared plan/spec doc and its execution badge (#285). The link is
 * declared track-side (`plan:` in track frontmatter) and resolved by the CLI
 * against the track's repo checkout. `resolved` false → the link is declared but
 * couldn't be evaluated (no local clone, or the file is absent); the badge fields
 * are then absent and only `rel` is meaningful.
 */
export interface TrackPlan {
  /** Repo-relative POSIX path of the linked doc, as declared in frontmatter. */
  rel: string;
  resolved: boolean;
  verdict?: PlanDoc["verdict"];
  glyph?: string;
  files_present?: number;
  files_declared?: number;
  checkboxes_done?: number;
  checkboxes_total?: number;
  lie_gap?: boolean;
  stalled?: boolean;
  override?: "shipped" | "partial" | "dead" | null;
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
  /** Config repo key (the key under `repos:` in config.yml), or null. Used as
   *  the `plan-status --repo=<key>` arg by the Plans view (#164) — the CLI
   *  resolves a local checkout by folder key, not by github slug. */
  folder: string | null;
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
  /**
   * The effective preset name driving next-up ordering (e.g. "flow",
   * "priority-driven", "backlog", "custom"), as emitted by `export --json`
   * (#326 Phase 2). Optional on the wire — older CLIs omit it; the viewer
   * degrades gracefully (no indicator) when absent.
   */
  next_up_preset?: string;
  /** Track slugs that this track explicitly depends on (#102). */
  depends_on: string[];
  rollup: Rollup;
  issues: Issue[];
  /** The track's declared plan/spec doc + execution badge (#285), or null/absent
   *  when the track declares no `plan:`. Optional on the wire so an older CLI
   *  (no `plan` field) deserializes cleanly. */
  plan?: TrackPlan | null;
}

/**
 * A configured repo from `config.yml`'s `repos:` block, emitted by the CLI for
 * EVERY registered repo regardless of track membership (#288). Lets the viewer
 * show a registered-but-empty repo so the user can start adding tracks to it.
 */
export interface ConfigRepo {
  /** Config repo key (the key under `repos:` in config.yml), or null. */
  folder: string | null;
  /** GitHub slug "org/repo", or null when the config block has no `github`. */
  repo: string | null;
  /** Absolute path to the local checkout, or null when none is configured. */
  local: string | null;
  /** true when `local` exists on disk. */
  has_local: boolean;
  /** "PUBLIC" | "PRIVATE" | null (best-effort). */
  visibility: "PUBLIC" | "PRIVATE" | null;
}

/** Root shape emitted by `work-plan export --json`. */
export interface Export {
  schema: number;
  generated_at: string;
  tracks: Track[];
  /** Open issues referenced by no track, grouped by repo (CLI schema 1, additive). */
  untracked?: { repo: string; issues: Issue[] }[];
  /** Every configured repo, regardless of track membership (#288, additive). */
  repos?: ConfigRepo[];
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
  /**
   * Human verdict-override from the doc's frontmatter (#286): "shipped" |
   * "partial" | "dead" when a reviewer has affirmed the verdict, else null.
   * When set, the CLI pins `verdict` to it and forces `lie_gap` false. Optional
   * on the wire so an older CLI (no override field) deserializes to undefined.
   */
  override?: "shipped" | "partial" | "dead" | null;
  /**
   * Durable, shared acknowledgment from the doc's frontmatter (`acknowledged:
   * true`), written by `plan-ack` (#286). Distinct from the viewer's per-machine
   * workspaceState ack — this one is committed with the repo. Optional on the
   * wire so an older CLI (no field) deserializes to undefined.
   */
  acknowledged?: boolean;
  /**
   * Drift baseline (#286): the verdict stamped by `plan-baseline` (a verdict
   * string, or null). `verdict_drift` is true when the live `verdict` no longer
   * matches this baseline (and no override is pinning it) — a once-shipped plan
   * that silently regressed. Optional on the wire for older-CLI compatibility.
   */
  verdict_baseline?: "shipped" | "partial" | "dead" | null;
  verdict_drift?: boolean;
  /**
   * Declared manifest paths that resolve OUTSIDE the repo (absolute, ~, ..-escape,
   * junk `/`) — surfaced read-only (#286). They silently drag the file score
   * down and usually mean a typo/misfiled plan. Optional for older-CLI compat.
   */
  offtree_paths?: string[];
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

/**
 * Issue numbers ALREADY tracked by some track in `repo` — the union, across that
 * repo's tracks, of each track's issues + next_up + blockers. Passed as the
 * `--exclude` set when fetching a repo's open issues (#303 fix) so the Untracked
 * bucket never shows an issue that a track already owns (e.g. #287 in the
 * work-plan-viewer track). Without this, "Fetch Open Issues" on a repo that has
 * tracks pulled every open issue and rendered tracked ones as untracked.
 */
export function trackedIssueNumbers(exp: Export, repo: string): number[] {
  const nums = new Set<number>();
  for (const t of exp.tracks) {
    if (t.repo !== repo) continue;
    for (const i of t.issues) nums.add(i.number);
    for (const n of t.next_up) nums.add(n);
    for (const n of t.blockers) nums.add(n);
  }
  return [...nums];
}
