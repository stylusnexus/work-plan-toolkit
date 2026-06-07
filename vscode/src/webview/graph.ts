/**
 * Pure Mermaid graph derivation from a work-plan Export.
 *
 * No vscode imports. No Date / Math.random — output is fully deterministic.
 */

import type { Export } from "../model.ts";
import { statusCategory } from "../treeModel.ts";

// ---------------------------------------------------------------------------
// Public surface
// ---------------------------------------------------------------------------

/**
 * Derives a Mermaid LR graph definition from a work-plan export.
 *
 * @param exp           - The parsed export JSON.
 * @param selectedTrack - Optional track name to highlight with a 'selected' class.
 * @returns             Mermaid graph definition string (deterministic).
 */
export function toMermaid(exp: Export, selectedTrack?: string): string {
  const lines: string[] = [];

  lines.push("graph LR");

  // -------------------------------------------------------------------------
  // Class definitions
  // -------------------------------------------------------------------------

  lines.push("  classDef blocked fill:#fee2e2,stroke:#ef4444,color:#7f1d1d");
  lines.push("  classDef selected fill:#dbeafe,stroke:#3b82f6,color:#1e3a8a,stroke-width:2px");

  // -------------------------------------------------------------------------
  // Build an issue title index from all tracks' issues[].
  // Use the first occurrence if the same issue number appears in multiple tracks.
  // -------------------------------------------------------------------------

  const titleIndex = new Map<number, string>();
  for (const track of exp.tracks) {
    for (const issue of track.issues) {
      if (!titleIndex.has(issue.number)) {
        titleIndex.set(issue.number, issue.title);
      }
    }
  }

  // -------------------------------------------------------------------------
  // Determine which issue numbers appear in any track's issues[]
  // so we can build the cross-track owns edges.
  // issueOwner: issue number → track name that owns it (first match wins).
  // -------------------------------------------------------------------------

  const issueOwner = new Map<number, string>();
  for (const track of exp.tracks) {
    for (const issue of track.issues) {
      if (!issueOwner.has(issue.number)) {
        issueOwner.set(issue.number, track.name);
      }
    }
  }

  // -------------------------------------------------------------------------
  // Collect issue numbers referenced as blocker or next_up (in first-reference
  // order across all tracks, preserving track-order and within-track order).
  // -------------------------------------------------------------------------

  // Use a Map to maintain insertion order without Set reordering.
  const referencedIssues = new Map<number, true>();
  for (const track of exp.tracks) {
    for (const n of track.blockers) {
      referencedIssues.set(n, true);
    }
    for (const n of track.next_up) {
      referencedIssues.set(n, true);
    }
  }

  // -------------------------------------------------------------------------
  // Emit track nodes
  // -------------------------------------------------------------------------

  lines.push("");
  lines.push("  %% Track nodes");
  for (const track of exp.tracks) {
    const id = trackId(track.name);
    const label = mermaidLabel(track.name);
    lines.push(`  ${id}["${label}"]`);
  }

  // -------------------------------------------------------------------------
  // Emit issue nodes (only those referenced in blockers/next_up)
  // -------------------------------------------------------------------------

  lines.push("");
  lines.push("  %% Issue nodes");
  for (const [num] of referencedIssues) {
    const id = `i_${num}`;
    const title = titleIndex.get(num);
    const label = title !== undefined ? `#${num} ${mermaidLabel(title)}` : `#${num}`;
    lines.push(`  ${id}(["${label}"])`);
  }

  // -------------------------------------------------------------------------
  // Emit edges (per track, in track order)
  // -------------------------------------------------------------------------

  lines.push("");
  lines.push("  %% Edges");

  for (const track of exp.tracks) {
    const tid = trackId(track.name);

    // blocks edges: i_<b> -->|blocks| t_<track>
    for (const b of track.blockers) {
      lines.push(`  i_${b} -->|blocks| ${tid}`);

      // owns (cross-track): if issue b is owned by another track O, emit
      //   t_<O> -->|owns #<b>| t_<track>
      const ownerName = issueOwner.get(b);
      if (ownerName !== undefined && ownerName !== track.name) {
        const ownerId = trackId(ownerName);
        lines.push(`  ${ownerId} -->|owns #${b}| ${tid}`);
      }
    }

    // next_up flow edges
    if (track.next_up.length > 0) {
      const [first, ...rest] = track.next_up;
      // Solid edge: track → first issue
      lines.push(`  ${tid} -->|next_up| i_${first}`);
      // Dashed edges between consecutive issues (skip self-transitions)
      let prev = first;
      for (const n of rest) {
        if (n !== prev) {
          lines.push(`  i_${prev} -.->|then| i_${n}`);
        }
        prev = n;
      }
    }
  }

  // -------------------------------------------------------------------------
  // Class assignments
  // -------------------------------------------------------------------------

  lines.push("");
  lines.push("  %% Class assignments");

  // Blocked tracks
  const blockedIds: string[] = [];
  for (const track of exp.tracks) {
    if (statusCategory(track) === "blocked") {
      blockedIds.push(trackId(track.name));
    }
  }
  if (blockedIds.length > 0) {
    lines.push(`  class ${blockedIds.join(",")} blocked`);
  }

  // Selected track
  if (selectedTrack !== undefined) {
    const selId = trackId(selectedTrack);
    lines.push(`  class ${selId} selected`);
  }

  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Derives a Mermaid-safe node id from a track name.
 * Replaces any character outside [A-Za-z0-9_] with `_` and prefixes with `t_`.
 */
function trackId(name: string): string {
  return "t_" + name.replace(/[^A-Za-z0-9_]/g, "_");
}

/**
 * Escapes characters that would break Mermaid `["..."]` / `(["..."])` node labels.
 * A literal `"` terminates the label early and yields a parse error; `<`/`>`/`&`
 * are escaped for HTML-label safety.
 */
function mermaidLabel(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
