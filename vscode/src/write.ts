import type { CliRunner } from "./cli.ts";
import { runWrite } from "./cli.ts";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/** A write action the viewer can request. Pure data — no vscode. */
export type WriteAction =
  | { kind: "editFields"; track: string; fields: Record<string, string> }
  | { kind: "setNext"; track: string; issues: number[] }
  | { kind: "refresh"; track: string }
  | { kind: "reconcileDraft"; track: string }
  | { kind: "hygiene" }
  | { kind: "slot"; track: string; issue: number }
  | { kind: "close"; track: string; state: "shipped" | "parked" | "abandoned"; note?: string }
  | { kind: "newTrack"; repo: string; slug: string; priority?: string; milestone?: string }
  | { kind: "addRepo"; key: string; github: string; local?: string }
  | { kind: "setNotesRoot"; path: string };

/** The user's decision from the public-repo confirm modal. */
export type ConfirmDecision = "writeAnyway" | "cancel";

/** Injected by the caller — in production it shows a vscode modal; in tests it's a fake. */
export type ConfirmPrompt = (reason: string) => Promise<ConfirmDecision>;

/** Result of executeWrite. */
export type WriteOutcome =
  | { status: "written"; stdout: string }
  | { status: "cancelled" };

// ---------------------------------------------------------------------------
// actionToArgs
// ---------------------------------------------------------------------------

/**
 * Maps a WriteAction to work-plan CLI argv. Does NOT include --confirm.
 *
 * Mappings:
 *   editFields      → ["set", track, ...entries.map(k=v)]
 *   setNext         → ["handoff", track, "--set-next=<csv>"]   (equals form)
 *   refresh         → ["refresh-md", track, "--yes"]
 *   reconcileDraft  → ["reconcile", track, "--draft"]
 *   hygiene         → ["hygiene", "--yes"]
 *   slot            → ["slot", issue, track, "--no-move"]
 *   close           → ["close", track, "--state=<state>", ..."--note=<text>"]
 *   newTrack        → ["new-track", repo, slug, ..."--priority=<p>", ..."--milestone=<m>"]
 *   addRepo         → ["init-repo", key, "--github=<org/repo>", ..."--local=<path>"]
 *   setNotesRoot    → ["set-notes-root", path]
 */
export function actionToArgs(action: WriteAction): string[] {
  switch (action.kind) {
    case "editFields":
      return [
        "set",
        action.track,
        ...Object.entries(action.fields).map(([k, v]) => `${k}=${v}`),
      ];

    case "setNext":
      return [
        "handoff",
        action.track,
        `--set-next=${action.issues.join(",")}`,
      ];

    case "refresh":
      return ["refresh-md", action.track, "--yes"];

    case "reconcileDraft":
      return ["reconcile", action.track, "--draft"];

    case "hygiene":
      return ["hygiene", "--yes"];

    case "slot":
      return ["slot", String(action.issue), action.track, "--no-move"];

    case "close":
      return [
        "close",
        action.track,
        `--state=${action.state}`,
        ...(action.note ? [`--note=${action.note}`] : []),
      ];

    case "newTrack":
      return [
        "new-track",
        action.repo,
        action.slug,
        ...(action.priority ? [`--priority=${action.priority}`] : []),
        ...(action.milestone ? [`--milestone=${action.milestone}`] : []),
      ];

    case "addRepo":
      return [
        "init-repo",
        action.key,
        `--github=${action.github}`,
        ...(action.local ? [`--local=${action.local}`] : []),
      ];

    case "setNotesRoot":
      return ["set-notes-root", action.path];
  }
}

// ---------------------------------------------------------------------------
// executeWrite
// ---------------------------------------------------------------------------

/**
 * Runs a write action through the confirm-token flow:
 *
 * 1. runWrite(run, actionToArgs(action))
 * 2. If result.json?.needs_confirm === true → call confirm(reason)
 *    - "writeAnyway" → re-invoke with the SAME args + `--confirm=<token>` (equals
 *                       form), return { status: "written", stdout }
 *    - "cancel"      → return { status: "cancelled" } WITHOUT a second invocation
 * 3. Otherwise → return { status: "written", stdout } from the first call
 *
 * CliError from runWrite is not caught here; the caller surfaces it.
 */
export async function executeWrite(
  run: CliRunner,
  action: WriteAction,
  confirm: ConfirmPrompt,
): Promise<WriteOutcome> {
  const args = actionToArgs(action);
  const result = await runWrite(run, args);

  // Defensively check for the confirm-token gate.
  if (
    result.json !== null &&
    typeof result.json === "object" &&
    result.json.needs_confirm === true
  ) {
    const blob = result.json as Record<string, unknown>;
    const reason = String(blob.reason ?? "This write targets a public repo.");
    const token = String(blob.token ?? "");

    const decision = await confirm(reason);

    if (decision !== "writeAnyway") {
      return { status: "cancelled" };
    }

    // Re-invoke with the equals-form confirm token appended.
    const confirmedResult = await runWrite(run, [...args, `--confirm=${token}`]);
    return { status: "written", stdout: confirmedResult.stdout };
  }

  return { status: "written", stdout: result.stdout };
}
