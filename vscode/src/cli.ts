import { spawn } from "node:child_process";
import type { Export } from "./model.ts";

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
