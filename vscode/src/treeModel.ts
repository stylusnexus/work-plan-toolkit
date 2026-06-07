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
