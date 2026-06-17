import * as fs from "node:fs";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * One accepted suggestion entry, derived from a v2 answers file (#241). The
 * answers file is written by a Claude session (NOT the extension) after the user
 * runs Suggest Tracks; this model reads it back, validates it, and buckets it.
 */
export interface SuggestionEntry {
  issueNumber: number;
  suggestedTrack: string;
  /** The model's second-choice track, if it offered one. */
  runnerUp?: string;
  /** 0–1; surfaced in the tooltip, never as the leading label (per the UX spec). */
  confidence: number;
  /** "clear" → one-click accept eligible; "narrow" → forced into Needs review. */
  margin: "clear" | "narrow";
  rationale: string;
}

/**
 * The split result: `suggested` are one-click-accept eligible (verdict "suggest",
 * margin "clear", confidence ≥ threshold); `needsReview` are lower-confidence or
 * narrow-margin suggestions that need a human eye before slotting. Abstains and
 * dismissed issues never appear in either bucket. `batchMismatch` is true when the
 * answers file's batch_id didn't match the current scan — the caller may warn and
 * both buckets are empty.
 */
export interface SuggestionBuckets {
  suggested: SuggestionEntry[];
  needsReview: SuggestionEntry[];
  batchMismatch: boolean;
}

const EMPTY: SuggestionBuckets = { suggested: [], needsReview: [], batchMismatch: false };

// ---------------------------------------------------------------------------
// Parsing + bucketing
// ---------------------------------------------------------------------------

/**
 * Reads a v2 answers file from `path`, validates it against `expectedBatchId`,
 * and splits its non-abstain, non-dismissed suggestions into the suggested /
 * needs-review buckets.
 *
 * Tolerant by design: a missing file, an unreadable file, or unparseable JSON
 * all return EMPTY (no throw) — the answers file is written asynchronously by a
 * separate Claude session, so "not there yet" is the normal cold state, not an
 * error. A batch_id mismatch returns empty buckets with `batchMismatch: true` so
 * a stale answers file from a prior scan is never silently applied.
 *
 * Pure aside from the file read: `isDismissed(issueNumber)` lets the caller
 * exclude issues the user has dismissed (workspaceState), and `threshold` is the
 * suggested-vs-needsReview confidence cutoff.
 */
export function readSuggestions(
  path: string,
  expectedBatchId: string,
  threshold: number,
  isDismissed: (issueNumber: number) => boolean,
): SuggestionBuckets {
  let raw: string;
  try {
    raw = fs.readFileSync(path, "utf8");
  } catch {
    return EMPTY; // not written yet / unreadable — normal cold state
  }
  return parseSuggestions(raw, expectedBatchId, threshold, isDismissed);
}

/**
 * The pure core of `readSuggestions` — parses already-read file contents. Split
 * out so tests can exercise the parse/bucket/threshold/dismiss/batch-id logic
 * without touching the filesystem.
 */
export function parseSuggestions(
  contents: string,
  expectedBatchId: string,
  threshold: number,
  isDismissed: (issueNumber: number) => boolean,
): SuggestionBuckets {
  let blob: unknown;
  try {
    blob = JSON.parse(contents);
  } catch {
    return EMPTY;
  }
  if (blob === null || typeof blob !== "object") {
    return EMPTY;
  }
  const obj = blob as Record<string, unknown>;

  // Validate the batch_id: a stale answers file from a prior scan must never be
  // applied to the current untracked set. An answers file with no batch_id is
  // treated as a mismatch (we can't correlate it).
  if (typeof obj.batch_id !== "string" || obj.batch_id !== expectedBatchId) {
    return { suggested: [], needsReview: [], batchMismatch: true };
  }

  const rawSuggestions = Array.isArray(obj.suggestions) ? obj.suggestions : [];

  const suggested: SuggestionEntry[] = [];
  const needsReview: SuggestionEntry[] = [];

  for (const item of rawSuggestions) {
    if (item === null || typeof item !== "object") continue;
    const s = item as Record<string, unknown>;

    const issueNumber = typeof s.issue === "number" ? s.issue : NaN;
    if (!Number.isInteger(issueNumber)) continue;

    // verdict "abstain" → not shown at all (stays in plain untracked).
    const verdict = typeof s.verdict === "string" ? s.verdict : "";
    if (verdict !== "suggest") continue;

    // A suggestion with no track can't be slotted — drop it.
    const suggestedTrack = typeof s.track === "string" ? s.track : "";
    if (suggestedTrack === "") continue;

    // Dismissed issues drop back to plain untracked.
    if (isDismissed(issueNumber)) continue;

    const confidence = typeof s.confidence === "number" ? s.confidence : 0;
    const margin: "clear" | "narrow" = s.margin === "narrow" ? "narrow" : "clear";
    const runnerUp = typeof s.runner_up === "string" && s.runner_up !== "" ? s.runner_up : undefined;
    const rationale = typeof s.rationale === "string" ? s.rationale : "";

    const entry: SuggestionEntry = {
      issueNumber,
      suggestedTrack,
      ...(runnerUp ? { runnerUp } : {}),
      confidence,
      margin,
      rationale,
    };

    // THREE-tier bucketing (#241): one-click "Suggested" only when the model is
    // confident (clear margin) AND meets the threshold; everything else
    // (narrow margin, or below-threshold confidence) goes to "Needs review",
    // which has NO one-click accept.
    if (margin === "clear" && confidence >= threshold) {
      suggested.push(entry);
    } else {
      needsReview.push(entry);
    }
  }

  return { suggested, needsReview, batchMismatch: false };
}
