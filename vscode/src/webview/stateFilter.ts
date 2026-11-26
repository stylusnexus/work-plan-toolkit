/** The shared Open / Closed issue state setting (#598). No vscode imports. */

export interface IssueStates { open: boolean; closed: boolean }

export const DEFAULT_ISSUE_STATES: Readonly<IssueStates> = { open: true, closed: false };

/** An issue whose state the export does not carry is always shown. */
export function isStateShown(state: "open" | "closed" | undefined, s: IssueStates): boolean {
  return state === undefined || s[state];
}
