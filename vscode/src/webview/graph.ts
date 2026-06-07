/**
 * Pure Mermaid graph derivation from a work-plan Export.
 *
 * No vscode imports. No Date / Math.random — output is fully deterministic.
 */

import type { Export, Track } from "../model.ts";
import { statusCategory } from "../treeModel.ts";

// ---------------------------------------------------------------------------
// Public surface
// ---------------------------------------------------------------------------

export interface ToMermaidOptions {
  /** When true, render only the dependency neighborhood of selectedTrack. */
  focus?: boolean;
}

/**
 * Derives a Mermaid LR graph definition from a work-plan export.
 *
 * @param exp           - The parsed export JSON.
 * @param selectedTrack - Optional track name to highlight with a 'selected' class.
 * @param opts          - Optional options; opts.focus scopes the graph to the selected track.
 * @returns             Mermaid graph definition string (deterministic).
 */
export function toMermaid(exp: Export, selectedTrack?: string, opts?: ToMermaidOptions): string {
  // Focus mode: render only the selected track's neighbourhood, but only when
  // focus is requested AND the named track actually exists. Otherwise fall back
  // to the full graph.
  if (opts?.focus === true && selectedTrack !== undefined) {
    const selectedTrackObj = exp.tracks.find(t => t.name === selectedTrack);
    if (selectedTrackObj !== undefined) {
      return _toMermaidFocused(exp, selectedTrackObj);
    }
  }
  return _toMermaidFull(exp, selectedTrack);
}

// ---------------------------------------------------------------------------
// Full graph (existing behaviour, refactored into a private function)
// ---------------------------------------------------------------------------

function _toMermaidFull(exp: Export, selectedTrack?: string): string {
  const lines: string[] = [];

  lines.push("graph LR");

  // Class definitions
  lines.push("  classDef blocked fill:#fee2e2,stroke:#ef4444,color:#7f1d1d");
  lines.push("  classDef selected fill:#dbeafe,stroke:#3b82f6,color:#1e3a8a,stroke-width:2px");

  // Build an issue title index from all tracks' issues[].
  const titleIndex = new Map<number, string>();
  for (const track of exp.tracks) {
    for (const issue of track.issues) {
      if (!titleIndex.has(issue.number)) {
        titleIndex.set(issue.number, issue.title);
      }
    }
  }

  // issueOwner: issue number → track name that owns it (first match wins).
  const issueOwner = new Map<number, string>();
  for (const track of exp.tracks) {
    for (const issue of track.issues) {
      if (!issueOwner.has(issue.number)) {
        issueOwner.set(issue.number, track.name);
      }
    }
  }

  // Collect issue numbers referenced as blocker or next_up (in insertion order).
  const referencedIssues = new Map<number, true>();
  for (const track of exp.tracks) {
    for (const n of track.blockers) {
      referencedIssues.set(n, true);
    }
    for (const n of track.next_up) {
      referencedIssues.set(n, true);
    }
  }

  // Emit track nodes
  lines.push("");
  lines.push("  %% Track nodes");
  for (const track of exp.tracks) {
    const id = trackId(track.name);
    const label = mermaidLabel(track.name);
    lines.push(`  ${id}["${label}"]`);
  }

  // Emit issue nodes (only those referenced in blockers/next_up)
  lines.push("");
  lines.push("  %% Issue nodes");
  for (const [num] of referencedIssues) {
    const id = `i_${num}`;
    const title = titleIndex.get(num);
    const label = title !== undefined ? `#${num} ${mermaidLabel(title)}` : `#${num}`;
    lines.push(`  ${id}(["${label}"])`);
  }

  // Emit edges (per track, in track order)
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
      lines.push(`  ${tid} -->|next_up| i_${first}`);
      let prev = first;
      for (const n of rest) {
        if (n !== prev) {
          lines.push(`  i_${prev} -.->|then| i_${n}`);
        }
        prev = n;
      }
    }
  }

  // Class assignments
  lines.push("");
  lines.push("  %% Class assignments");

  const blockedIds: string[] = [];
  for (const track of exp.tracks) {
    if (statusCategory(track) === "blocked") {
      blockedIds.push(trackId(track.name));
    }
  }
  if (blockedIds.length > 0) {
    lines.push(`  class ${blockedIds.join(",")} blocked`);
  }

  if (selectedTrack !== undefined) {
    const selId = trackId(selectedTrack);
    lines.push(`  class ${selId} selected`);
  }

  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Focused graph — only T's dependency neighbourhood
// ---------------------------------------------------------------------------

function _toMermaidFocused(exp: Export, t: Track): string {
  const lines: string[] = [];
  lines.push("graph LR");
  lines.push("  classDef blocked fill:#fee2e2,stroke:#ef4444,color:#7f1d1d");
  lines.push("  classDef selected fill:#dbeafe,stroke:#3b82f6,color:#1e3a8a,stroke-width:2px");

  // Build title index from all tracks (titles may live on any track).
  const titleIndex = new Map<number, string>();
  for (const tr of exp.tracks) {
    for (const issue of tr.issues) {
      if (!titleIndex.has(issue.number)) {
        titleIndex.set(issue.number, issue.title);
      }
    }
  }

  // issueOwner: issue number → track name (first-match).
  const issueOwner = new Map<number, string>();
  for (const tr of exp.tracks) {
    for (const issue of tr.issues) {
      if (!issueOwner.has(issue.number)) {
        issueOwner.set(issue.number, tr.name);
      }
    }
  }

  // Determine which track nodes to include:
  //   - always: the selected track itself.
  //   - for each blocker b of T: the owner track of b (if b is owned by another track).
  const includedTrackNames = new Set<string>([t.name]);
  for (const b of t.blockers) {
    const ownerName = issueOwner.get(b);
    if (ownerName !== undefined && ownerName !== t.name) {
      includedTrackNames.add(ownerName);
    }
  }

  // Determine which issue nodes to include:
  //   - T's blockers and T's next_up (in that order, deduped, preserving insertion order).
  const includedIssues = new Map<number, true>();
  for (const b of t.blockers) {
    includedIssues.set(b, true);
  }
  for (const n of t.next_up) {
    includedIssues.set(n, true);
  }

  // Emit track nodes (only the included ones; preserve original track order).
  lines.push("");
  lines.push("  %% Track nodes");
  for (const tr of exp.tracks) {
    if (!includedTrackNames.has(tr.name)) continue;
    const id = trackId(tr.name);
    const label = mermaidLabel(tr.name);
    lines.push(`  ${id}["${label}"]`);
  }

  // Emit issue nodes.
  lines.push("");
  lines.push("  %% Issue nodes");
  for (const [num] of includedIssues) {
    const id = `i_${num}`;
    const title = titleIndex.get(num);
    const label = title !== undefined ? `#${num} ${mermaidLabel(title)}` : `#${num}`;
    lines.push(`  ${id}(["${label}"])`);
  }

  // Emit edges (only those relevant to T).
  lines.push("");
  lines.push("  %% Edges");

  const tid = trackId(t.name);

  // blocks edges from T's blockers → T
  for (const b of t.blockers) {
    lines.push(`  i_${b} -->|blocks| ${tid}`);
    // owns edge from owning track → T
    const ownerName = issueOwner.get(b);
    if (ownerName !== undefined && ownerName !== t.name) {
      const ownerId = trackId(ownerName);
      lines.push(`  ${ownerId} -->|owns #${b}| ${tid}`);
    }
  }

  // next_up flow edges for T
  if (t.next_up.length > 0) {
    const [first, ...rest] = t.next_up;
    lines.push(`  ${tid} -->|next_up| i_${first}`);
    let prev = first;
    for (const n of rest) {
      if (n !== prev) {
        lines.push(`  i_${prev} -.->|then| i_${n}`);
      }
      prev = n;
    }
  }

  // Class assignments
  lines.push("");
  lines.push("  %% Class assignments");

  // blocked class — only for included tracks
  const blockedIds: string[] = [];
  for (const tr of exp.tracks) {
    if (!includedTrackNames.has(tr.name)) continue;
    if (statusCategory(tr) === "blocked") {
      blockedIds.push(trackId(tr.name));
    }
  }
  if (blockedIds.length > 0) {
    lines.push(`  class ${blockedIds.join(",")} blocked`);
  }

  // selected class
  lines.push(`  class ${tid} selected`);

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
