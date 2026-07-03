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
  // Non-draft reconcile (#221) — applies the label-drift ADDs/MOVEs the draft
  // previewed. `--yes` runs it non-interactively; writes are local frontmatter
  // only (the read-only-GitHub contract holds), and the CLI self-skips MOVEs into
  // PUBLIC destination tracks. Routed through executeWrite for a uniform path.
  | { kind: "reconcileApply"; track: string }
  | { kind: "hygiene" }
  // `expect` (#241) opts into the CLI's compare-and-swap staleness guard: the
  // fingerprint of the target track's issue list as the viewer last saw it. If
  // the on-disk list changed since, the CLI aborts with {stale} and the caller
  // re-offers instead of clobbering. Omitted → today's unguarded behaviour.
  | { kind: "slot"; track: string; issue: number; expect?: string }
  | { kind: "batchSlot"; track: string; issues: number[]; expect?: string }
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
  // Archive a shipped plan doc (#387) — moves the doc into archive/shipped/.
  // Non-interactive + structured for the viewer (--yes --json). repoKey is the
  // config folder key; rel is the repo-relative doc path.
  | { kind: "planArchive"; repoKey: string; rel: string }
  | { kind: "planUnarchive"; repoKey: string; rel: string }
  // Batch-archive every clean shipped doc in a repo (#387). includeLieGap opts
  // unverified (lie-gap) shipped docs into the sweep.
  | { kind: "planArchiveAllShipped"; repoKey: string; includeLieGap?: boolean }
  // Close a GitHub issue (#305) — one of two GitHub-mutating actions (the other is
  // issueInProgress). `repo` is the org/repo slug; gated by a mandatory UI modal in
  // the command handler (no needs_confirm token — closing doesn't leak private content
  // to a public repo).
  | { kind: "closeIssue"; repo: string; number: number; reason: "completed" | "not_planned"; comment?: string }
  // Mark or clear the work-plan:in-progress label on an issue (#271) — the second
  // GitHub-mutating action (the first is closeIssue). `repo` is the org/repo slug;
  // clear=true removes the label instead of adding it.
  // Goes through the public-repo confirm-token flow (executeWrite) — no extra
  // modal needed since it only mutates the label, not the issue's state.
  | { kind: "issueInProgress"; repo: string; number: number; clear: boolean }
  // Promote a private track to the shared tier + push (#306). repoKey is the
  // config folder key (disambiguates the track). Public-repo gated by the CLI's
  // needs_confirm, which executeWrite drives.
  | { kind: "pushTrack"; track: string; repoKey?: string }
  // Set the per-track next-up ordering preset (#326 Phase 3). repoKey is the
  // config folder key (passed as --repo=<key> to the CLI). preset is omitted
  // when clear=true (which resets to the default "flow"). auto, when present,
  // toggles automatic next-up ranking (#338) — can be combined with preset or
  // used alone (no preset → no --preset/--clear flag emitted).
  | { kind: "setNextUpPreset"; track: string; repoKey?: string; preset?: string; clear?: boolean; auto?: "on" | "off" }
  // Flag a track as a cleanup candidate (#328/#329/#330) — a reversible,
  // non-destructive frontmatter flag (NOT deletion). repoKey is the config folder
  // key (passed as --repo=<key>). reason is an optional free-text note (omitted
  // entirely when blank). Public-repo gated by the CLI's needs_confirm, which
  // executeWrite drives via the confirm-token round trip.
  | { kind: "markCleanup"; track: string; repoKey?: string; reason?: string }
  // Clear the cleanup-candidate flag (#328/#329/#330) — the --clear inverse of
  // markCleanup. Same public-repo confirm-token flow.
  | { kind: "unmarkCleanup"; track: string; repoKey?: string }
  // Archive a track (reversibly) into archive/parked/ (#328).
  | { kind: "archiveTrack"; track: string; repoKey?: string }
  // Restore an archived track back into the active set (#328).
  | { kind: "unarchiveTrack"; track: string; repoKey?: string }
  // Delete a track's .md (#330). DESTRUCTIVE; never touches GitHub issues.
  | { kind: "deleteTrack"; track: string; repoKey?: string };

/** The user's decision from the public-repo confirm modal. */
export type ConfirmDecision = "writeAnyway" | "cancel";

/** Injected by the caller — in production it shows a vscode modal; in tests it's a fake. */
export type ConfirmPrompt = (reason: string) => Promise<ConfirmDecision>;

/** Result of executeWrite. */
export type WriteOutcome =
  | { status: "written"; stdout: string }
  | { status: "cancelled" }
  // The CLI's #241 guards declined the write so the caller can re-offer on fresh
  // state instead of treating it as success:
  //  - "stale": the target's issue list changed since the offer (CAS mismatch);
  //    `current` is the fresh on-disk list.
  //  - "needsRebase": a shared-tier plan branch diverged and couldn't auto-rebase.
  | { status: "stale"; current: number[] }
  | { status: "needsRebase" };

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
 *   reconcileApply  → ["reconcile", "--yes", "--", track]
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
 *   issueInProgress → ["in-progress", ..."--clear", "--repo=<slug>", "--", number]
 *   pushTrack       → ["push-track", ..."--repo=<key>", "--", track]
  setNextUpPreset → ["set-next-up", ..."--repo=<key>", "--preset=<p>"|"--clear"|"--auto=on|off", "--", track]
                    (auto alone: ["set-next-up", ..."--repo=<key>", "--auto=on|off", "--", track])
 *   planArchive    → ["plan-archive", "--repo=<key>", "--yes", "--json", "--", rel]
 *   planArchiveAllShipped → ["plan-status", "--repo=<key>", "--archive-shipped", "--yes", "--json", ..."--include-lie-gap"]
 *   markCleanup    → ["mark-cleanup", ..."--repo=<key>", ..."--reason=<text>", "--", track]
 *   unmarkCleanup  → ["mark-cleanup", ..."--repo=<key>", "--clear", "--", track]
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

    case "reconcileApply":
      return ["reconcile", "--yes", "--", action.track];

    case "hygiene":
      return ["hygiene", "--yes"];

    case "slot":
      return [
        "slot",
        "--no-move",
        ...(action.expect ? [`--expect=${action.expect}`] : []),
        "--",
        String(action.issue),
        action.track,
      ];

    case "batchSlot":
      return [
        "batch-slot",
        "--no-move",
        ...(action.expect ? [`--expect=${action.expect}`] : []),
        "--",
        ...action.issues.map(String),
        action.track,
      ];

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

    case "planArchive":
      return [
        "plan-archive",
        `--repo=${action.repoKey}`,
        "--yes",
        "--json",
        "--",
        action.rel,
      ];

    case "planUnarchive":
      return [
        "plan-unarchive",
        `--repo=${action.repoKey}`,
        "--yes",
        "--json",
        "--",
        action.rel,
      ];

    case "planArchiveAllShipped":
      return [
        "plan-status",
        `--repo=${action.repoKey}`,
        "--archive-shipped",
        "--yes",
        "--json",
        ...(action.includeLieGap ? ["--include-lie-gap"] : []),
      ];

    case "closeIssue":
      return [
        "close-issue",
        `--repo=${action.repo}`,
        `--reason=${action.reason}`,
        ...(action.comment ? [`--comment=${action.comment}`] : []),
        "--",
        String(action.number),
      ];

    case "issueInProgress":
      return [
        "in-progress",
        ...(action.clear ? ["--clear"] : []),
        `--repo=${action.repo}`,
        "--",
        String(action.number),
      ];

    case "pushTrack":
      return [
        "push-track",
        ...(action.repoKey ? [`--repo=${action.repoKey}`] : []),
        "--",
        action.track,
      ];

    case "setNextUpPreset":
      return [
        "set-next-up",
        ...(action.repoKey ? [`--repo=${action.repoKey}`] : []),
        ...(action.clear ? ["--clear"] : action.preset ? [`--preset=${action.preset}`] : []),
        ...(action.auto ? [`--auto=${action.auto}`] : []),
        "--",
        action.track,
      ];

    case "markCleanup":
      return [
        "mark-cleanup",
        ...(action.repoKey ? [`--repo=${action.repoKey}`] : []),
        ...(action.reason ? [`--reason=${action.reason}`] : []),
        "--",
        action.track,
      ];

    case "unmarkCleanup":
      return [
        "mark-cleanup",
        ...(action.repoKey ? [`--repo=${action.repoKey}`] : []),
        "--clear",
        "--",
        action.track,
      ];

    case "archiveTrack":
      return [
        "archive-track",
        ...(action.repoKey ? [`--repo=${action.repoKey}`] : []),
        "--",
        action.track,
      ];

    case "unarchiveTrack":
      return [
        "unarchive-track",
        ...(action.repoKey ? [`--repo=${action.repoKey}`] : []),
        "--",
        action.track,
      ];

    case "deleteTrack":
      return [
        "delete-track",
        ...(action.repoKey ? [`--repo=${action.repoKey}`] : []),
        "--",
        action.track,
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
    // parser, which would swallow the token instead of honouring it. The
    // confirmed re-invocation also carries --expect, so it can STILL come back
    // {stale}/{needs_rebase} even though confirm was satisfied (#241).
    const confirmedArgs = withConfirmToken(args, token);
    const confirmedResult = await runWrite(run, confirmedArgs);
    return guardOutcome(confirmedResult.json) ?? { status: "written", stdout: confirmedResult.stdout };
  }

  // #241 staleness / shared-rebase signals can arrive on the first (unconfirmed)
  // call too — a private-repo slot never hits the confirm gate.
  return guardOutcome(result.json) ?? { status: "written", stdout: result.stdout };
}

/**
 * Maps a CLI JSON response to a guard WriteOutcome, or null when it's a normal
 * write. The CLI emits these as pure-JSON stdout (it routes advisory notes to
 * stderr in --expect mode) so they parse cleanly.
 */
function guardOutcome(json: unknown): WriteOutcome | null {
  if (json === null || typeof json !== "object") {
    return null;
  }
  const blob = json as Record<string, unknown>;
  if (blob.stale === true) {
    const current = Array.isArray(blob.current)
      ? blob.current.filter((n): n is number => typeof n === "number")
      : [];
    return { status: "stale", current };
  }
  if (blob.needs_rebase === true) {
    return { status: "needsRebase" };
  }
  return null;
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
