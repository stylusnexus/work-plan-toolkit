/**
 * Pure keyword search over work-plan export issues (#272).
 *
 * Supports a tiny SQL-LIKE-style wildcard grammar with `%` as the only
 * wildcard, meaningful only as a leading and/or trailing anchor:
 *
 *   %term%  → contains   (substring match, anywhere)
 *   term%   → starts-with
 *   %term   → ends-with
 *   term    → contains    (bare term defaults to substring)
 *
 * Matching is case-insensitive. Regex metacharacters in the query are treated
 * literally. No vscode imports — safe to unit-test without a VS Code host.
 */

import type { Export, Issue } from "../model.ts";

/** Issue fields a search can target. "title" and (#429) "labels" are populated;
 *  "body" is reserved — the type is shaped so adding it later is additive. */
export type SearchField = "title" | "body" | "labels";

/** A single issue that matched a search, with its owning track (null = untracked). */
export interface SearchHit {
  number: number;
  title: string;
  state: "open" | "closed";
  assignee: string;
  milestone: string | null;
  repo: string;
  /** Owning track slug, or null when the issue is in the untracked bucket. */
  track: string | null;
  /** Reserved for a future body search. */
  body?: string;
  /** The issue's labels, when the export carries them (#429). */
  labels?: string[];
}

/** Prefix that scopes a query to labels: `label:security`, `label:priority/%`. */
const LABEL_PREFIX = /^\s*label:/i;

/**
 * Splits a raw query into the fields it targets and the wildcard pattern.
 * Only an explicit `label:` prefix searches labels; every bare query stays a
 * title search, exactly as before (#429). Everything after the prefix is the
 * pattern, so a label containing spaces (`label:good first issue`) works.
 */
export function parseSearchQuery(query: string): { fields: SearchField[]; pattern: string } {
  const m = LABEL_PREFIX.exec(query);
  return m === null
    ? { fields: ["title"], pattern: query }
    : { fields: ["labels"], pattern: query.slice(m[0].length) };
}

/** True when the query is an explicit label search. */
export function isLabelQuery(query: string): boolean {
  return LABEL_PREFIX.test(query);
}

/** True when at least one issue in the export carries label data (a CLI that
 *  predates #429 emits none, which must not be confused with "no labels"). */
export function exportCarriesLabels(exp: Export): boolean {
  const has = (i: Issue): boolean => Array.isArray(i.labels);
  return exp.tracks.some(t => t.issues.some(has)) ||
    (exp.untracked ?? []).some(g => g.issues.some(has));
}

/**
 * Compiles a wildcard query into a case-insensitive RegExp.
 *
 * Returns null when there is nothing to match on — an empty/whitespace query,
 * or a query consisting only of `%` wildcards (`%`, `%%`). Callers treat null
 * as "no search to run".
 *
 * Only leading/trailing `%` are treated as anchors; any other `%` (interior or
 * the anchors themselves once stripped) is matched literally.
 */
export function wildcardToRegExp(query: string): RegExp | null {
  const trimmed = query.trim();
  if (trimmed === "") return null;

  // A query that is only `%` characters has no literal core → nothing to match.
  if (/^%+$/.test(trimmed)) return null;

  const hasLeadingWildcard = trimmed.startsWith("%"); // %term → drop the left anchor (ends-with)
  const hasTrailingWildcard = trimmed.endsWith("%"); // term% → drop the right anchor (starts-with)

  // Strip a single leading and/or trailing `%`; the remainder is matched literally.
  let core = trimmed;
  if (hasLeadingWildcard) core = core.slice(1);
  if (hasTrailingWildcard) core = core.slice(0, -1);

  const literal = escapeRegExp(core);

  // Anchor a side only when the OTHER side carries a wildcard:
  //   term%  → ^term   (starts-with)   %term → term$   (ends-with)
  //   %term% → term    (contains)      term  → term    (contains, bare = contains)
  // A bare term (no wildcards) and a both-sides-wildcard term are both "contains".
  const prefix = !hasLeadingWildcard && hasTrailingWildcard ? "^" : "";
  const suffix = !hasTrailingWildcard && hasLeadingWildcard ? "$" : "";

  return new RegExp(`${prefix}${literal}${suffix}`, "i");
}

/** Escapes regex metacharacters so a query is matched as a literal string. */
function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Returns every issue whose searched fields match the query, across all tracks
 * and the untracked bucket. Results preserve discovery order (tracks then
 * issues, then untracked). Returns [] for a null/empty match (see
 * wildcardToRegExp).
 *
 * With no explicit `fields`, the query decides: a `label:` prefix searches
 * labels (case-insensitive, same `%` wildcards, any one label may match), and
 * anything else searches titles (#429). Passing `fields` overrides that and
 * matches the whole query unchanged.
 */
export function searchIssues(
  exp: Export,
  query: string,
  fields?: SearchField[],
): SearchHit[] {
  const parsed = fields === undefined ? parseSearchQuery(query) : { fields, pattern: query };
  const re = wildcardToRegExp(parsed.pattern);
  if (!re) return [];

  const matches = (issue: Issue): boolean =>
    parsed.fields.some(f =>
      (f === "title" && re.test(issue.title)) ||
      (f === "labels" && (issue.labels ?? []).some(l => re.test(l))),
    );

  const hits: SearchHit[] = [];

  const push = (issue: Issue, repo: string, track: string | null): void => {
    if (matches(issue)) {
      hits.push({
        number: issue.number,
        title: issue.title,
        state: issue.state,
        assignee: issue.assignee,
        milestone: issue.milestone,
        repo,
        track,
        ...(issue.labels !== undefined && { labels: issue.labels }),
      });
    }
  };

  for (const t of exp.tracks) {
    for (const issue of t.issues) {
      push(issue, t.repo ?? t.folder ?? "(no repo)", t.name);
    }
  }
  for (const group of exp.untracked ?? []) {
    for (const issue of group.issues) {
      push(issue, group.repo, null);
    }
  }

  return hits;
}
