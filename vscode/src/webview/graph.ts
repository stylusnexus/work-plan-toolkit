/**
 * Pure Mermaid graph derivation from a work-plan Export.
 *
 * No vscode imports. No Date / Math.random — output is fully deterministic.
 */

import type { Export, Track, Issue } from "../model.ts";
import { blockerIssue } from "../model.ts";
import { statusCategory } from "../treeModel.ts";

// ---------------------------------------------------------------------------
// Public surface
// ---------------------------------------------------------------------------

export interface ToMermaidOptions {
  /** When true, render only the dependency neighborhood of selectedTrack. */
  focus?: boolean;
  /**
   * When true, emit dark-theme classDef fills. Mermaid's SVG can't read CSS
   * vars, so the node-class colours are baked per editor theme here (#207).
   * Defaults to dark (the prior hardcoded behaviour).
   */
  dark?: boolean;
}

/**
 * classDef lines for the blocked / selected node classes, picked to read on the
 * editor's light or dark theme. Returned as Mermaid source lines.
 */
function classDefLines(dark: boolean): string[] {
  if (dark) {
    return [
      "  classDef blocked fill:#5b1d1d,stroke:#f87171,color:#fecaca",
      "  classDef selected fill:#1e3a5f,stroke:#60a5fa,color:#dbeafe,stroke-width:2px",
    ];
  }
  return [
    "  classDef blocked fill:#fee2e2,stroke:#ef4444,color:#7f1d1d",
    "  classDef selected fill:#dbeafe,stroke:#3b82f6,color:#1e3a8a,stroke-width:2px",
  ];
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
  const dark = opts?.dark ?? true;
  if (opts?.focus === true && selectedTrack !== undefined) {
    const selectedTrackObj = exp.tracks.find(t => t.name === selectedTrack);
    if (selectedTrackObj !== undefined) {
      return _toMermaidFocused(exp, selectedTrackObj, dark);
    }
  }
  return _toMermaidFull(exp, selectedTrack, dark);
}

// ---------------------------------------------------------------------------
// Full graph (existing behaviour, refactored into a private function)
// ---------------------------------------------------------------------------

function _toMermaidFull(exp: Export, selectedTrack: string | undefined, dark: boolean): string {
  const lines: string[] = [];

  lines.push("graph LR");

  // Class definitions (node styling only; edge styling is not supported here)
  lines.push(...classDefLines(dark));

  // Build a unique, collision-resistant track ID for each track name.
  const tids = buildTrackIds(exp.tracks);

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
    for (const b of track.blockers) {
      // Free-text blockers aren't issue nodes — skip them (a raw `i_${b}` of a
      // prose blocker is the Mermaid "Syntax error in text" bomb).
      const num = blockerIssue(b);
      if (num !== null) referencedIssues.set(num, true);
    }
    for (const n of track.next_up) {
      referencedIssues.set(n, true);
    }
  }

  // Emit track nodes
  lines.push("");
  lines.push("  %% Track nodes");
  for (const track of exp.tracks) {
    const id = tids.get(track.name)!;
    // Mark blocked nodes with a non-colour glyph too — the classDef fill alone
    // signals blocked by colour, which colourblind users can't read (#244).
    const marker = statusCategory(track) === "blocked" ? "⛔ " : "";
    const label = marker + mermaidLabel(track.name);
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
    const tid = tids.get(track.name)!;

    // blocks edges: i_<b> -->|blocks| t_<track>
    for (const b of track.blockers) {
      const num = blockerIssue(b);
      if (num === null) continue; // free-text blocker — not a graph edge
      lines.push(`  i_${num} -->|blocks| ${tid}`);

      // owns (cross-track): if issue b is owned by another track O, emit
      //   t_<O> -->|owns #<b>| t_<track>
      const ownerName = issueOwner.get(num);
      if (ownerName !== undefined && ownerName !== track.name) {
        const ownerId = tids.get(ownerName)!;
        lines.push(`  ${ownerId} -->|owns #${num}| ${tid}`);
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

    // depends_on edges (explicit cross-track dependencies, #102)
    const depNames = track.depends_on || [];
    for (const depName of depNames) {
      const depId = tids.get(depName) ?? trackId(depName);
      lines.push(`  ${tid} ==>|depends on| ${depId}`);
    }
  }

  // Class assignments
  lines.push("");
  lines.push("  %% Class assignments");

  const blockedIds: string[] = [];
  for (const track of exp.tracks) {
    if (statusCategory(track) === "blocked") {
      blockedIds.push(tids.get(track.name)!);
    }
  }
  if (blockedIds.length > 0) {
    lines.push(`  class ${blockedIds.join(",")} blocked`);
  }

  if (selectedTrack !== undefined) {
    const selId = tids.get(selectedTrack) ?? trackId(selectedTrack);
    lines.push(`  class ${selId} selected`);
  }

  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Focused graph — only T's dependency neighbourhood
// ---------------------------------------------------------------------------

function _toMermaidFocused(exp: Export, t: Track, dark: boolean): string {
  const lines: string[] = [];
  lines.push("graph LR");
  lines.push(...classDefLines(dark));

  // Build a unique, collision-resistant track ID for each track name.
  const tids = buildTrackIds(exp.tracks);

  // Build title index from all tracks (titles may live on any track).
  const titleIndex = new Map<number, string>();
  // Build issue object index (first-match wins, same traversal order as titleIndex).
  const issueIndex = new Map<number, Issue>();
  for (const tr of exp.tracks) {
    for (const issue of tr.issues) {
      if (!titleIndex.has(issue.number)) {
        titleIndex.set(issue.number, issue.title);
      }
      if (!issueIndex.has(issue.number)) {
        issueIndex.set(issue.number, issue);
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
  //   - tracks that T explicitly depends_on, and tracks that depend_on T (#102).
  const includedTrackNames = new Set<string>([t.name]);
  for (const b of t.blockers) {
    const num = blockerIssue(b);
    if (num === null) continue; // free-text blocker owns no track
    const ownerName = issueOwner.get(num);
    if (ownerName !== undefined && ownerName !== t.name) {
      includedTrackNames.add(ownerName);
    }
  }
  // Add dependency neighbourhood (#102)
  const depNames = t.depends_on || [];
  for (const depName of depNames) {
    includedTrackNames.add(depName);
  }
  // Reverse: add tracks that depend on T
  for (const tr of exp.tracks) {
    if ((tr.depends_on || []).includes(t.name)) {
      includedTrackNames.add(tr.name);
    }
  }

  // Determine which issue nodes to include:
  //   - T's blockers and T's next_up (in that order, deduped, preserving insertion order).
  const includedIssues = new Map<number, true>();
  for (const b of t.blockers) {
    const num = blockerIssue(b);
    if (num !== null) includedIssues.set(num, true);
  }
  for (const n of t.next_up) {
    includedIssues.set(n, true);
  }

  // Emit track nodes (only the included ones; preserve original track order).
  lines.push("");
  lines.push("  %% Track nodes");
  for (const tr of exp.tracks) {
    if (!includedTrackNames.has(tr.name)) continue;
    const id = tids.get(tr.name)!;
    const marker = statusCategory(tr) === "blocked" ? "⛔ " : "";
    const label = marker + mermaidLabel(tr.name);
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

  const tid = tids.get(t.name)!;

  // blocks edges from T's blockers → T
  for (const b of t.blockers) {
    const num = blockerIssue(b);
    if (num === null) continue; // free-text blocker — not a graph edge
    lines.push(`  i_${num} -->|blocks| ${tid}`);
    // owns edge from owning track → T
    const ownerName = issueOwner.get(num);
    if (ownerName !== undefined && ownerName !== t.name) {
      const ownerId = tids.get(ownerName)!;
      lines.push(`  ${ownerId} -->|owns #${num}| ${tid}`);
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

  // depends_on edges for T and its dependency neighbourhood (#102)
  const fDepNames = t.depends_on || [];
  for (const depName of fDepNames) {
    const depId = tids.get(depName) ?? trackId(depName);
    lines.push(`  ${tid} ==>|depends on| ${depId}`);
  }
  // Reverse: tracks that depend on T
  for (const tr of exp.tracks) {
    if ((tr.depends_on || []).includes(t.name)) {
      const depId = tids.get(tr.name)!;
      lines.push(`  ${depId} ==>|depends on| ${tid}`);
    }
  }

  // #257: issue→issue blocked-by edges, same-repo only.
  // Both the blocked issue and its blocker must already be nodes in includedIssues.
  for (const [num] of includedIssues) {
    const issue = issueIndex.get(num);
    if (issue === undefined) continue;
    for (const dep of issue.blocked_by ?? []) {
      if (dep.repo !== t.repo) continue;              // cross-repo excluded
      if (!includedIssues.has(dep.number)) continue;  // blocker must be a node too
      lines.push(`  i_${dep.number} --x|blocked by| i_${num}`);
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
      blockedIds.push(tids.get(tr.name)!);
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
 * Builds a collision-resistant Map of track name → Mermaid node id.
 *
 * Sanitised base ids are produced by replace(/[^A-Za-z0-9_]/g, "_"). If two
 * different track names would map to the same sanitised id (e.g. "my-track"
 * and "my_track"), a zero-based numeric suffix is appended to disambiguate
 * later occurrences.  The first-seen name keeps the bare id so single-track
 * graphs produce the same output as before.  Deterministic for the same input.
 */
function buildTrackIds(tracks: { name: string }[]): Map<string, string> {
  const map = new Map<string, string>();
  const used = new Set<string>();
  for (const t of tracks) {
    let base = "t_" + t.name.replace(/[^A-Za-z0-9_]/g, "_");
    let id = base;
    let suffix = 1;
    while (used.has(id)) {
      id = `${base}_${suffix++}`;
    }
    used.add(id);
    map.set(t.name, id);
  }
  return map;
}

/**
 * Derives a Mermaid-safe node id from a track name.
 * Replaces any character outside [A-Za-z0-9_] with `_` and prefixes with `t_`.
 *
 * Prefer `buildTrackIds` when processing multiple tracks — it guarantees
 * uniqueness across the set.  This function is kept for single-track callers
 * (e.g. the `selected` class fallback in `_toMermaidFull`).
 */
function trackId(name: string): string {
  return "t_" + name.replace(/[^A-Za-z0-9_]/g, "_");
}

/**
 * Escapes characters that would break Mermaid `["..."]` / `(["..."])` node labels.
 *
 * `<` / `>` / `&` are escaped to HTML entities so the browser does not
 * misinterpret them as tags or entity starts.  These entities survive the
 * browser's HTML parse (they are inside a `<pre>`), and after Mermaid's
 * own `entityDecode` they become the original characters — which are safe
 * inside Mermaid label strings.
 *
 * `"` / `[` / `]` / `` ` `` / `{` / `}` are **replaced** with safe
 * alternatives (`'` / `(` / `)`) instead of HTML entities.  Mermaid
 * 11.x's `entityDecode` passes `innerHTML` through `escape()`,
 * `innerHTML`, and `textContent`, which decodes **all** HTML entities
 * back to their raw characters.  A raw `"` followed by `]` (i.e. `"]`)
 * forms the Mermaid `SQE` token and terminates the label string
 * prematurely, causing "Syntax error in text".  Replacing with safe
 * literal characters avoids this entirely.
 *
 * Newlines (`\n` / `\r`) are collapsed to a single space: a literal line
 * break inside a `["..."]` label aborts the node statement and produces a
 * "Syntax error in text" (cosmetic DoS of the graph pane). GitHub issue
 * titles are single-line in practice, but a crafted title on a tracked
 * public repo could embed one — so neutralise it defensively (#197).
 */
function mermaidLabel(s: string): string {
  return s
    .replace(/[\r\n]+/g, " ")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "'")
    .replace(/\[/g, "(")
    .replace(/\]/g, ")")
    .replace(/\{/g, "(")
    .replace(/\}/g, ")")
    .replace(/`/g, "'");
}

/** Exposed for the hostile-title corpus test (#197). Not used in production. */
export const __mermaidLabelForTest = mermaidLabel;
