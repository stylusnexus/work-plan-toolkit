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
  | { kind: "hygiene" };

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
    const reason = String(
      (result.json as Record<string, unknown>).reason ?? "This write targets a public repo."
    );
    const token = String(
      (result.json as Record<string, unknown>).token ?? ""
    );

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
