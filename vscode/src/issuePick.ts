/**
 * Pure helpers for building issue QuickPick items (#212).
 *
 * vscode-free so it's unit-testable without a mock. The call sites in
 * extension.ts feed the result straight to `vscode.window.showQuickPick` —
 * `IssuePickItem` is structurally a `vscode.QuickPickItem` (label + optional
 * description) plus the issue number, so it's assignable without importing
 * vscode here.
 */
import type { Issue } from "./model.ts";

/** A QuickPick row for one issue. `issueNumber` carries the pick back to the
 *  handler; label/description are what VS Code renders + filters on. */
export interface IssuePickItem {
  label: string;
  description?: string;
  issueNumber: number;
}

/**
 * Build QuickPick items for a track's issues, in pick-list order.
 *
 * Order: open issues first, then (if included) closed, each group ascending by
 * number — matches how a GitHub issue list scans. Label is `#<n>  <title>`
 * (two spaces read as a column; the `#<n>` makes the number type-to-filter).
 * State + milestone go in the description so `matchOnDescription` can filter on
 * them and they render dimmed — never in the label, which is the identity.
 *
 * @param opts.includeClosed  Move shows closed (the "closed in the wrong track"
 *   correction); Set-Next omits them (next-up is forward-looking). Default true.
 */
export function buildIssuePickItems(
  issues: Issue[],
  opts: { includeClosed?: boolean } = {},
): IssuePickItem[] {
  const includeClosed = opts.includeClosed ?? true;
  const considered = includeClosed
    ? issues
    : issues.filter((i) => i.state !== "closed");

  const sorted = [...considered].sort((a, b) => {
    // Open before closed, then ascending by number within each group.
    const aClosed = a.state === "closed" ? 1 : 0;
    const bClosed = b.state === "closed" ? 1 : 0;
    if (aClosed !== bClosed) return aClosed - bClosed;
    return a.number - b.number;
  });

  return sorted.map((i) => ({
    label: `#${i.number}  ${i.title}`,
    description: issueDescription(i),
    issueNumber: i.number,
  }));
}

/** "open", "closed · v0.6", "open · @eve", etc. — the dimmed metadata line. */
function issueDescription(i: Issue): string {
  const bits: string[] = [i.state];
  if (i.milestone) bits.push(i.milestone);
  return bits.join(" · ");
}
