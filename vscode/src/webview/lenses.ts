/**
 * Pure lens derivation and filtering for work-plan exports.
 *
 * A "lens" is a cross-cutting view that filters the export's track list.
 * No vscode imports — safe for testing without a VS Code environment.
 */

import type { Export } from "../model.ts";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type Lens =
  | { kind: "all" }
  | { kind: "repo"; repo: string }
  | { kind: "milestone"; milestone: string }
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
 *   4. "Blocked tracks" — only when at least one track has non-empty blockers.
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

  // 3. Distinct non-empty milestones in first-seen order
  const seenMilestones = new Set<string>();
  for (const track of exp.tracks) {
    for (const issue of track.issues) {
      if (issue.milestone !== null && issue.milestone !== "" && !seenMilestones.has(issue.milestone)) {
        seenMilestones.add(issue.milestone);
        choices.push({
          id: `milestone:${issue.milestone}`,
          label: `Milestone: ${issue.milestone}`,
          lens: { kind: "milestone", milestone: issue.milestone },
        });
      }
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
  };
}
