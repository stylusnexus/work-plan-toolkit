import { spawn } from "node:child_process";
import type { Export, Issue, IssueDep, PlanStatus } from "./model.ts";

// ---------------------------------------------------------------------------
// Core types — the injectable seam between cli.ts and extension.ts
// ---------------------------------------------------------------------------

/** Raw result from a single CLI invocation. Never throws; the caller decides. */
export type CliResult = { code: number; stdout: string; stderr: string };

/** Per-invocation options. `cwd` targets a specific directory — used by the
 *  repo auto-focus probe (#357), which runs `which-repo` from each workspace
 *  folder. Omitted → the CLI runs in the extension host's default cwd. */
export type CliRunOpts = { cwd?: string };

/** Injectable runner — real spawn in production, fake in tests. A fake that
 *  ignores `opts` (i.e. `(args) => …`) stays assignable, so existing callers and
 *  test doubles need no change. */
export type CliRunner = (args: string[], opts?: CliRunOpts) => Promise<CliResult>;

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

/** Thrown by high-level functions when the CLI exits non-zero or output is unparseable. */
export class CliError extends Error {
  readonly args: string[];
  readonly code: number;
  readonly stdout: string;
  readonly stderr: string;

  constructor(opts: {
    message: string;
    args: string[];
    code: number;
    stdout: string;
    stderr: string;
  }) {
    super(opts.message);
    this.name = "CliError";
    this.args = opts.args;
    this.code = opts.code;
    this.stdout = opts.stdout;
    this.stderr = opts.stderr;
  }
}

/**
 * True when `err` is a CliError signalling an "already exists" failure from the
 * CLI — e.g. `init-repo` on an already-registered key.
 *
 * CliError.message is built from **stderr only** (see runWrite), but init-repo
 * prints "already exists" to **stdout** (it uses `print(...)`). So matching on
 * the message misses it; we scan stdout AND stderr to be channel-agnostic.
 * Kept here in the tested pure layer rather than in the vscode glue so the
 * detection can't silently rot (#290).
 */
export function isAlreadyExistsError(err: unknown): boolean {
  return (
    err instanceof CliError &&
    /already exists/i.test((err.stdout ?? "") + (err.stderr ?? ""))
  );
}

// ---------------------------------------------------------------------------
// Real process runner — thin by design; not unit-tested
// ---------------------------------------------------------------------------

/**
 * Builds the production CliRunner from a resolved CLI path.
 * Rejects only on spawn failure (e.g. ENOENT); non-zero exit resolves normally.
 */
export function makeSpawnRunner(cliPath: string): CliRunner {
  return (args: string[], opts?: CliRunOpts): Promise<CliResult> => {
    return new Promise((resolve, reject) => {
      // cwd: undefined keeps spawn's default (the extension host's cwd), so
      // callers that omit opts are unaffected.
      const child = spawn(cliPath, args, { shell: false, cwd: opts?.cwd });
      let stdout = "";
      let stderr = "";
      // A non-ENOENT spawn error (EPERM, signal abort) can emit both "error" and
      // "close"; this flag ensures the promise settles exactly once.
      let settled = false;

      child.stdout.on("data", (chunk: Buffer) => {
        stdout += chunk.toString();
      });
      child.stderr.on("data", (chunk: Buffer) => {
        stderr += chunk.toString();
      });

      child.on("close", (code: number | null) => {
        if (settled) return;
        settled = true;
        resolve({ code: code ?? 1, stdout, stderr });
      });

      child.on("error", (err: NodeJS.ErrnoException) => {
        if (settled) return;
        settled = true;
        if (err.code === "ENOENT") {
          reject(
            new CliError({
              message: `work-plan CLI not found at "${cliPath}" — install it with: npm install -g @stylusnexus/work-plan`,
              args,
              code: -1,
              stdout,
              stderr: err.message,
            })
          );
        } else {
          reject(
            new CliError({
              message: `Failed to spawn work-plan CLI: ${err.message}`,
              args,
              code: -1,
              stdout,
              stderr: err.message,
            })
          );
        }
      });
    });
  };
}

// ---------------------------------------------------------------------------
// High-level CLI functions
// ---------------------------------------------------------------------------

/**
 * Normalizes a raw parsed issue from the export JSON, defaulting the
 * `blocked_by` and `blocking` dependency arrays to `[]` when absent (older
 * CLI payloads that predate #257). All other fields are passed through as-is.
 */
export function normalizeExportIssue(raw: Omit<Issue, "blocked_by" | "blocking"> & {
  blocked_by?: IssueDep[];
  blocking?: IssueDep[];
}): Issue {
  return {
    ...raw,
    blocked_by: raw.blocked_by ?? [],
    blocking: raw.blocking ?? [],
  };
}

/**
 * Runs `work-plan export --json` and returns the parsed Export object.
 * Throws CliError on non-zero exit or unparseable output.
 */
export async function exportJson(run: CliRunner): Promise<Export> {
  const args = ["export", "--json"];
  const result = await run(args);

  if (result.code !== 0) {
    throw new CliError({
      message: `work-plan export --json failed (exit ${result.code}): ${result.stderr.trim()}`,
      args,
      code: result.code,
      stdout: result.stdout,
      stderr: result.stderr,
    });
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(result.stdout);
  } catch {
    throw new CliError({
      message: `could not parse export JSON: ${result.stdout.slice(0, 200)}`,
      args,
      code: result.code,
      stdout: result.stdout,
      stderr: result.stderr,
    });
  }

  // Normalize the parsed Export: default blocked_by/blocking to [] on every
  // issue so consumers never see undefined (handles older CLI payloads, #257).
  const exp = parsed as Export;
  for (const track of exp.tracks) {
    track.issues = track.issues.map(normalizeExportIssue);
  }
  for (const bucket of exp.untracked ?? []) {
    bucket.issues = bucket.issues.map(normalizeExportIssue);
  }
  return exp;
}

/** A repo's open issues, as emitted by `work-plan list-open-issues` (#282). */
export interface RepoOpenIssues {
  repo: string;
  issues: Issue[];
}

/**
 * Runs `work-plan list-open-issues --repo <repo> [--exclude <csv>]` and returns
 * the repo's open issues (#282). `exclude` drops issues already in the track so
 * they don't reappear in the Slot pick-list. Throws CliError on non-zero exit or
 * unparseable output.
 */
export async function listRepoOpenIssues(
  run: CliRunner,
  repo: string,
  exclude: number[] = [],
): Promise<RepoOpenIssues> {
  const args = [`list-open-issues`, `--repo=${repo}`];
  if (exclude.length > 0) {
    args.push(`--exclude=${exclude.join(",")}`);
  }
  const result = await run(args);

  if (result.code !== 0) {
    throw new CliError({
      message: `work-plan list-open-issues failed (exit ${result.code}): ${result.stderr.trim()}`,
      args,
      code: result.code,
      stdout: result.stdout,
      stderr: result.stderr,
    });
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(result.stdout);
  } catch {
    throw new CliError({
      message: `could not parse list-open-issues JSON: ${result.stdout.slice(0, 200)}`,
      args,
      code: result.code,
      stdout: result.stdout,
      stderr: result.stderr,
    });
  }

  return parsed as RepoOpenIssues;
}

/**
 * Runs `work-plan plan-status --repo=<key> --json [--stall-days=<n>]` and returns
 * the parsed plan-status report (#164). Throws CliError on non-zero exit or
 * unparseable output.
 */
export async function planStatus(
  run: CliRunner,
  repoKey: string,
  stallDays?: number,
): Promise<PlanStatus> {
  const args = ["plan-status", `--repo=${repoKey}`, "--json"];
  if (stallDays !== undefined) args.push(`--stall-days=${stallDays}`);
  const result = await run(args);
  if (result.code !== 0) {
    throw new CliError({
      message: `work-plan plan-status failed (exit ${result.code}): ${result.stderr.trim()}`,
      args,
      code: result.code,
      stdout: result.stdout,
      stderr: result.stderr,
    });
  }
  try {
    return JSON.parse(result.stdout) as PlanStatus;
  } catch {
    throw new CliError({
      message: `could not parse plan-status JSON: ${result.stdout.slice(0, 200)}`,
      args,
      code: result.code,
      stdout: result.stdout,
      stderr: result.stderr,
    });
  }
}

/** One issue in an auto-next suggestion (#274). */
export interface NextUpCandidate {
  number: number;
  title: string;
  priority: string;
  milestone: string;
}

/** Read-only result of `handoff --suggest-next` (#274). `suggested` is in the
 *  CLI's algorithmic priority order; `skipped` lists issues dropped because a
 *  sibling active track already queued them. `error` is a soft, payload-level
 *  note (no repo / no issues) — the call still resolves, not throws. */
export interface NextUpSuggestion {
  track: string;
  repo: string | null;
  current: number[];
  suggested: NextUpCandidate[];
  skipped: { number: number; claimed_by: string }[];
  error?: string;
}

/**
 * Compute the algorithmic next_up suggestion for a track WITHOUT writing — the
 * read-only feed for the native auto-next picker (#274). The picker confirms +
 * edits, then writes back via the audited `setNext` path (`handoff --set-next`).
 */
export async function suggestNextUp(
  run: CliRunner,
  track: string,
  repoKey?: string,
): Promise<NextUpSuggestion> {
  const args = ["handoff", "--suggest-next"];
  if (repoKey) args.push(`--repo=${repoKey}`);
  args.push("--", track);
  const result = await run(args);
  if (result.code !== 0) {
    throw new CliError({
      message: `work-plan handoff --suggest-next failed (exit ${result.code}): ${result.stderr.trim()}`,
      args,
      code: result.code,
      stdout: result.stdout,
      stderr: result.stderr,
    });
  }
  try {
    return JSON.parse(result.stdout) as NextUpSuggestion;
  } catch {
    throw new CliError({
      message: `could not parse suggest-next JSON: ${result.stdout.slice(0, 200)}`,
      args,
      code: result.code,
      stdout: result.stdout,
      stderr: result.stderr,
    });
  }
}

/**
 * Runs an arbitrary write command (e.g. `set`, `confirm`).
 * Resolves with parsed JSON when the output is valid JSON, null otherwise
 * (the `set` command prints either a `{needs_confirm,...}` object or a human "✓ …" line).
 * Throws CliError on non-zero exit.
 */
export async function runWrite(
  run: CliRunner,
  args: string[]
): Promise<{ stdout: string; json: any | null }> {
  const result = await run(args);

  if (result.code !== 0) {
    throw new CliError({
      message: `work-plan ${args[0] ?? ""} failed (exit ${result.code}): ${result.stderr.trim()}`,
      args,
      code: result.code,
      stdout: result.stdout,
      stderr: result.stderr,
    });
  }

  let json: any | null = null;
  try {
    json = JSON.parse(result.stdout);
  } catch {
    // Human-readable success line — json stays null, which is expected.
  }

  return { stdout: result.stdout, json };
}

// ---------------------------------------------------------------------------
// Version gate
// ---------------------------------------------------------------------------

/**
 * The CalVer date of the oldest CLI the extension can drive. This is the
 * 2026.06.14 release, which added the per-issue `in_progress` export field +
 * `in-progress` subcommand (#271) AND the `blocked_by`/`blocking` export edges
 * (#257) — the in-progress badge/toggle and the dependency graph/chips depend
 * on these. An older CLI omits the fields, so checkVersion surfaces a compat
 * warning instead of letting those surfaces silently fail.
 *
 * INVARIANT: never set this ahead of the repo's own `VERSION` file — the
 * extension and the CLI it ships alongside reach `main` in the same deploy, so
 * the gate must equal (not exceed) that deploy's CalVer. A test in cli.test.ts
 * enforces `meetsMinVersion(<VERSION>, MIN_CLI_VERSION)`. (0.9.0 shipped this
 * one day ahead — "2026.06.15" vs a 2026.06.14 deploy — so every updated user
 * got a false "CLI incompatible" warning; 0.9.1 corrects it.)
 */
export const MIN_CLI_VERSION = "2026.06.15";

/**
 * Parses the version token from `work-plan --version` output.
 * The CLI prints `work-plan <VERSION>` (e.g. `work-plan 2026.06.07+9f049ec`).
 * Returns the `YYYY.MM.DD` string, or null if unparseable.
 */
export function parseVersion(versionOutput: string): string | null {
  // Strip optional "work-plan " prefix and trailing whitespace.
  const token = versionOutput.trim().replace(/^work-plan\s+/, "");
  // Take the part before any + build-suffix.
  const base = token.split("+")[0].trim();
  // Validate YYYY.MM.DD shape.
  if (/^\d{4}\.\d{2}\.\d{2}$/.test(base)) {
    return base;
  }
  return null;
}

/**
 * Compares two `YYYY.MM.DD` CalVer strings as numeric tuples.
 * Returns true when `actual >= min`.
 */
export function meetsMinVersion(actual: string, min: string): boolean {
  const toTuple = (v: string): [number, number, number] => {
    const parts = v.split(".").map(Number);
    return [parts[0], parts[1], parts[2]];
  };
  const [ay, am, ad] = toTuple(actual);
  const [my, mm, md] = toTuple(min);
  if (ay !== my) return ay > my;
  if (am !== mm) return am > mm;
  return ad >= md;
}

/**
 * Checks whether the installed CLI meets MIN_CLI_VERSION.
 * Never throws — activation should degrade gracefully to a warning.
 */
export async function checkVersion(
  run: CliRunner
): Promise<{ ok: boolean; version: string | null }> {
  try {
    const result = await run(["--version"]);
    if (result.code !== 0) {
      return { ok: false, version: null };
    }
    const version = parseVersion(result.stdout);
    if (version === null) {
      return { ok: false, version: null };
    }
    return { ok: meetsMinVersion(version, MIN_CLI_VERSION), version };
  } catch {
    // Spawn failure (ENOENT) or any other error — degrade gracefully.
    return { ok: false, version: null };
  }
}

// ---------------------------------------------------------------------------
// GitHub auth probe (#auth) — fast-fail instead of silent degradation
// ---------------------------------------------------------------------------

/** Parsed `auth-status --json` result. `ghPresent` false ⇒ gh not installed
 *  (a different fix than "not signed in"); both leave `authenticated` false. */
export type AuthState = {
  authenticated: boolean;
  ghPresent: boolean;
  user: string | null;
};

/**
 * Runs `auth-status --json` and reports whether `gh` is installed + signed in.
 * Never throws — auth detection must degrade gracefully, not break activation.
 * A spawn failure or unparseable output is treated as "gh present, not
 * authenticated" (the conservative state that surfaces the sign-in path) UNLESS
 * the CLI itself couldn't be found, which the caller already reports separately.
 */
export async function checkAuth(run: CliRunner): Promise<AuthState> {
  try {
    const result = await run(["auth-status", "--json"]);
    const blob = JSON.parse(result.stdout) as Partial<{
      authenticated: boolean; gh_present: boolean; user: string | null;
    }>;
    return {
      authenticated: Boolean(blob.authenticated),
      ghPresent: blob.gh_present !== false, // default true unless explicitly false
      user: blob.user ?? null,
    };
  } catch {
    return { authenticated: false, ghPresent: true, user: null };
  }
}

// ---------------------------------------------------------------------------
// which-repo — resolve a directory to a configured repo (#357/#358)
// ---------------------------------------------------------------------------

/** Parsed `which-repo --json` result. `github` may be null for a repo with no
 *  configured slug — the viewer can't focus those (the repo lens keys on the
 *  slug), so they're treated as "no usable match." */
export type ResolvedRepo = { key: string; github: string | null };

/**
 * Runs `which-repo --json` with `cwd` set to the given directory and returns the
 * resolved repo, or null on no match / non-repo / parse failure. Never throws —
 * auto-focus must degrade silently, never break activation.
 */
export async function whichRepo(run: CliRunner, cwd: string): Promise<ResolvedRepo | null> {
  try {
    const result = await run(["which-repo", "--json"], { cwd });
    const blob = JSON.parse(result.stdout) as Partial<{ key: string | null; github: string | null }>;
    if (!blob || blob.key == null) return null;
    return { key: blob.key, github: blob.github ?? null };
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// auto-triage scan (#241) — fetch untracked issues + the AI prompt for the viewer
// ---------------------------------------------------------------------------

/**
 * The one JSON object emitted by `auto-triage --json --repo=<key>` (#241). The
 * viewer captures `batch_id` to correlate the answers a Claude session writes
 * back, and `answers_path` (used verbatim — never recomputed) is where those
 * answers must land. `prompt` is relayed to the output channel.
 */
export interface AutoTriageScan {
  batch_id: string;
  repo: string;
  folder: string | null;
  untracked: { number: number; title: string }[];
  tracks: { slug: string; name: string; milestone: string | null; priority: string | null; scope: string }[];
  prompt: string;
  /** Absolute path the agent should write the answers JSON to (per-repo). */
  answers_path: string;
  /** Set on informational early-exits the CLI emits as JSON in --json mode:
   *  "no_active_tracks" (nothing to suggest into) / "full_coverage" (no
   *  untracked issues). batch_id/prompt/answers_path are absent in those cases. */
  note?: string;
}

/**
 * Runs `auto-triage --json --repo=<folderKey>` and returns the parsed scan
 * (#241). The CLI prints progress to stderr so stdout is one clean JSON object.
 * A "full coverage" repo (no untracked issues) prints a human line instead of
 * JSON — that parses as failure, surfaced as a soft CliError the caller can
 * detect and message as "nothing to triage". Throws CliError on non-zero exit
 * or unparseable output.
 */
export async function autoTriageScan(
  run: CliRunner,
  folderKey: string,
  opts: { heuristic?: boolean } = {},
): Promise<AutoTriageScan> {
  const args = ["auto-triage", "--json", `--repo=${folderKey}`];
  // --heuristic (#373): the CLI writes the v2 answers file itself (no LLM), so
  // suggestions appear with no Claude session — lower-trust, but offline.
  if (opts.heuristic) args.push("--heuristic");
  const result = await run(args);
  if (result.code !== 0) {
    throw new CliError({
      message: `work-plan auto-triage failed (exit ${result.code}): ${result.stderr.trim()}`,
      args,
      code: result.code,
      stdout: result.stdout,
      stderr: result.stderr,
    });
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(result.stdout);
  } catch {
    throw new CliError({
      message: `could not parse auto-triage JSON: ${result.stdout.slice(0, 200)}`,
      args,
      code: result.code,
      stdout: result.stdout,
      stderr: result.stderr,
    });
  }
  return parsed as AutoTriageScan;
}

// ---------------------------------------------------------------------------
// notes-vcs — opt-in local history for the private notes_root tier (#103/#224)
// ---------------------------------------------------------------------------

/** Machine-readable state from `notes-vcs status --json`. */
export type NotesVcsStatus = {
  notes_root: string;
  under_git: boolean;
  is_root: boolean;
  auto_commit: boolean;
  last_commit_sha: string | null;
  /** Short sha of HEAD's first parent (null at the root commit). Used to confirm
   *  a post-write HEAD sits directly on the previously-seen commit before Undo. */
  head_parent_sha: string | null;
  last_commit_subject: string | null;
  dirty: boolean;
};

/**
 * Runs `notes-vcs status --json` and returns the parsed state, or null on any
 * failure. Never throws — local history is an enhancement, so a missing/old CLI
 * must degrade to "feature absent", not break the viewer.
 */
export async function notesVcsStatus(run: CliRunner): Promise<NotesVcsStatus | null> {
  try {
    const result = await run(["notes-vcs", "status", "--json"]);
    if (result.code !== 0) return null;
    const blob = JSON.parse(result.stdout) as Partial<NotesVcsStatus>;
    if (typeof blob !== "object" || blob === null) return null;
    return {
      notes_root: String(blob.notes_root ?? ""),
      under_git: Boolean(blob.under_git),
      is_root: Boolean(blob.is_root),
      auto_commit: Boolean(blob.auto_commit),
      last_commit_sha: blob.last_commit_sha ?? null,
      head_parent_sha: blob.head_parent_sha ?? null,
      last_commit_subject: blob.last_commit_subject ?? null,
      dirty: Boolean(blob.dirty),
    };
  } catch {
    return null;
  }
}

/**
 * Runs a side-effecting `notes-vcs` action (init / enable / disable).
 * Throws CliError on non-zero exit so the caller can surface the message.
 */
export async function notesVcsRun(
  run: CliRunner,
  action: "init" | "enable" | "disable",
): Promise<string> {
  const args = ["notes-vcs", action];
  const result = await run(args);
  if (result.code !== 0) {
    throw new CliError({
      message: `work-plan notes-vcs ${action} failed (exit ${result.code}): ${result.stderr.trim()}`,
      args,
      code: result.code,
      stdout: result.stdout,
      stderr: result.stderr,
    });
  }
  return result.stdout;
}

/**
 * Reverts a notes_root commit via `notes-vcs undo [<sha>]` (git stays in the
 * engine). The sha is placed after a `--` separator so a dash-led value can't
 * be misread as a flag. Throws CliError on non-zero exit.
 */
export async function notesVcsUndo(run: CliRunner, sha?: string): Promise<string> {
  const args = sha ? ["notes-vcs", "undo", "--", sha] : ["notes-vcs", "undo"];
  const result = await run(args);
  if (result.code !== 0) {
    throw new CliError({
      message: `work-plan notes-vcs undo failed (exit ${result.code}): ${result.stderr.trim()}`,
      args,
      code: result.code,
      stdout: result.stdout,
      stderr: result.stderr,
    });
  }
  return result.stdout;
}
