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
  /** True when the spawn failed with ENOENT — the `work-plan` binary itself
   *  wasn't found on the extension host's PATH (a different fix than "not
   *  signed in"; #402). Lets callers distinguish a missing CLI from a real
   *  error without matching on the message string. */
  readonly notFound: boolean;

  constructor(opts: {
    message: string;
    args: string[];
    code: number;
    stdout: string;
    stderr: string;
    notFound?: boolean;
  }) {
    super(opts.message);
    this.name = "CliError";
    this.args = opts.args;
    this.code = opts.code;
    this.stdout = opts.stdout;
    this.stderr = opts.stderr;
    this.notFound = opts.notFound ?? false;
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
              notFound: true,
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
export async function exportJson(run: CliRunner, includeArchived = false): Promise<Export> {
  const args = includeArchived ? ["export", "--json", "--include-archived"] : ["export", "--json"];
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
  const args = ["plan-status", `--repo=${repoKey}`, "--json", "--include-archived"];
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
 * 2026.07.15 release, which added the `doctor` subcommand (#439) — the new
 * status-bar config-drift indicator calls `doctor --json` at activation, and
 * an older CLI doesn't have the subcommand at all, so checkVersion surfaces a
 * compat warning instead of the doctor call silently no-op'ing with zero
 * signal as to why.
 *
 * INVARIANT: never set this ahead of the repo's own `VERSION` file — the
 * extension and the CLI it ships alongside reach `main` in the same deploy, so
 * the gate must equal (not exceed) that deploy's CalVer. A test in cli.test.ts
 * enforces `meetsMinVersion(<VERSION>, MIN_CLI_VERSION)`. (0.9.0 shipped this
 * one day ahead — "2026.06.15" vs a 2026.06.14 deploy — so every updated user
 * got a false "CLI incompatible" warning; 0.9.1 corrects it. This bump is a
 * deliberate follow-up commit made AFTER the #439 merge, once VERSION was
 * actually stamped — see docs/superpowers/specs/2026-07-15-config-drift-doctor-design.md's
 * "Rollout sequencing," since bumping this in the same PR as the feature
 * would set it ahead of the still-old checked-in VERSION and fail this exact
 * invariant test.)
 */
export const MIN_CLI_VERSION = "2026.07.15";

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

/** Parsed `auth-status --json` result. Three distinct "not authenticated"
 *  causes, each with its own fix:
 *   - `cliPresent` false ⇒ the `work-plan` CLI itself wasn't found on the
 *     extension host's PATH (#402 — common in Remote-WSL when the CLI was
 *     installed on Windows but the host runs in WSL). Install the CLI.
 *   - `ghPresent` false ⇒ `gh` not installed. Install gh.
 *   - both true, `authenticated` false ⇒ genuinely not signed in. Run sign-in.
 *  When `cliPresent` is false, `ghPresent` is unknown (we never reached gh) and
 *  reported false so callers don't show a misleading gh-specific message.
 *
 *  `probeOk` signals whether the auth probe itself ran and returned a parseable,
 *  authoritative answer (`true`), or whether the probe errored / couldn't be
 *  trusted (`false` — transient). When `probeOk` is false the caller should keep
 *  the last-good tree rather than switching to an onboarding banner.
 *
 *  `error` is a short human reason set ONLY when the probe ran but produced no
 *  trustworthy answer (`probeOk:false` with `cliPresent:true`) — typically the
 *  launcher's own stderr, e.g. "work-plan: missing required tool(s) on PATH: yq".
 *  It lets the caller say "the CLI couldn't run: <reason>" instead of the
 *  misleading "not signed in to GitHub". Null whenever there's nothing to add. */
export type AuthState = {
  authenticated: boolean;
  cliPresent: boolean;
  ghPresent: boolean;
  probeOk: boolean;
  user: string | null;
  error: string | null;
};

/**
 * Runs `auth-status --json` and reports whether `gh` is installed + signed in.
 * Never throws — auth detection must degrade gracefully, not break activation.
 *
 * Three failure shapes, kept distinct so the caller never mislabels one as
 * "not signed in":
 *  - spawn ENOENT (#402) → `cliPresent:false` ("install the CLI").
 *  - the CLI ran but emitted no parseable JSON (older launcher gating the probe
 *    behind a missing dependency like yq, a crash, a truncated pipe) →
 *    `probeOk:false` with `error` carrying the launcher's stderr. This is a CLI
 *    runtime problem, NOT a sign-in state.
 *  - clean parse → `probeOk:true`; `authenticated`/`ghPresent` are authoritative.
 */
export async function checkAuth(run: CliRunner): Promise<AuthState> {
  let result: CliResult;
  try {
    result = await run(["auth-status", "--json"]);
  } catch (err) {
    // The work-plan binary wasn't found on PATH — distinct from a gh/auth
    // failure. ghPresent is unknown (we never reached gh) → false, but cliPresent
    // false is what drives the message. This IS authoritative (CLI truly absent),
    // so probeOk stays false (we got no parseable answer) but cliPresent:false
    // tells the caller to show the install-the-CLI banner, not keep last-good.
    if (err instanceof CliError && err.notFound) {
      return { authenticated: false, cliPresent: false, ghPresent: false, probeOk: false, user: null, error: null };
    }
    // A non-ENOENT spawn error (EPERM, signal abort) — transient.
    const reason = err instanceof Error ? err.message : String(err);
    return { authenticated: false, cliPresent: true, ghPresent: true, probeOk: false, user: null, error: reason || null };
  }

  try {
    const blob = JSON.parse(result.stdout) as Partial<{
      authenticated: boolean; gh_present: boolean; user: string | null;
    }>;
    return {
      authenticated: Boolean(blob.authenticated),
      cliPresent: true,
      ghPresent: blob.gh_present !== false, // default true unless explicitly false
      probeOk: true,
      user: blob.user ?? null,
      error: null,
    };
  } catch {
    // The CLI ran (we reached this binary) but returned nothing parseable. That
    // is a runtime/dependency problem, NOT "not signed in". Surface the
    // launcher's own diagnostics (first non-empty line of stderr — the launcher
    // writes missing-tool messages there; unparseable stdout is the failure
    // itself, not a human reason) so the caller can name the real fix instead of
    // sending the user into a futile sign-in loop.
    const reason =
      result.stderr
        .split("\n")
        .map((l) => l.trim())
        .find((l) => l.length > 0) ?? null;
    return { authenticated: false, cliPresent: true, ghPresent: true, probeOk: false, user: null, error: reason };
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
// doctor — config-drift scan (#: doctor)
// ---------------------------------------------------------------------------

/** One `doctor --json` finding. Mirrors commands/doctor.py's finding dict. */
export type DoctorFinding = {
  type: string;
  key: string | null;
  folder: string | null;
  track: string | null;
  message: string;
  fixable: boolean;
  unverified: boolean;
  old: string | null;
  new: string | null;
};

/**
 * Runs `doctor --json` and returns its findings, or null on anything that
 * makes the result untrustworthy: a nonzero exit, a spawn rejection, JSON
 * that doesn't parse, JSON with a "findings" field missing or not an array,
 * or JSON carrying a "fatal" key (doctor's own Step 0 failure shape — this
 * must NEVER be read as "0 findings = clean"). Never throws — this is a
 * convenience signal, exactly like whichRepo/checkVersion.
 */
export async function doctorScan(run: CliRunner): Promise<DoctorFinding[] | null> {
  try {
    const result = await run(["doctor", "--json"]);
    if (result.code !== 0) return null;
    const blob = JSON.parse(result.stdout) as Partial<{
      fatal: string;
      attempts: unknown;
      findings: unknown;
    }>;
    if (!blob || typeof blob !== "object") return null;
    if ("fatal" in blob) return null;
    if (!Array.isArray(blob.findings)) return null;
    return blob.findings as DoctorFinding[];
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
   *  untracked issues) / "fetch_failed" (the GitHub open-issues fetch itself
   *  failed — untracked is [] but that does NOT mean full coverage).
   *  batch_id/prompt/answers_path are absent in those cases. */
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
