import type { Export, Issue, Track, TierDuplicate } from "./model.ts";
import type { SuggestionEntry } from "./suggestions.ts";

// ---------------------------------------------------------------------------
// Node types
// ---------------------------------------------------------------------------

export type StatusCategory = "blocked" | "active" | "shipped" | "parked";

export interface UntrackedGroupNode {
  kind: "untrackedGroup";
  repo: string;
  issues: Issue[];
}

export interface UntrackedIssueNode {
  kind: "untrackedIssue";
  repo: string;
  issue: Issue;
}

/**
 * Auto-slot suggestion buckets (#241), nested as the FIRST children of a repo's
 * Untracked group when `workPlan.autoSlotSuggestions` is on and a Claude session
 * has written answers for the current scan batch:
 *   - `suggestedGroup`/`suggestedIssue`: high-confidence, clear-margin matches —
 *     one-click accept (the issue's click opens the accept QuickPick).
 *   - `needsReviewGroup`/`needsReviewIssue`: narrow-margin or below-threshold
 *     matches — NO one-click accept (the issue's click opens the issue itself).
 * Abstains never reach the tree (they stay plain untracked).
 */
export interface SuggestedGroupNode {
  kind: "suggestedGroup";
  repo: string;
  suggestions: SuggestionEntry[];
}

export interface SuggestedIssueNode {
  kind: "suggestedIssue";
  repo: string;
  issue: Issue;
  suggestedTrack: string;
  runnerUp?: string;
  confidence: number;
  rationale: string;
  margin: "clear" | "narrow";
  tier: "suggested" | "needsReview";
}

export interface NeedsReviewGroupNode {
  kind: "needsReviewGroup";
  repo: string;
  suggestions: SuggestionEntry[];
}

/**
 * A read-only advisory under a repo (#361): N tracks exist in both the shared
 * and private tier. Surfaces the otherwise-invisible "exists in both" condition
 * and names the `dedupe-tiers` verb. Has NO command — the destructive cleanup
 * stays in the CLI; this only makes the condition visible.
 */
export interface TierDupWarningNode {
  kind: "tierDupWarning";
  repo: string;
  folder: string | null;
  count: number;
  /** How many of `count` are safe to auto-remove (private issues ⊆ shared). */
  safeCount: number;
}

export interface TrackNode {
  kind: "track";
  name: string;
  repo: string | null;
  status: string;
  category: StatusCategory;
  /** rollup.open */
  open: number;
  /** rollup.closed — for the tree's closed/total count (#220). */
  closed: number;
  /** "⛔ #4821" | "→ #87" | null */
  hint: string | null;
  /** The raw track — passed to commands/webview by the provider. */
  track: Track;
}

export interface RepoNode {
  kind: "repo";
  /** "your-org/myproject" or "(no repo)" for the null-repo bucket. */
  repo: string;
  /** true when visibility === "PUBLIC" on any child track → ⚠ badge. */
  isPublic: boolean;
  /** Tier from the first track (today "private"). */
  tier: string;
  tracks: TrackNode[];
  /**
   * Open issues for this repo that are referenced by no track.
   * Populated from `Export.untracked`; always `[]` when the repo has no
   * untracked issues or when the CLI did not emit the field (older versions).
   */
  untracked: Issue[];
  /**
   * Tracks present in both this repo's shared and private tier (#361).
   * Populated from `Export.tier_duplicates`; `[]` when none or when the CLI
   * predates the field. Drives the read-only `tierDupWarning` advisory node.
   */
  tierDuplicates: TierDuplicate[];
  /**
   * Config repo key (the key under `repos:` in config.yml) for a configured
   * repo (#288), or null for a track-only repo not present in `Export.repos`
   * (and for the "(no repo)" bucket). Used to prefill New Track from a repo node.
   */
  folder: string | null;
  /** true when the configured repo has a local checkout on disk (`has_local`);
   *  false for track-only repos. */
  hasLocal: boolean;
}

/**
 * The empty-state child of a repo node that has zero tracks (#288). Rendered as
 * a dimmed "No tracks yet — add one" affordance whose click starts a New Track
 * prefilled for THIS repo.
 */
export interface EmptyRepoNode {
  kind: "emptyRepo";
  /** The parent repo's github slug, or "(no repo)". */
  repo: string;
  /** The parent repo's config folder key, or null. */
  folder: string | null;
}

/**
 * On-demand "fetch open issues" affordance under a trackless registered repo
 * (#303). `export` only emits untracked issues for repos that have tracks, so a
 * trackless repo's open issues never arrive automatically — this node fetches
 * them via `list-open-issues` on click. `fetched` drives the label (Fetch →
 * Refresh), `count` is the number found once fetched.
 */
export interface FetchUntrackedNode {
  kind: "fetchUntracked";
  /** The parent repo's github slug (never "(no repo)" — that can't be queried). */
  repo: string;
  fetched: boolean;
  count: number;
}

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

/**
 * The repo-row description text.
 *
 * Tier and GitHub visibility are orthogonal axes that happen to share the
 * "private"/"public" vocabulary, so rendering them together reads as a
 * contradiction (e.g. "private ⚠ public"). For a PUBLIC repo the visibility
 * warning is what matters, so we surface only the `⚠ public` badge; otherwise
 * we show the tier (today always "private"; forward-compat for when the
 * two-tier model lands and a repo can be "shared").
 */
export function repoDescription(node: RepoNode): string {
  return node.isPublic ? "⚠ public" : node.tier;
}

/**
 * The two independent visibility axes of a track, rendered for the tree:
 *   - repo visibility: PUBLIC (`$(globe)`) vs PRIVATE/unknown (`$(lock)`)
 *   - tier: shared (`$(cloud)`, travels via git) vs unshared (no glyph, local only)
 *
 * The only high-stakes corner is **public + shared** — the plan is committed to
 * a public repo and is world-visible — so it (and only it) gets a leading
 * `$(warning)` glyph (theme-coloured by VS Code automatically) and the word
 * "exposed". The three safe states stay quiet so the one alarm keeps its meaning.
 *
 * Accessibility (#208 lineage): every state is distinguishable by glyph SHAPE and
 * literal text, never colour alone. A null/unknown `visibility` is treated as
 * PRIVATE (the safe default) so a missing field never under-warns. Pure — the
 * caller (tree.ts) wraps `tooltipMarkdown` in a MarkdownString.
 */
export interface VisibilityTierBadge {
  /** Unicode glyph cluster for the plain-text TreeItem.description, e.g. "⚠️🌐☁️". */
  descriptionPrefix: string;
  /** Markdown (icons need MarkdownString with supportThemeIcons). */
  tooltipMarkdown: string;
  /** True only for public + shared — the world-visible leak state. */
  exposed: boolean;
}

export function visibilityTierBadge(track: Track): VisibilityTierBadge {
  const isShared = track.tier === "shared";
  const isPublic = track.visibility === "PUBLIC"; // null/PRIVATE → safe default
  const exposed = isShared && isPublic;

  // The visible badge lands in TreeItem.description, which is PLAIN TEXT and
  // does NOT resolve $(codicon) syntax — so it uses Unicode glyphs that render
  // literally. (The tooltip below keeps codicons; it's a themed MarkdownString.)
  const visIcon = isPublic ? "🌐" : "🔒";
  const tierIcon = isShared ? "☁️" : "";
  const descriptionPrefix = (exposed ? "⚠️" : "") + visIcon + tierIcon;

  // Tooltip codicons render (and theme-colour the warning) inside the
  // MarkdownString(supportThemeIcons) the caller wraps tooltipMarkdown in.
  const visGlyph = isPublic ? "$(globe)" : "$(lock)";
  const tierGlyph = isShared ? "$(cloud)" : "";

  const visWord = isPublic ? "public repo" : "private repo";
  const tierWord = isShared ? "shared tier — travels via git push/pull" : "local only — never pushed";
  const tooltipMarkdown = exposed
    ? `$(warning) **Exposed** — ${visGlyph} ${visWord} · ${tierGlyph} shared tier. ` +
      `This plan is committed to a public repo and is **world-visible**.`
    : `${visGlyph} ${visWord} · ${isShared ? tierGlyph + " " : ""}${tierWord}.`;

  return { descriptionPrefix, tooltipMarkdown, exposed };
}

/**
 * Derives a StatusCategory for a track.
 * Blocker presence (array non-empty) OR status === "blocked" → "blocked";
 * this override takes priority over every other status value.
 */
export function statusCategory(track: Track): StatusCategory {
  if (track.blockers.length > 0 || track.status === "blocked") {
    return "blocked";
  }
  if (track.status === "shipped") {
    return "shipped";
  }
  if (track.status === "parked" || track.status === "abandoned") {
    return "parked";
  }
  // active / in-progress / anything else
  return "active";
}

/**
 * Returns a one-line hint for the sidebar:
 * - "⛔ #<first blocker>" when blockers are present
 * - "→ #<first next_up>" when next_up is non-empty
 * - null otherwise
 */
export function trackHint(track: Track): string | null {
  if (track.blockers.length > 0) {
    return `⛔ #${track.blockers[0]}`;
  }
  if (track.next_up.length > 0) {
    return `→ #${track.next_up[0]}`;
  }
  return null;
}

/**
 * Builds the sidebar tree from an Export.
 *
 * Grouping rules:
 * - Every configured repo in `Export.repos` is seeded as a node FIRST (#288),
 *   keyed by its github slug, so a registered repo appears even with zero tracks.
 * - Tracks are then grouped by `repo`, preserving first-seen order; a track-only
 *   repo (not in `Export.repos`) still gets a node, appended after the config repos.
 * - Tracks with a null or empty `repo` are bucketed under "(no repo)".
 * - A RepoNode is marked `isPublic:true` if ANY of its tracks has visibility
 *   "PUBLIC"; an empty config repo derives `isPublic` from its own visibility.
 * - `tier` is taken from the first track in the group (fallback "private").
 * - `folder`/`hasLocal` come from the matching config repo (null/false otherwise).
 */
export function buildTree(exp: Export): RepoNode[] {
  // Use a Map to maintain insertion order (config repos first, then track-only).
  const repoMap = new Map<string, RepoNode>();

  // Seed a node for every configured repo BEFORE grouping tracks, so an empty
  // registered repo still shows up. Keyed by github slug; a config repo with a
  // null slug can't be matched to tracks (which key by slug) so we skip it.
  for (const cr of exp.repos ?? []) {
    if (cr.repo == null || cr.repo === "" || repoMap.has(cr.repo)) {
      continue;
    }
    repoMap.set(cr.repo, {
      kind: "repo",
      repo: cr.repo,
      // An empty repo's badge comes from its own GitHub visibility.
      isPublic: cr.visibility === "PUBLIC",
      tier: "private",
      tracks: [],
      untracked: [],
      tierDuplicates: [],
      folder: cr.folder,
      hasLocal: cr.has_local,
    });
  }

  for (const track of exp.tracks) {
    const repoKey = track.repo == null || track.repo === "" ? "(no repo)" : track.repo;

    if (!repoMap.has(repoKey)) {
      repoMap.set(repoKey, {
        kind: "repo",
        repo: repoKey,
        isPublic: false,
        tier: track.tier ?? "private",
        tracks: [],
        untracked: [],
        tierDuplicates: [],
        folder: null,
        hasLocal: false,
      });
    }

    const repoNode = repoMap.get(repoKey)!;

    // The tier comes from the first track to land in the group (a seeded empty
    // repo defaults to "private"; the first real track refines it).
    if (repoNode.tracks.length === 0) {
      repoNode.tier = track.tier ?? "private";
    }

    // Any PUBLIC track flips the repo flag.
    if (track.visibility === "PUBLIC") {
      repoNode.isPublic = true;
    }

    repoNode.tracks.push({
      kind: "track",
      name: track.name,
      repo: track.repo,
      status: track.status,
      category: statusCategory(track),
      open: track.rollup.open,
      closed: track.rollup.closed,
      hint: trackHint(track),
      track,
    });
  }

  // Populate untracked issues per repo from the additive export field.
  // The null-repo bucket ("(no repo)") gets [] — untracked is always repo-keyed.
  for (const node of repoMap.values()) {
    if (node.repo !== "(no repo)") {
      node.untracked = exp.untracked?.find(u => u.repo === node.repo)?.issues ?? [];
      node.tierDuplicates =
        exp.tier_duplicates?.filter(d => d.repo === node.repo) ?? [];
    }
  }

  return Array.from(repoMap.values());
}

/**
 * Activity-bar badge counts (#215): blocked tracks + total open issues, across
 * every track. Pure. The caller prefers `blocked` (the louder signal) and falls
 * back to `open`. "Blocked" matches the tree's own notion (`statusCategory`).
 */
export function badgeCounts(tracks: Track[]): { blocked: number; open: number } {
  let blocked = 0;
  let open = 0;
  for (const t of tracks) {
    if (statusCategory(t) === "blocked") blocked++;
    open += t.rollup.open;
  }
  return { blocked, open };
}

/**
 * Merges on-demand fetched open issues (#303) into matching repo nodes'
 * `untracked`. A TRACKLESS repo's export `untracked` is empty, so this fills it
 * from the fetch cache. A repo that HAS tracks is left untouched: the export
 * already computes its `untracked` (open-minus-tracked) fresh on every refresh,
 * so it stays authoritative and the (possibly stale) fetch snapshot must never
 * override it — otherwise an already-tracked issue could resurface under
 * Untracked between refreshes (#303 follow-up). Pure + non-mutating.
 */
export function mergeFetchedUntracked(
  repos: RepoNode[],
  fetched: Map<string, Issue[]>,
): RepoNode[] {
  if (fetched.size === 0) return repos;
  return repos.map(repo =>
    repo.tracks.length === 0 && fetched.has(repo.repo)
      ? { ...repo, untracked: fetched.get(repo.repo)! }
      : repo,
  );
}

// ---------------------------------------------------------------------------
// Auto-slot suggestion nodes (#241)
// ---------------------------------------------------------------------------

/**
 * Builds the SuggestedIssueNode for a single suggestion entry, resolving the
 * full Issue (for the title) from the repo's untracked list. When the issue is
 * no longer in the untracked list (e.g. it got tracked between scan and render),
 * a minimal placeholder Issue is synthesized so the node still renders coherently
 * — the next refresh drops it. Pure.
 */
export function suggestedIssueNode(
  repo: string,
  entry: SuggestionEntry,
  untracked: Issue[],
  tier: "suggested" | "needsReview",
): SuggestedIssueNode {
  const issue =
    untracked.find(i => i.number === entry.issueNumber) ??
    ({
      number: entry.issueNumber,
      title: `#${entry.issueNumber}`,
      state: "open",
      assignee: "—",
      milestone: null,
      in_progress: false,
      in_progress_label: false,
      blocked_by: [],
      blocking: [],
    } as Issue);
  return {
    kind: "suggestedIssue",
    repo,
    issue,
    suggestedTrack: entry.suggestedTrack,
    ...(entry.runnerUp ? { runnerUp: entry.runnerUp } : {}),
    confidence: entry.confidence,
    rationale: entry.rationale,
    margin: entry.margin,
    tier,
  };
}

// ---------------------------------------------------------------------------
// Track sort
// ---------------------------------------------------------------------------

export type TrackSort = "default" | "blocked" | "open" | "name";

/**
 * Orders a repo's tracks by `mode`. Pure, non-mutating, stable, deterministic.
 *
 * - `"default"` → a copy in the given order (unchanged).
 * - `"blocked"` → blocked tracks first (`category === "blocked"`), then the rest;
 *   within each group, tie-break by `open` descending, then `name` ascending.
 * - `"open"` → by `open` descending; tie-break `name` ascending.
 * - `"name"` → by `name` ascending (localeCompare).
 *
 * Always returns a NEW array; the input is never mutated.
 * Uses a total-order comparator (includes `name` as the final tie-break) so
 * output is deterministic regardless of engine sort-stability.
 */
export function sortTracks(tracks: TrackNode[], mode: TrackSort): TrackNode[] {
  if (mode === "default") {
    return tracks.slice();
  }

  const copy = tracks.slice();

  if (mode === "name") {
    copy.sort((a, b) => a.name.localeCompare(b.name));
    return copy;
  }

  if (mode === "open") {
    copy.sort((a, b) => {
      // open descending
      if (b.open !== a.open) return b.open - a.open;
      // name ascending as tie-break (total order)
      return a.name.localeCompare(b.name);
    });
    return copy;
  }

  // mode === "blocked"
  copy.sort((a, b) => {
    const aBlocked = a.category === "blocked" ? 0 : 1;
    const bBlocked = b.category === "blocked" ? 0 : 1;
    // blocked group first
    if (aBlocked !== bBlocked) return aBlocked - bBlocked;
    // within group: open descending
    if (b.open !== a.open) return b.open - a.open;
    // name ascending as tie-break (total order)
    return a.name.localeCompare(b.name);
  });
  return copy;
}

/**
 * Whether repo nodes should render expanded.
 *
 * Default is collapsed (so a many-track repo doesn't flood the sidebar), with
 * two ways to expand: the `workPlan.expandReposByDefault` setting, or a
 * single-repo workspace (forcing a lone user to click one node adds no value).
 */
export function shouldExpandRepos(repoCount: number, expandSetting: boolean): boolean {
  return expandSetting || repoCount <= 1;
}
