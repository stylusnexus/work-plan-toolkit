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
 *   2. One entry per distinct track.repo, in first-seen order.
 *   3. One entry per distinct non-empty issue.milestone across all tracks,
 *      in first-seen (track order, then issue order) order.
 *   4. Status lenses ("Status: Active", "Status: Shipped", "Status: Parked"),
 *      in that fixed order, each only when at least one track falls in that
 *      category per `statusCategory`. The "blocked" category is intentionally
 *      NOT surfaced here — it has its own standalone "Blocked tracks" lens.
 *   5. "Blocked tracks" — only when at least one track has non-empty blockers.
 *
 * Categories with no members are omitted.
 */
export function availableLenses(exp: Export): LensChoice[] {
  const choices: LensChoice[] = [];

  // 1. Always: all
  choices.push({ id: "all", label: "All tracks", lens: { kind: "all" } });

  // 2. Distinct repos in first-seen order
  const seenRepos = new Set<string>();
  for (const track of exp.tracks) {
    if (!seenRepos.has(track.repo)) {
      seenRepos.add(track.repo);
      choices.push({
        id: `repo:${track.repo}`,
        label: `Repo: ${track.repo}`,
        lens: { kind: "repo", repo: track.repo },
      });
    }
  }

  // 3. Distinct non-empty milestones, sorted numeric-aware ascending so
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

  // 4. Status lenses — one per category that has at least one member.
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

  // 5. Blocked — only when at least one track has blockers
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
    // Forward configured repos unchanged (#288). buildTree seeds a node for
    // every registered repo so a zero-track repo (e.g. a just-added agent-armor)
    // still shows in the Tracks view. Dropping the field here means buildTree's
    // seeding loop iterates [] and empty repos vanish under EVERY lens — exactly
    // the untracked bug above, one field over. The Plans view reads rawExport so
    // it kept showing them; the split between the two views was this omission.
    ...(exp.repos !== undefined && { repos: exp.repos }),
  };
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
      parts.push(`repo: ${lens.repo}`);
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
