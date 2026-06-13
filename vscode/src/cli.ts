import { spawn } from "node:child_process";
import type { Export, Issue, PlanStatus } from "./model.ts";

// ---------------------------------------------------------------------------
// Core types — the injectable seam between cli.ts and extension.ts
// ---------------------------------------------------------------------------

/** Raw result from a single CLI invocation. Never throws; the caller decides. */
export type CliResult = { code: number; stdout: string; stderr: string };

/** Injectable runner — real spawn in production, fake in tests. */
export type CliRunner = (args: string[]) => Promise<CliResult>;

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
  return (args: string[]): Promise<CliResult> => {
    return new Promise((resolve, reject) => {
      const child = spawn(cliPath, args, { shell: false });
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

  // Return typed; schema mismatch is a soft concern handled by the caller.
  return parsed as Export;
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
 * The CalVer date in which `export`/`set`/confirm-token first shipped.
 * NOTE: finalized at the Phase-4 publish step (Task 11) to the actual deployed
 * version; for now it gates against the Phase-1 date.
 */
export const MIN_CLI_VERSION = "2026.06.07";

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
