/**
 * Pure Mermaid graph derivation from a work-plan Export.
 *
 * No vscode imports. No Date / Math.random — output is fully deterministic.
 */

import type { Export, Track, Issue, TrackKey, IssueKey } from "../model.ts";
import {
  blockerIssue,
  issueKey,
  isTrackKey,
  resolveTrack,
  trackKey,
  trackKeyFromParts,
  trackRepoQualifier,
} from "../model.ts";
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
 * @param selectedTrack - Optional canonical track key (or unique legacy name) to highlight.
 * @param opts          - Optional options; opts.focus scopes the graph to the selected track.
 * @returns             Mermaid graph definition string (deterministic).
 */
export function toMermaid(
  exp: Export,
  selectedTrack?: TrackKey | string,
  opts?: ToMermaidOptions,
): string {
  // Focus mode: render only the selected track's neighbourhood, but only when
  // focus is requested AND the keyed/uniquely-named track exists. Otherwise
  // fall back to the full graph.
  const dark = opts?.dark ?? true;
  const selectedTrackObj = selectedTrack === undefined
    ? undefined
    : resolveTrack(exp.tracks, selectedTrack);
  if (opts?.focus === true && selectedTrackObj !== undefined) {
    return _toMermaidFocused(exp, selectedTrackObj, dark);
  }

  // Preserve the old unknown-name fallback, but do not let an ambiguous legacy
  // name select whichever duplicate happened to receive the bare Mermaid id.
  const unknownSelection = selectedTrack !== undefined
    && selectedTrackObj === undefined
    && !isTrackKey(selectedTrack)
    && !exp.tracks.some(track => track.name === selectedTrack)
    ? selectedTrack
    : undefined;
  return _toMermaidFull(
    exp,
    selectedTrackObj === undefined ? undefined : trackKey(selectedTrackObj),
    unknownSelection,
    dark,
  );
}

// ---------------------------------------------------------------------------
// Full graph (existing behaviour, refactored into a private function)
// ---------------------------------------------------------------------------

function _toMermaidFull(
  exp: Export,
  selectedTrack: TrackKey | undefined,
  unknownSelection: string | undefined,
  dark: boolean,
): string {
  const lines: string[] = [];

  lines.push("graph LR");

  // Class definitions (node styling only; edge styling is not supported here)
  lines.push(...classDefLines(dark));

  // Build a unique, collision-resistant track ID for each composite identity.
  const tids = buildTrackIds(exp.tracks);
  const missingTids = buildMissingTrackIds(exp.tracks, tids);

  // Build issue metadata indexes from all tracks' issues[].
  const titleIndex = new Map<IssueKey, string>();
  const issueOwner = new Map<IssueKey, TrackKey>();
  for (const track of exp.tracks) {
    const ownerKey = trackKey(track);
    for (const issue of track.issues) {
      const key = issueKey(issueScope(track), issue.number);
      if (!titleIndex.has(key)) {
        titleIndex.set(key, issue.title);
      }
      if (!issueOwner.has(key)) {
        issueOwner.set(key, ownerKey);
      }
    }
  }

  // Collect repo-qualified issues referenced as blocker or next_up, preserving
  // insertion order so Mermaid ids remain deterministic.
  const referencedIssues = new Map<IssueKey, IssueRef>();
  for (const track of exp.tracks) {
    for (const b of track.blockers) {
      // Free-text blockers aren't issue nodes — skip them (a raw `i_${b}` of a
      // prose blocker is the Mermaid "Syntax error in text" bomb).
      const num = blockerIssue(b);
      if (num !== null) addIssueRef(referencedIssues, issueScope(track), num);
    }
    for (const n of track.next_up) {
      addIssueRef(referencedIssues, issueScope(track), n);
    }
  }
  const iids = buildIssueIds(referencedIssues.values());

  // Emit track nodes
  lines.push("");
  lines.push("  %% Track nodes");
  for (const track of exp.tracks) {
    const id = tids.get(trackKey(track))!;
    // Mark blocked nodes with a non-colour glyph too — the classDef fill alone
    // signals blocked by colour, which colourblind users can't read (#244).
    const marker = statusCategory(track) === "blocked" ? "⛔ " : "";
    const label = marker + mermaidLabel(track.name);
    lines.push(`  ${id}["${label}"]`);
  }

  // Emit issue nodes (only those referenced in blockers/next_up)
  lines.push("");
  lines.push("  %% Issue nodes");
  for (const [key, ref] of referencedIssues) {
    const { number: num } = ref;
    const id = iids.get(key)!;
    const title = titleIndex.get(key);
    const label = title !== undefined ? `#${num} ${mermaidLabel(title)}` : `#${num}`;
    lines.push(`  ${id}(["${label}"])`);
  }

  // Emit edges (per track, in track order)
  lines.push("");
  lines.push("  %% Edges");

  for (const track of exp.tracks) {
    const currentTrackKey = trackKey(track);
    const tid = tids.get(currentTrackKey)!;

    // blocks edges: i_<b> -->|blocks| t_<track>
    for (const b of track.blockers) {
      const num = blockerIssue(b);
      if (num === null) continue; // free-text blocker — not a graph edge
      const key = issueKey(issueScope(track), num);
      lines.push(`  ${iids.get(key)!} -->|blocks| ${tid}`);

      // owns (cross-track): if issue b is owned by another track O, emit
      //   t_<O> -->|owns #<b>| t_<track>
      const ownerKey = issueOwner.get(key);
      if (ownerKey !== undefined && ownerKey !== currentTrackKey) {
        const ownerId = tids.get(ownerKey)!;
        lines.push(`  ${ownerId} -->|owns #${num}| ${tid}`);
      }
    }

    // next_up flow edges
    if (track.next_up.length > 0) {
      const [first, ...rest] = track.next_up;
      lines.push(`  ${tid} -->|next_up| ${iids.get(issueKey(issueScope(track), first))!}`);
      let prev = first;
      for (const n of rest) {
        if (n !== prev) {
          const prevId = iids.get(issueKey(issueScope(track), prev))!;
          const nextId = iids.get(issueKey(issueScope(track), n))!;
          lines.push(`  ${prevId} -.->|then| ${nextId}`);
        }
        prev = n;
      }
    }

    // depends_on edges (explicit cross-track dependencies, #102)
    const depNames = track.depends_on || [];
    for (const depName of depNames) {
      const repoQualifier = trackRepoQualifier(track);
      const depKey = trackKeyFromParts(repoQualifier, depName);
      const depId = tids.get(depKey) ?? missingTids.get(depKey)!;
      lines.push(`  ${tid} ==>|depends on| ${depId}`);
    }
  }

  // Class assignments
  lines.push("");
  lines.push("  %% Class assignments");

  const blockedIds: string[] = [];
  for (const track of exp.tracks) {
    if (statusCategory(track) === "blocked") {
      blockedIds.push(tids.get(trackKey(track))!);
    }
  }
  if (blockedIds.length > 0) {
    lines.push(`  class ${blockedIds.join(",")} blocked`);
  }

  if (selectedTrack !== undefined) {
    const selId = tids.get(selectedTrack)!;
    lines.push(`  class ${selId} selected`);
  } else if (unknownSelection !== undefined) {
    lines.push(`  class ${trackId(unknownSelection)} selected`);
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

  // Build a unique, collision-resistant track ID for each composite identity.
  const tids = buildTrackIds(exp.tracks);
  const missingTids = buildMissingTrackIds(exp.tracks, tids);

  // Build title index from all tracks (titles may live on any track).
  const titleIndex = new Map<IssueKey, string>();
  // Build issue object index (first-match wins, same traversal order as titleIndex).
  const issueIndex = new Map<IssueKey, Issue>();
  // issueOwner: repo-qualified issue → composite track identity (first match).
  const issueOwner = new Map<IssueKey, TrackKey>();
  for (const tr of exp.tracks) {
    const ownerKey = trackKey(tr);
    for (const issue of tr.issues) {
      const key = issueKey(issueScope(tr), issue.number);
      if (!titleIndex.has(key)) {
        titleIndex.set(key, issue.title);
      }
      if (!issueIndex.has(key)) {
        issueIndex.set(key, issue);
      }
      if (!issueOwner.has(key)) {
        issueOwner.set(key, ownerKey);
      }
    }
  }

  // Determine which track nodes to include:
  //   - always: the selected track itself.
  //   - for each blocker b of T: the owner track of b (if b is owned by another track).
  //   - tracks that T explicitly depends_on, and tracks that depend_on T (#102).
  const selectedTrackKey = trackKey(t);
  const repoQualifier = trackRepoQualifier(t);
  const includedTrackKeys = new Set<TrackKey>([selectedTrackKey]);
  for (const b of t.blockers) {
    const num = blockerIssue(b);
    if (num === null) continue; // free-text blocker owns no track
    const ownerKey = issueOwner.get(issueKey(issueScope(t), num));
    if (ownerKey !== undefined && ownerKey !== selectedTrackKey) {
      includedTrackKeys.add(ownerKey);
    }
  }
  // Add dependency neighbourhood (#102)
  const depNames = t.depends_on || [];
  for (const depName of depNames) {
    const depKey = trackKeyFromParts(repoQualifier, depName);
    if (tids.has(depKey)) includedTrackKeys.add(depKey);
  }
  // Reverse: add tracks that depend on T
  for (const tr of exp.tracks) {
    if (trackRepoQualifier(tr) !== repoQualifier) continue;
    if ((tr.depends_on || []).some(
      depName => trackKeyFromParts(repoQualifier, depName) === selectedTrackKey,
    )) {
      includedTrackKeys.add(trackKey(tr));
    }
  }

  // Determine which issue nodes to include:
  //   - T's blockers and T's next_up (in that order, deduped, preserving insertion order).
  const includedIssues = new Map<IssueKey, IssueRef>();
  for (const b of t.blockers) {
    const num = blockerIssue(b);
    if (num !== null) addIssueRef(includedIssues, issueScope(t), num);
  }
  for (const n of t.next_up) {
    addIssueRef(includedIssues, issueScope(t), n);
  }
  const iids = buildIssueIds(includedIssues.values());

  // Emit track nodes (only the included ones; preserve original track order).
  lines.push("");
  lines.push("  %% Track nodes");
  for (const tr of exp.tracks) {
    const key = trackKey(tr);
    if (!includedTrackKeys.has(key)) continue;
    const id = tids.get(key)!;
    const marker = statusCategory(tr) === "blocked" ? "⛔ " : "";
    const label = marker + mermaidLabel(tr.name);
    lines.push(`  ${id}["${label}"]`);
  }

  // Emit issue nodes.
  lines.push("");
  lines.push("  %% Issue nodes");
  for (const [key, ref] of includedIssues) {
    const { number: num } = ref;
    const id = iids.get(key)!;
    const title = titleIndex.get(key);
    const label = title !== undefined ? `#${num} ${mermaidLabel(title)}` : `#${num}`;
    lines.push(`  ${id}(["${label}"])`);
  }

  // Emit edges (only those relevant to T).
  lines.push("");
  lines.push("  %% Edges");

  const tid = tids.get(selectedTrackKey)!;

  // blocks edges from T's blockers → T
  for (const b of t.blockers) {
    const num = blockerIssue(b);
    if (num === null) continue; // free-text blocker — not a graph edge
    const key = issueKey(issueScope(t), num);
    lines.push(`  ${iids.get(key)!} -->|blocks| ${tid}`);
    // owns edge from owning track → T
    const ownerKey = issueOwner.get(key);
    if (ownerKey !== undefined && ownerKey !== selectedTrackKey) {
      const ownerId = tids.get(ownerKey)!;
      lines.push(`  ${ownerId} -->|owns #${num}| ${tid}`);
    }
  }

  // next_up flow edges for T
  if (t.next_up.length > 0) {
    const [first, ...rest] = t.next_up;
    lines.push(`  ${tid} -->|next_up| ${iids.get(issueKey(issueScope(t), first))!}`);
    let prev = first;
    for (const n of rest) {
      if (n !== prev) {
        const prevId = iids.get(issueKey(issueScope(t), prev))!;
        const nextId = iids.get(issueKey(issueScope(t), n))!;
        lines.push(`  ${prevId} -.->|then| ${nextId}`);
      }
      prev = n;
    }
  }

  // depends_on edges for T and its dependency neighbourhood (#102)
  const fDepNames = t.depends_on || [];
  for (const depName of fDepNames) {
    const depKey = trackKeyFromParts(repoQualifier, depName);
    const depId = tids.get(depKey) ?? missingTids.get(depKey)!;
    lines.push(`  ${tid} ==>|depends on| ${depId}`);
  }
  // Reverse: tracks that depend on T
  for (const tr of exp.tracks) {
    if (trackRepoQualifier(tr) !== repoQualifier) continue;
    if ((tr.depends_on || []).some(
      depName => trackKeyFromParts(repoQualifier, depName) === selectedTrackKey,
    )) {
      const depId = tids.get(trackKey(tr))!;
      lines.push(`  ${depId} ==>|depends on| ${tid}`);
    }
  }

  // #257: issue→issue blocked-by edges, same-repo only.
  // Both the blocked issue and its blocker must already be nodes in includedIssues.
  for (const [key] of includedIssues) {
    const issue = issueIndex.get(key);
    if (issue === undefined) continue;
    for (const dep of issue.blocked_by ?? []) {
      if (dep.repo !== t.repo) continue;              // cross-repo excluded
      const depKey = issueKey(dep.repo, dep.number);
      if (!includedIssues.has(depKey)) continue;      // blocker must be a node too
      lines.push(`  ${iids.get(depKey)!} --x|blocked by| ${iids.get(key)!}`);
    }
  }

  // Class assignments
  lines.push("");
  lines.push("  %% Class assignments");

  // blocked class — only for included tracks
  const blockedIds: string[] = [];
  for (const tr of exp.tracks) {
    const key = trackKey(tr);
    if (!includedTrackKeys.has(key)) continue;
    if (statusCategory(tr) === "blocked") {
      blockedIds.push(tids.get(key)!);
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
 * Builds a collision-resistant Map of composite track key → Mermaid node id.
 *
 * Sanitised base ids are produced by replace(/[^A-Za-z0-9_]/g, "_"). If two
 * different identities would map to the same sanitised id (e.g. "my-track"
 * and "my_track", or same-named tracks in different repos), a numeric suffix
 * is appended to disambiguate later occurrences. The first-seen identity keeps
 * the bare id so non-colliding graphs produce the same output as before.
 */
function buildTrackIds(tracks: readonly Track[]): Map<TrackKey, string> {
  const map = new Map<TrackKey, string>();
  const allocator = createIdAllocator();
  for (const t of tracks) {
    map.set(trackKey(t), claimNodeId(trackId(t.name), allocator));
  }
  return map;
}

interface IssueRef {
  key: IssueKey;
  repo: string;
  number: number;
}

/** Add a repo-qualified issue reference without disturbing first-seen order. */
function addIssueRef(
  refs: Map<IssueKey, IssueRef>,
  repo: string,
  number: number,
): void {
  const key = issueKey(repo, number);
  if (!refs.has(key)) refs.set(key, { key, repo, number });
}

/**
 * Assign short issue node ids while keeping same-number issues in different
 * repos distinct. The first occurrence retains the legacy `i_<number>` id.
 */
function buildIssueIds(refs: Iterable<IssueRef>): Map<IssueKey, string> {
  const map = new Map<IssueKey, string>();
  const allocator = createIdAllocator();
  for (const ref of refs) {
    map.set(ref.key, claimNodeId(`i_${ref.number}`, allocator));
  }
  return map;
}

interface IdAllocator {
  used: Set<string>;
  nextSuffix: Map<string, number>;
}

function createIdAllocator(initial: Iterable<string> = []): IdAllocator {
  return { used: new Set(initial), nextSuffix: new Map() };
}

/** Claims a deterministic ID without rescanning suffixes already tried for a base. */
function claimNodeId(base: string, allocator: IdAllocator): string {
  let suffix = allocator.nextSuffix.get(base) ?? 0;
  let id = suffix === 0 ? base : `${base}_${suffix}`;
  while (allocator.used.has(id)) {
    suffix += 1;
    id = `${base}_${suffix}`;
  }
  allocator.used.add(id);
  allocator.nextSuffix.set(base, suffix + 1);
  return id;
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
 * Repo-scoped id for an unresolved dependency. Encoding Unicode code points is
 * verbose but injective and deterministic, avoiding aliases with real tracks
 * from another repo or with differently-punctuated missing dependency names.
 */
function missingTrackIdBase(repoQualifier: string, name: string): string {
  const encode = (value: string): string => Array.from(value)
    .map(char => char.codePointAt(0)!.toString(16))
    .join("_");
  return `t_missing_${encode(repoQualifier)}__${encode(name)}`;
}

/**
 * Allocates unresolved-dependency IDs in the same namespace as real tracks, so
 * a crafted real track name cannot make a missing edge point at that track.
 */
function buildMissingTrackIds(
  tracks: readonly Track[],
  trackIds: ReadonlyMap<TrackKey, string>,
): Map<TrackKey, string> {
  const map = new Map<TrackKey, string>();
  const allocator = createIdAllocator(trackIds.values());
  for (const track of tracks) {
    const qualifier = trackRepoQualifier(track);
    for (const depName of track.depends_on ?? []) {
      const key = trackKeyFromParts(qualifier, depName);
      if (trackIds.has(key) || map.has(key)) continue;
      map.set(key, claimNodeId(missingTrackIdBase(qualifier, depName), allocator));
    }
  }
  return map;
}

/** Repo scope for issue identity; folder is the stable fallback for repo-less tracks. */
function issueScope(track: Pick<Track, "repo" | "folder">): string {
  return track.repo ?? trackRepoQualifier(track);
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
