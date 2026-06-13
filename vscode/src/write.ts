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
  | { kind: "batchSlot"; track: string; issues: number[] }
  | { kind: "close"; track: string; state: "shipped" | "parked" | "abandoned"; note?: string }
  | { kind: "newTrack"; repo: string; slug: string; priority?: string; milestone?: string }
  | { kind: "renameTrack"; track: string; newSlug: string }
  | { kind: "addRepo"; key: string; github: string; local?: string; update?: boolean; clearLocal?: boolean }
  | { kind: "removeRepo"; key: string }
  | { kind: "setNotesRoot"; path: string }
  | { kind: "move"; fromTrack: string; toTrack: string; issue: number }
  | { kind: "handoff"; track: string }
  // Plan verdict-override (#286) — frontmatter-only write to a plan/spec doc.
  // repoKey is the config folder key (the `plan-status --repo=<key>` arg); rel is
  // the repo-relative doc path. clear=true removes the override instead of setting.
  | { kind: "planConfirm"; repoKey: string; rel: string; verdict: "shipped" | "partial" | "dead" }
  | { kind: "planConfirmClear"; repoKey: string; rel: string }
  // Durable frontmatter acknowledgment (#286) — writes `acknowledged: true`
  // (clear removes it). Frontmatter-only, same shape as planConfirm.
  | { kind: "planAck"; repoKey: string; rel: string }
  | { kind: "planAckClear"; repoKey: string; rel: string }
  // Drift baseline (#286) — stamps the current computed verdict into frontmatter
  // (clear removes it). Frontmatter-only, same shape as planConfirm/planAck.
  | { kind: "planBaseline"; repoKey: string; rel: string }
  | { kind: "planBaselineClear"; repoKey: string; rel: string }
  // Close a GitHub issue (#305) — the ONLY GitHub-mutating action. `repo` is the
  // org/repo slug; gated by a mandatory UI modal in the command handler (no
  // needs_confirm token — closing doesn't leak private content to a public repo).
  | { kind: "closeIssue"; repo: string; number: number; reason: "completed" | "not_planned"; comment?: string };

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
 * Argument-injection hardening (#194): user/GitHub-derived **positional** args
 * (track names, repo keys, slugs, notes paths) are placed AFTER a `--`
 * end-of-options separator. A track named `--repo` or `--confirm=<token>` then
 * reaches the CLI as a plain positional rather than being misparsed as a flag.
 * Flags (`--set-next=`, `--state=`, `--no-move`, …) are emitted in equals/literal
 * form BEFORE the `--`. Numeric issue args are never dash-led but live after the
 * `--` too, for a single, predictable shape: [subcommand, ...flags, "--", ...positionals].
 *
 * NOTE: this depends on the CLI honouring `--` (stopping flag parsing there) —
 * shipped on a separate Python branch. Verbs with no positionals (hygiene) emit
 * no separator.
 *
 * Mappings:
 *   editFields      → ["set", ...entries.map(k=v), "--", track]
 *   setNext         → ["handoff", "--set-next=<csv>", "--", track]   (equals form)
 *   refresh         → ["refresh-md", "--yes", "--", track]
 *   reconcileDraft  → ["reconcile", "--draft", "--", track]
 *   hygiene         → ["hygiene", "--yes"]
 *   slot            → ["slot", "--no-move", "--", issue, track]
 *   batchSlot       → ["batch-slot", "--no-move", "--", ...issues, track]
 *   close           → ["close", "--state=<state>", ..."--note=<text>", "--", track]
 *   newTrack        → ["new-track", ..."--priority=<p>", ..."--milestone=<m>", "--", repo, slug]
 *   renameTrack     → ["rename-track", "--", track, newSlug]
 *   addRepo         → ["init-repo", "--github=<org/repo>", ..."--local=<path>", ..."--update", ..."--clear-local", "--", key]
 *   removeRepo      → ["remove-repo", "--", key]
 *   setNotesRoot    → ["set-notes-root", "--", path]
 *   move            → ["move", "--", issue, fromTrack, toTrack]
 *   handoff         → ["handoff", "--", track]   (derived/non-interactive mode)
 *   planConfirm     → ["plan-confirm", "--repo=<key>", "--verdict=<v>", "--", rel]
 *   planConfirmClear→ ["plan-confirm", "--repo=<key>", "--clear", "--", rel]
 *   planAck         → ["plan-ack", "--repo=<key>", "--", rel]
 *   planAckClear    → ["plan-ack", "--repo=<key>", "--clear", "--", rel]
 *   planBaseline    → ["plan-baseline", "--repo=<key>", "--", rel]
 *   planBaselineClear→ ["plan-baseline", "--repo=<key>", "--clear", "--", rel]
 *   closeIssue      → ["close-issue", "--repo=<slug>", "--reason=<r>", ..."--comment=<c>", "--", number]
 */
export function actionToArgs(action: WriteAction): string[] {
  switch (action.kind) {
    case "editFields":
      return [
        "set",
        ...Object.entries(action.fields).map(([k, v]) => `${k}=${v}`),
        "--",
        action.track,
      ];

    case "setNext":
      return [
        "handoff",
        `--set-next=${action.issues.join(",")}`,
        "--",
        action.track,
      ];

    case "refresh":
      return ["refresh-md", "--yes", "--", action.track];

    case "reconcileDraft":
      return ["reconcile", "--draft", "--", action.track];

    case "hygiene":
      return ["hygiene", "--yes"];

    case "slot":
      return ["slot", "--no-move", "--", String(action.issue), action.track];

    case "batchSlot":
      return ["batch-slot", "--no-move", "--", ...action.issues.map(String), action.track];

    case "close":
      return [
        "close",
        `--state=${action.state}`,
        ...(action.note ? [`--note=${action.note}`] : []),
        "--",
        action.track,
      ];

    case "newTrack":
      return [
        "new-track",
        ...(action.priority ? [`--priority=${action.priority}`] : []),
        ...(action.milestone ? [`--milestone=${action.milestone}`] : []),
        "--",
        action.repo,
        action.slug,
      ];

    case "renameTrack":
      return ["rename-track", "--", action.track, action.newSlug];

    case "addRepo":
      return [
        "init-repo",
        `--github=${action.github}`,
        // --clear-local and --local are mutually exclusive in the CLI; when
        // clearing, drop --local and force --update (clear is update-only).
        ...(action.clearLocal ? [] : action.local ? [`--local=${action.local}`] : []),
        ...(action.update || action.clearLocal ? ["--update"] : []),
        ...(action.clearLocal ? ["--clear-local"] : []),
        "--",
        action.key,
      ];

    case "removeRepo":
      return ["remove-repo", "--", action.key];

    case "setNotesRoot":
      return ["set-notes-root", "--", action.path];

    case "move":
      return ["move", "--", String(action.issue), action.fromTrack, action.toTrack];

    case "handoff":
      // Derived (non-interactive) handoff. The CLI's prompt helpers fall back to
      // their defaults under non-TTY stdin (#183), so this never blocks; --auto-next
      // and -i are deliberately omitted (they'd need a native picker — separate work).
      return ["handoff", "--", action.track];

    case "planConfirm":
      return [
        "plan-confirm",
        `--repo=${action.repoKey}`,
        `--verdict=${action.verdict}`,
        "--",
        action.rel,
      ];

    case "planConfirmClear":
      return ["plan-confirm", `--repo=${action.repoKey}`, "--clear", "--", action.rel];

    case "planAck":
      return ["plan-ack", `--repo=${action.repoKey}`, "--", action.rel];

    case "planAckClear":
      return ["plan-ack", `--repo=${action.repoKey}`, "--clear", "--", action.rel];

    case "planBaseline":
      return ["plan-baseline", `--repo=${action.repoKey}`, "--", action.rel];

    case "planBaselineClear":
      return ["plan-baseline", `--repo=${action.repoKey}`, "--clear", "--", action.rel];

    case "closeIssue":
      return [
        "close-issue",
        `--repo=${action.repo}`,
        `--reason=${action.reason}`,
        ...(action.comment ? [`--comment=${action.comment}`] : []),
        "--",
        String(action.number),
      ];
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
 *                       form), inserted BEFORE the `--` end-of-options separator
 *                       so a strict CLI parser treats it as a flag, not a
 *                       positional; return { status: "written", stdout }
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

    // Re-invoke with the equals-form confirm token. It MUST land before the
    // `--` separator (#194) — anything after `--` is a positional to a strict
    // parser, which would swallow the token instead of honouring it.
    const confirmedArgs = withConfirmToken(args, token);
    const confirmedResult = await runWrite(run, confirmedArgs);
    return { status: "written", stdout: confirmedResult.stdout };
  }

  return { status: "written", stdout: result.stdout };
}

/**
 * Returns a copy of `args` with `--confirm=<token>` inserted as a flag.
 * If `args` contains a `--` end-of-options separator, the flag is inserted
 * immediately before it (so it stays in the flag region); otherwise it is
 * appended (e.g. `hygiene`, which has no positionals).
 */
function withConfirmToken(args: string[], token: string): string[] {
  const flag = `--confirm=${token}`;
  const sepIdx = args.indexOf("--");
  if (sepIdx === -1) {
    return [...args, flag];
  }
  return [...args.slice(0, sepIdx), flag, ...args.slice(sepIdx)];
}
