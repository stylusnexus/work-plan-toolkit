/**
 * Pure lens derivation and filtering for work-plan exports.
 *
 * A "lens" is a cross-cutting view that filters the export's track list.
 * No vscode imports — safe for testing without a VS Code environment.
 */

import type { Export } from "../model.ts";
import type { StatusCategory, TrackSort } from "../treeModel.ts";
import { statusCategory } from "../treeModel.ts";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type Lens =
  | { kind: "all" }
  | { kind: "repo"; repo: string }
  | { kind: "milestone"; milestone: string }
  | { kind: "status"; status: StatusCategory }
  | { kind: "blocked" };

export interface LensChoice {
  id: string;
  label: string;
  lens: Lens;
}

// ---------------------------------------------------------------------------
// availableLenses
// ---------------------------------------------------------------------------

/**
 * Derives the deterministic list of selectable lenses from export data.
 *
 * Order:
 *   1. Always: "All tracks"
 *   2. One entry per distinct non-empty issue.milestone across all tracks,
 *      in first-seen (track order, then issue order) order.
 *   3. Status lenses ("Status: Active", "Status: Shipped", "Status: Parked"),
 *      in that fixed order, each only when at least one track falls in that
 *      category per `statusCategory`. The "blocked" category is intentionally
 *      NOT surfaced here — it has its own standalone "Blocked tracks" lens.
 *   4. "Blocked tracks" — only when at least one track has non-empty blockers.
 *
 * Categories with no members are omitted. Per-repo lenses are intentionally NOT
 * listed here: repo scoping is the single "Focus current repo / Display all
 * repos" toggle the picker adds at the top (it enumerated every repo, which was
 * noise once the tree shows all repos by default). The `repo` Lens kind still
 * exists and applyLens still honors it — only this menu enumeration is dropped.
 */
export function availableLenses(exp: Export): LensChoice[] {
  const choices: LensChoice[] = [];

  // 1. Always: all
  choices.push({ id: "all", label: "All tracks", lens: { kind: "all" } });

  // 2. Distinct non-empty milestones, sorted numeric-aware ascending so
  //    version-like names order naturally (v0.5.0 before v0.10.0) instead of
  //    appearing in issue-iteration order (#268).
  const seenMilestones = new Set<string>();
  for (const track of exp.tracks) {
    for (const issue of track.issues) {
      if (issue.milestone !== null && issue.milestone !== "") {
        seenMilestones.add(issue.milestone);
      }
    }
  }
  for (const milestone of [...seenMilestones].sort((a, b) =>
    a.localeCompare(b, undefined, { numeric: true }),
  )) {
    choices.push({
      id: `milestone:${milestone}`,
      label: `Milestone: ${milestone}`,
      lens: { kind: "milestone", milestone },
    });
  }

  // 3. Status lenses — one per category that has at least one member.
  //    Driven by the SAME statusCategory classifier the tree uses, so the lens
  //    and the sidebar always agree. "blocked" is omitted here on purpose; it
  //    keeps its own standalone "Blocked tracks" lens below.
  const statusLensSpecs: { status: StatusCategory; label: string }[] = [
    { status: "active", label: "Status: Active" },
    { status: "shipped", label: "Status: Shipped" },
    { status: "parked", label: "Status: Parked" },
  ];
  for (const spec of statusLensSpecs) {
    if (exp.tracks.some(t => statusCategory(t) === spec.status)) {
      choices.push({
        id: `status:${spec.status}`,
        label: spec.label,
        lens: { kind: "status", status: spec.status },
      });
    }
  }

  // 4. Blocked — only when at least one track has blockers
  const hasBlocked = exp.tracks.some(t => t.blockers.length > 0);
  if (hasBlocked) {
    choices.push({
      id: "blocked",
      label: "Blocked tracks",
      lens: { kind: "blocked" },
    });
  }

  return choices;
}

// ---------------------------------------------------------------------------
// applyLens
// ---------------------------------------------------------------------------

/**
 * Returns a NEW Export with `tracks` filtered to the lens.
 * The `schema` and `generated_at` fields are preserved unchanged.
 * Tracks are kept whole — no per-issue surgery.
 * The input Export is never mutated.
 */
export function applyLens(exp: Export, lens: Lens): Export {
  let filteredTracks: Export["tracks"];

  switch (lens.kind) {
    case "all":
      filteredTracks = exp.tracks.slice();
      break;

    case "repo":
      filteredTracks = exp.tracks.filter(t => t.repo === lens.repo);
      break;

    case "milestone":
      filteredTracks = exp.tracks.filter(t =>
        t.issues.some(issue => issue.milestone === lens.milestone)
      );
      break;

    case "status":
      // Reuse the tree's classifier so this filter and the sidebar agree.
      filteredTracks = exp.tracks.filter(t => statusCategory(t) === lens.status);
      break;

    case "blocked":
      filteredTracks = exp.tracks.filter(t => t.blockers.length > 0);
      break;
  }

  return {
    schema: exp.schema,
    generated_at: exp.generated_at,
    tracks: filteredTracks,
    // Forward untracked unchanged. The tree always renders from the filtered
    // export, and buildTree only attaches a repo's untracked issues when that
    // repo still has a matching (filtered) track — so dropping the field here
    // would make the Untracked bucket vanish under EVERY lens, including "all".
    ...(exp.untracked !== undefined && { untracked: exp.untracked }),
    // Forward configured repos, SCOPED to the lens. buildTree seeds a node for
    // every forwarded repo, so a zero-track repo still shows in the Tracks view
    // (#288). But under a filtering lens the forwarded set must shrink, or every
    // OTHER configured repo gets seeded with zero tracks and renders the
    // "No tracks yet — add one" empty-state — indistinguishable from a genuinely
    // empty repo. With repo auto-focus on (#357) that turned "focus this repo"
    // into "every other repo looks deleted." So:
    //   - "all": forward all configured repos (zero-track repos still show).
    //   - "repo": forward only the focused repo (others disappear cleanly, the
    //     normal meaning of a filter; the focused repo still shows even with zero
    //     tracks so its "add a track" / fetch-issues affordances remain).
    //   - milestone/status/blocked: forward only configured repos that still
    //     have a surviving track — a repo filtered down to nothing drops out
    //     rather than masquerading as empty.
    ...(exp.repos !== undefined && { repos: scopeReposToLens(exp.repos, lens, filteredTracks) }),
  };
}

/**
 * Narrows the configured-repos list to match a lens (see applyLens). Pure; the
 * input array is never mutated. The "all" lens forwards everything; "repo"
 * forwards only the focused slug; the filtering lenses forward only repos that
 * still own a surviving filtered track.
 */
function scopeReposToLens(
  repos: NonNullable<Export["repos"]>,
  lens: Lens,
  filteredTracks: Export["tracks"],
): NonNullable<Export["repos"]> {
  switch (lens.kind) {
    case "all":
      return repos;
    case "repo":
      return repos.filter(r => r.repo === lens.repo);
    case "milestone":
    case "status":
    case "blocked": {
      const surviving = new Set(filteredTracks.map(t => t.repo));
      // A config repo with a null slug can't own a track — drop it under a
      // filtering lens (it only earns a node under "all", via #288 seeding).
      return repos.filter(r => r.repo != null && surviving.has(r.repo));
    }
  }
}

// ---------------------------------------------------------------------------
// describeView
// ---------------------------------------------------------------------------

/**
 * Builds a short, human-readable label for the active lens + sort, suitable for
 * a TreeView.description (shown inline next to the view title). Returns "" when
 * the lens is "all" AND the sort is "default" — i.e. nothing to surface (#209).
 *
 * Examples:
 *   ({kind:"milestone", milestone:"v2.0.0"}, "blocked") → "milestone: v2.0.0 · blocked-first"
 *   ({kind:"blocked"}, "default")                       → "blocked"
 *   ({kind:"all"}, "name")                              → "name A–Z"
 *   ({kind:"all"}, "default")                           → ""
 */
export function describeView(lens: Lens, sort: TrackSort): string {
  const parts: string[] = [];

  switch (lens.kind) {
    case "repo":
      // Short name only (drop the "org/" prefix): the view title truncates hard
      // in a narrow sidebar — "repo: stylusnexus/work-plan-toolkit" collapsed to
      // an illegible "r…", hiding the one signal that a repo lens is active. The
      // bare repo name survives truncation and still identifies the focus.
      parts.push(`repo: ${lens.repo.split("/").pop() ?? lens.repo}`);
      break;
    case "milestone":
      parts.push(`milestone: ${lens.milestone}`);
      break;
    case "status":
      parts.push(`status: ${lens.status}`);
      break;
    case "blocked":
      parts.push("blocked");
      break;
    case "all":
      break;
  }

  switch (sort) {
    case "blocked":
      parts.push("blocked-first");
      break;
    case "open":
      parts.push("most-open");
      break;
    case "name":
      parts.push("name A–Z");
      break;
    case "default":
      break;
  }

  return parts.join(" · ");
}
