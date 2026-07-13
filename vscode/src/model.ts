/** Schema version for the work-plan export JSON surface. */
export const SCHEMA_VERSION = 1;

declare const trackKeyBrand: unique symbol;
declare const issueKeyBrand: unique symbol;

/** Canonical identity for a track: JSON `[folder ?? repo ?? "", name]`. */
export type TrackKey = string & { readonly [trackKeyBrand]: "TrackKey" };

/** Canonical identity for an issue: JSON `[repo, number]`. */
export type IssueKey = string & { readonly [issueKeyBrand]: "IssueKey" };

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
/**
 * A track blocker: either a tracked issue number, or a free-text note. The
 * frontmatter `blockers:` list accepts both — `- 5550` / `- "#5550"` is an
 * issue ref; `- "gated on the cost verdict…"` is prose. The CLI export emits
 * them verbatim, so any consumer that treats a blocker as a number must funnel
 * it through `blockerIssue` first (a raw `i_${b}` of a prose blocker detonates
 * the Mermaid graph; an unescaped one injects HTML into the detail panel).
 */
export type Blocker = number | string;

/**
 * The issue number a blocker refers to, or null when it is free-text.
 *
 * Accepts a bare number, or a string that is ONLY an issue ref — `"5550"` or
 * `"#5550"` (optional leading `#`, surrounding whitespace tolerated). A string
 * with any other content is free-text and returns null: we deliberately do NOT
 * parse an embedded `#5550` out of prose, because that number is often an active
 * `next_up` item the author is describing, not the blocker itself.
 */
export function blockerIssue(b: Blocker): number | null {
  if (typeof b === "number") return Number.isInteger(b) ? b : null;
  const m = /^\s*#?(\d+)\s*$/.exec(b);
  if (m === null) return null;
  const n = Number(m[1]);
  // Reject leading-zero ("007") and overflow (>MAX_SAFE_INTEGER) digit strings:
  // neither is a real GitHub issue number, so treat them as free-text rather
  // than emit a bogus ref. The round-trip `String(n) === m[1]` catches both.
  return Number.isSafeInteger(n) && String(n) === m[1] ? n : null;
}

export interface Track {
  name: string;
  repo: string | null;
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
  /** True for a track in the archive tier (#328) — present only when the export
   *  ran with `--include-archived` (the Show-archived toggle). Optional on the
   *  wire; an older CLI omits it. The viewer greys these + offers Unarchive. */
  archived?: boolean;
  launch_priority: string | null;
  milestone_alignment: string | null;
  /** "PUBLIC" | "PRIVATE" | null (best-effort). */
  visibility: "PUBLIC" | "PRIVATE" | null;
  /** Track blockers. Usually issue numbers, but the frontmatter also accepts a
   *  free-text note (e.g. "gated on the cost go/no-go verdict") — see Blocker. */
  blockers: Blocker[];
  /** Issue numbers queued as next-up. */
  next_up: number[];
  /**
   * The effective preset name driving next-up ordering (e.g. "flow",
   * "priority-driven", "backlog", "custom"), as emitted by `export --json`
   * (#326 Phase 2). Optional on the wire — older CLIs omit it; the viewer
   * degrades gracefully (no indicator) when absent.
   */
  next_up_preset?: string;
  /**
   * When true, the track's next-up list is ranked automatically by the active
   * preset (#338). When false or absent, the list is hand-curated. Optional
   * on the wire — older CLIs omit it; the viewer degrades gracefully.
   */
  next_up_auto?: boolean;
  /** Track slugs that this track explicitly depends on (#102). */
  depends_on: string[];
  rollup: Rollup;
  issues: Issue[];
  /** The track's declared plan/spec doc + execution badge (#285), or null/absent
   *  when the track declares no `plan:`. Optional on the wire so an older CLI
   *  (no `plan` field) deserializes cleanly. */
  plan?: TrackPlan | null;
  /**
   * True when the track is flagged as a cleanup candidate (#328/#329/#330) — a
   * reversible, non-destructive frontmatter flag (NOT deletion). Optional on the
   * wire so an older CLI (no field) deserializes cleanly.
   */
  cleanup_candidate?: boolean;
  /** Free-text reason for the cleanup flag, or null when none was given. */
  cleanup_reason?: string | null;
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

/**
 * A track that exists in BOTH a repo's shared `.work-plan/` tier and the private
 * `notes_root` tier (#361) — a private copy left behind after promotion. The CLI
 * already resolves the collision ("using shared") but the private orphan keeps
 * warning to stderr, which the viewer never sees; this surfaces it as a
 * read-only health signal. Resolved with the `dedupe-tiers` CLI verb.
 */
export interface TierDuplicate {
  /** GitHub slug "org/repo". */
  repo: string | null;
  /** Config repo key (the key under `repos:`), for the `--repo=` hint. */
  folder: string | null;
  /** Track name (filename stem, shared on both tiers). */
  name: string;
  /** Absolute path to the shared copy (the one that wins). */
  shared_path: string;
  /** Absolute path to the private orphan (the one dedupe-tiers would remove). */
  private_path: string;
  /** true when the private copy's issue refs are a subset of the shared copy's —
   *  i.e. dedupe-tiers can remove it with no data loss. false = diverged, needs
   *  manual review. */
  safe: boolean;
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
  /** Tracks present in both the shared and private tier (#361, additive). */
  tier_duplicates?: TierDuplicate[];
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
  /** Set by `plan-status --include-archived`: this doc lives under
   *  archive/shipped/ or archive/abandoned/. Optional for older-CLI compat. */
  archived?: boolean;
  archive_kind?: "shipped" | "abandoned";
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

/**
 * Repo qualifier used for track identity and repo-scoped CLI operations.
 * Configured repos are addressed by their folder key; older/minimal exports
 * without one fall back to the GitHub slug.
 */
export function trackRepoQualifier(
  track: Pick<Track, "folder" | "repo">,
): string {
  // Empty string is reserved for an unfiled track. Config keys and GitHub
  // slugs are non-empty, so it cannot alias a real repo qualifier.
  return track.folder ?? track.repo ?? "";
}

/** Builds a canonical track key from an already-resolved repo qualifier. */
export function trackKeyFromParts(repoQualifier: string, name: string): TrackKey {
  if (name.length === 0) {
    throw new TypeError("Track keys require a non-empty name");
  }
  return JSON.stringify([repoQualifier, name]) as TrackKey;
}

/** Builds the canonical identity for a track. */
export function trackKey(
  track: Pick<Track, "folder" | "repo" | "name">,
): TrackKey {
  return trackKeyFromParts(trackRepoQualifier(track), track.name);
}

/** Builds the canonical identity for an issue. */
export function issueKey(repo: string, number: number): IssueKey {
  if (!Number.isSafeInteger(number) || number <= 0) {
    throw new TypeError("Issue keys require a positive safe integer");
  }
  return JSON.stringify([repo, number]) as IssueKey;
}

/** Parses a canonical track key, rejecting alternate JSON spellings/shapes. */
export function parseTrackKey(value: unknown): readonly [string, string] | null {
  if (typeof value !== "string") return null;
  try {
    const parsed: unknown = JSON.parse(value);
    if (
      !Array.isArray(parsed)
      || parsed.length !== 2
      || typeof parsed[0] !== "string"
      || typeof parsed[1] !== "string"
      || parsed[1].length === 0
      || JSON.stringify(parsed) !== value
    ) {
      return null;
    }
    return [parsed[0], parsed[1]];
  } catch {
    return null;
  }
}

/** Parses a canonical issue key, rejecting alternate JSON spellings/shapes. */
export function parseIssueKey(value: unknown): readonly [string, number] | null {
  if (typeof value !== "string") return null;
  try {
    const parsed: unknown = JSON.parse(value);
    if (
      !Array.isArray(parsed)
      || parsed.length !== 2
      || typeof parsed[0] !== "string"
      || typeof parsed[1] !== "number"
      || !Number.isSafeInteger(parsed[1])
      || parsed[1] <= 0
      || JSON.stringify(parsed) !== value
    ) {
      return null;
    }
    return [parsed[0], parsed[1]];
  } catch {
    return null;
  }
}

/** Runtime validator for untrusted track-key payloads. */
export function isTrackKey(value: unknown): value is TrackKey {
  return parseTrackKey(value) !== null;
}

/** Runtime validator for untrusted issue-key payloads. */
export function isIssueKey(value: unknown): value is IssueKey {
  return parseIssueKey(value) !== null;
}

/**
 * Resolves a track by canonical key. A raw display name remains supported only
 * when unique, preventing compatibility callers from silently choosing the
 * wrong repo when duplicate names exist.
 */
export function resolveTrack(
  tracks: readonly Track[],
  selection: TrackKey | string,
): Track | undefined {
  const parts = parseTrackKey(selection);
  if (parts) {
    const [repoQualifier, name] = parts;
    return tracks.find(
      track => track.name === name && trackRepoQualifier(track) === repoQualifier,
    );
  }

  const matches = tracks.filter(track => track.name === selection);
  return matches.length === 1 ? matches[0] : undefined;
}

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
    for (const b of t.blockers) {
      const num = blockerIssue(b);
      if (num !== null) nums.add(num);
    }
  }
  return [...nums];
}

/**
 * Distinct milestone labels already present in the export — drawn from both
 * track `milestone_alignment` and issue `milestone` fields — sorted for a
 * stable quick-pick (#213). Used to suggest existing milestones when editing a
 * track's `milestone_alignment`, so the edit path doesn't accept blind free
 * text. Null/empty values are dropped. Pure.
 */
export function collectMilestones(exp: Export): string[] {
  const set = new Set<string>();
  for (const t of exp.tracks) {
    if (t.milestone_alignment) set.add(t.milestone_alignment);
    for (const i of t.issues) {
      if (i.milestone) set.add(i.milestone);
    }
  }
  return [...set].sort();
}
