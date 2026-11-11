/**
 * Pure helpers for "Sync Shared Plan" (#426): the CLI args, parsing the
 * `plan-branch sync --json` output, and the message to show. No vscode imports.
 */

/** States `plan-branch sync --json` can report. Unknown values read as "error". */
export type SyncState =
  | "up-to-date" | "ahead" | "fast-forwarded" | "would-fast-forward" | "unpublished"
  | "diverged" | "dirty" | "offline" | "missing" | "no-worktree" | "error" | "unconfigured";

export interface SyncResult {
  state: SyncState;
  behind: number;
  incoming: string[];
  moved: boolean;
  message: string;
}

const STATES: readonly string[] = [
  "up-to-date", "ahead", "fast-forwarded", "would-fast-forward", "unpublished",
  "diverged", "dirty", "offline", "missing", "no-worktree", "error", "unconfigured",
];

export const syncArgs = (repoKey: string): string[] => ["plan-branch", "sync", repoKey, "--json"];

/**
 * Parse the CLI's stdout. Null when it is not a sync result: an older CLI has
 * no `sync` action and prints a usage line, which the caller reports as such.
 */
export function parseSyncResult(stdout: string): SyncResult | null {
  let raw: unknown;
  try { raw = JSON.parse(stdout); } catch { return null; }
  if (typeof raw !== "object" || raw === null) return null;
  const o = raw as Record<string, unknown>;
  if (typeof o["state"] !== "string") return null;
  return {
    state: (STATES.includes(o["state"]) ? o["state"] : "error") as SyncState,
    behind: typeof o["behind"] === "number" ? o["behind"] : 0,
    incoming: Array.isArray(o["incoming"]) ? o["incoming"].filter((x): x is string => typeof x === "string") : [],
    moved: o["moved"] === true,
    message: typeof o["message"] === "string" ? o["message"] : "",
  };
}

export interface SyncToast { level: "info" | "warning" | "error"; text: string }

/** What to tell the user. Refusals carry the CLI's remediation text verbatim. */
export function syncToast(r: SyncResult | null, repo: string): SyncToast {
  if (r === null) {
    return {
      level: "error",
      text: "Work Plan: Sync Shared Plan needs a newer work-plan CLI. Update it and try again.",
    };
  }
  const n = r.incoming.length;
  switch (r.state) {
    case "fast-forwarded":
      return { level: "info", text: `Work Plan: synced ${repo} — ${n} new plan commit${n === 1 ? "" : "s"} from your team.` };
    case "up-to-date":
      return { level: "info", text: `Work Plan: ${repo}'s shared plan is already up to date.` };
    case "ahead":
      return { level: "info", text: `Work Plan: nothing to pull for ${repo}; you have plan commits that are not pushed yet.` };
    case "unpublished":
      return { level: "info", text: `Work Plan: ${repo}'s plan branch is not on origin yet, so there is nothing to sync.` };
    case "would-fast-forward":
      return { level: "info", text: `Work Plan: ${repo} is ${n} commit${n === 1 ? "" : "s"} behind origin.` };
    case "offline":
      return { level: "warning", text: `Work Plan: ${r.message || "could not reach origin."} Nothing changed.` };
    case "diverged":
    case "dirty":
      return { level: "warning", text: `Work Plan: ${r.message}` };
    default:
      return { level: "error", text: `Work Plan: sync failed for ${repo}. ${r.message}`.trim() };
  }
}
