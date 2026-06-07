import type { Export, Track } from "./model.ts";

// ---------------------------------------------------------------------------
// Node types
// ---------------------------------------------------------------------------

export type StatusCategory = "blocked" | "active" | "shipped" | "parked";

export interface TrackNode {
  kind: "track";
  name: string;
  repo: string | null;
  status: string;
  category: StatusCategory;
  /** rollup.open */
  open: number;
  /** "⛔ #4821" | "→ #87" | null */
  hint: string | null;
  /** The raw track — passed to commands/webview by the provider. */
  track: Track;
}

export interface RepoNode {
  kind: "repo";
  /** "stylusnexus/CritForge" or "(no repo)" for the null-repo bucket. */
  repo: string;
  /** true when visibility === "PUBLIC" on any child track → ⚠ badge. */
  isPublic: boolean;
  /** Tier from the first track (today "private"). */
  tier: string;
  tracks: TrackNode[];
}

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

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
 * - Tracks are grouped by `repo`, preserving first-seen repo order.
 * - Tracks with a null or empty `repo` are bucketed under "(no repo)".
 * - A RepoNode is marked `isPublic:true` if ANY of its tracks has visibility "PUBLIC".
 * - `tier` is taken from the first track in the group (fallback "private").
 */
export function buildTree(exp: Export): RepoNode[] {
  // Use a Map to maintain insertion order (first-seen repo key).
  const repoMap = new Map<string, RepoNode>();

  for (const track of exp.tracks) {
    const repoKey = track.repo == null || track.repo === "" ? "(no repo)" : track.repo;

    if (!repoMap.has(repoKey)) {
      repoMap.set(repoKey, {
        kind: "repo",
        repo: repoKey,
        isPublic: false,
        tier: track.tier ?? "private",
        tracks: [],
      });
    }

    const repoNode = repoMap.get(repoKey)!;

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
      hint: trackHint(track),
      track,
    });
  }

  return Array.from(repoMap.values());
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
