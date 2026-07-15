import { test, describe } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import type { CliResult, CliRunner } from "./cli.ts";
import {
  CliError,
  isAlreadyExistsError,
  exportJson,
  listRepoOpenIssues,
  planStatus,
  runWrite,
  parseVersion,
  meetsMinVersion,
  checkVersion,
  checkAuth,
  MIN_CLI_VERSION,
  notesVcsStatus,
  notesVcsRun,
  notesVcsUndo,
  normalizeExportIssue,
  suggestNextUp,
  doctorScan,
} from "./cli.ts";
import type { Export } from "./model.ts";

// ---------------------------------------------------------------------------
// Fixtures & helpers
// ---------------------------------------------------------------------------

/** Builds a fake CliRunner that always returns the given canned result. */
function fakeRunner(result: CliResult): CliRunner {
  return (_args: string[]) => Promise.resolve(result);
}

/** A valid schema-1 Export payload for happy-path tests. */
const VALID_EXPORT: Export = {
  schema: 1,
  generated_at: "2026-06-07T00:00:00Z",
  tracks: [
    {
      name: "platform-health",
      repo: "your-org/myproject",
      tier: "private",
      status: "active",
      launch_priority: "P2",
      milestone_alignment: "v1",
      visibility: "PRIVATE",
      blockers: [],
      next_up: [101],
      rollup: { open: 3, closed: 7 },
      issues: [
        {
          number: 101,
          title: "Fix auth flow",
          state: "open",
          assignee: "@eve",
          milestone: "v1",
          in_progress: false,
        },
      ],
    },
  ],
};

// ---------------------------------------------------------------------------
// exportJson
// ---------------------------------------------------------------------------

describe("exportJson", () => {
  test("parses a canned valid schema-1 JSON into an Export", async () => {
    const run = fakeRunner({ code: 0, stdout: JSON.stringify(VALID_EXPORT), stderr: "" });
    const result = await exportJson(run);

    assert.equal(result.schema, 1);
    assert.equal(result.tracks.length, 1);
    assert.equal(result.tracks[0].name, "platform-health");
    assert.equal(result.tracks[0].issues[0].number, 101);
    assert.equal(result.tracks[0].issues[0].state, "open");
  });

  test("throws CliError when runner returns a non-zero exit code", async () => {
    const run = fakeRunner({ code: 1, stdout: "", stderr: "no config found" });
    await assert.rejects(
      () => exportJson(run),
      (err: unknown) => {
        assert.ok(err instanceof CliError, "should be CliError");
        assert.equal((err as CliError).code, 1);
        assert.ok((err as CliError).stderr.includes("no config found"));
        return true;
      }
    );
  });

  test("throws CliError when stdout is not valid JSON", async () => {
    const run = fakeRunner({ code: 0, stdout: "not-json{{", stderr: "" });
    await assert.rejects(
      () => exportJson(run),
      (err: unknown) => {
        assert.ok(err instanceof CliError, "should be CliError");
        assert.ok((err as CliError).message.includes("could not parse export JSON"));
        return true;
      }
    );
  });
});

// ---------------------------------------------------------------------------
// listRepoOpenIssues (#282)
// ---------------------------------------------------------------------------

/** A runner that records the args it was called with, returning a canned result. */
function recordingRunner(result: CliResult): { run: CliRunner; calls: string[][] } {
  const calls: string[][] = [];
  const run: CliRunner = (args: string[]) => {
    calls.push(args);
    return Promise.resolve(result);
  };
  return { run, calls };
}

const VALID_OPEN_ISSUES = {
  repo: "your-org/myproject",
  issues: [
    { number: 142, title: "Add SSO", state: "open", assignee: "—", milestone: null, in_progress: false },
    { number: 87, title: "Fix auth", state: "open", assignee: "@eve", milestone: "v0.6", in_progress: false },
  ],
};

describe("listRepoOpenIssues", () => {
  test("parses a canned response into RepoOpenIssues", async () => {
    const run = fakeRunner({ code: 0, stdout: JSON.stringify(VALID_OPEN_ISSUES), stderr: "" });
    const result = await listRepoOpenIssues(run, "your-org/myproject");
    assert.equal(result.repo, "your-org/myproject");
    assert.equal(result.issues.length, 2);
    assert.equal(result.issues[0].number, 142);
  });

  test("passes --repo and omits --exclude when the exclude list is empty", async () => {
    const { run, calls } = recordingRunner({ code: 0, stdout: JSON.stringify(VALID_OPEN_ISSUES), stderr: "" });
    await listRepoOpenIssues(run, "o/r");
    assert.deepEqual(calls[0], ["list-open-issues", "--repo=o/r"]);
  });

  test("passes --exclude as a CSV when issues are excluded", async () => {
    const { run, calls } = recordingRunner({ code: 0, stdout: JSON.stringify(VALID_OPEN_ISSUES), stderr: "" });
    await listRepoOpenIssues(run, "o/r", [87, 91]);
    assert.deepEqual(calls[0], ["list-open-issues", "--repo=o/r", "--exclude=87,91"]);
  });

  test("throws CliError on a non-zero exit", async () => {
    const run = fakeRunner({ code: 1, stdout: "", stderr: "boom" });
    await assert.rejects(
      () => listRepoOpenIssues(run, "o/r"),
      (err: unknown) => {
        assert.ok(err instanceof CliError, "should be CliError");
        assert.ok((err as CliError).stderr.includes("boom"));
        return true;
      },
    );
  });

  test("throws CliError when stdout is not valid JSON", async () => {
    const run = fakeRunner({ code: 0, stdout: "not-json{{", stderr: "" });
    await assert.rejects(
      () => listRepoOpenIssues(run, "o/r"),
      (err: unknown) => {
        assert.ok(err instanceof CliError, "should be CliError");
        assert.ok((err as CliError).message.includes("could not parse list-open-issues JSON"));
        return true;
      },
    );
  });
});

// ---------------------------------------------------------------------------
// planStatus (#164)
// ---------------------------------------------------------------------------

const VALID_PLAN_STATUS = {
  repo: "your-org/myproject",
  docs: [
    {
      rel: "plans/auth-refactor.md",
      kind: "plan",
      verdict: "partial",
      glyph: "◐",
      rationale: "3 of 7 declared files present; 2 of 9 checkboxes done",
      files_present: 3,
      files_declared: 7,
      checkboxes_done: 2,
      checkboxes_total: 9,
      last_touched: "2026-05-29",
      manifest_last_touched: "2026-05-15",
      stalled: true,
      lie_gap: false,
      unchecked_items: ["wire up session store", "add logout route"],
      stall_days: 14,
    },
  ],
};

describe("planStatus", () => {
  test("parses a canned response into PlanStatus", async () => {
    const run = fakeRunner({ code: 0, stdout: JSON.stringify(VALID_PLAN_STATUS), stderr: "" });
    const result = await planStatus(run, "myrepo");
    assert.equal(result.repo, "your-org/myproject");
    assert.equal(result.docs.length, 1);
    assert.equal(result.docs[0].stalled, true);
    assert.equal(result.docs[0].kind, "plan");
  });

  test("passes --stall-days when provided", async () => {
    const { run, calls } = recordingRunner({ code: 0, stdout: JSON.stringify(VALID_PLAN_STATUS), stderr: "" });
    await planStatus(run, "myrepo", 30);
    assert.deepEqual(calls[0], ["plan-status", "--repo=myrepo", "--json", "--include-archived", "--stall-days=30"]);
  });

  test("always passes --include-archived; omits --stall-days when not provided", async () => {
    const { run, calls } = recordingRunner({ code: 0, stdout: JSON.stringify(VALID_PLAN_STATUS), stderr: "" });
    await planStatus(run, "myrepo");
    assert.deepEqual(calls[0], ["plan-status", "--repo=myrepo", "--json", "--include-archived"]);
  });

  test("throws CliError on a non-zero exit", async () => {
    const run = fakeRunner({ code: 1, stdout: "", stderr: "boom" });
    await assert.rejects(
      () => planStatus(run, "myrepo"),
      (err: unknown) => {
        assert.ok(err instanceof CliError, "should be CliError");
        assert.ok((err as CliError).stderr.includes("boom"));
        return true;
      },
    );
  });
});

// ---------------------------------------------------------------------------
// runWrite
// ---------------------------------------------------------------------------

describe("runWrite", () => {
  test("returns parsed json when stdout is a {needs_confirm:true,...} object", async () => {
    const payload = { needs_confirm: true, token: "abc123", message: "Set status?" };
    const run = fakeRunner({ code: 0, stdout: JSON.stringify(payload), stderr: "" });
    const result = await runWrite(run, ["set", "status", "shipped", "--track", "platform-health"]);

    assert.deepEqual(result.json, payload);
    assert.ok(result.json.needs_confirm === true);
  });

  test("returns {json: null} when stdout is a human success line", async () => {
    const run = fakeRunner({ code: 0, stdout: "✓ set status on ph", stderr: "" });
    const result = await runWrite(run, ["set", "status", "shipped", "--track", "ph"]);

    assert.equal(result.json, null);
    assert.equal(result.stdout, "✓ set status on ph");
  });

  test("throws CliError on non-zero exit code", async () => {
    const run = fakeRunner({ code: 2, stdout: "", stderr: "unknown track" });
    await assert.rejects(
      () => runWrite(run, ["set", "status", "shipped"]),
      (err: unknown) => {
        assert.ok(err instanceof CliError, "should be CliError");
        assert.equal((err as CliError).code, 2);
        return true;
      }
    );
  });
});

// ---------------------------------------------------------------------------
// meetsMinVersion
// ---------------------------------------------------------------------------

describe("meetsMinVersion", () => {
  test("equal dates → true", () => {
    assert.equal(meetsMinVersion("2026.06.07", "2026.06.07"), true);
  });

  test("newer actual year → true", () => {
    assert.equal(meetsMinVersion("2027.01.01", "2026.06.07"), true);
  });

  test("newer actual month → true", () => {
    assert.equal(meetsMinVersion("2026.07.01", "2026.06.07"), true);
  });

  test("newer actual day → true", () => {
    assert.equal(meetsMinVersion("2026.06.08", "2026.06.07"), true);
  });

  test("older actual month → false", () => {
    assert.equal(meetsMinVersion("2026.05.30", "2026.06.07"), false);
  });

  test("older actual day → false", () => {
    assert.equal(meetsMinVersion("2026.06.06", "2026.06.07"), false);
  });

  test("older actual year → false", () => {
    assert.equal(meetsMinVersion("2025.12.31", "2026.06.07"), false);
  });

  test("a CLI older than the in-progress/blocked-by release fails the min-version gate", () => {
    assert.equal(meetsMinVersion("2026.06.13", "2026.06.14"), false);
    assert.equal(meetsMinVersion("2026.06.14", "2026.06.14"), true);
  });

  test("MIN_CLI_VERSION is never ahead of the repo's own CLI VERSION", () => {
    // Root-cause guard for the 0.9.0 regression: MIN_CLI_VERSION was set one day
    // ahead of the deploy (2026.06.15 vs a 2026.06.14 CLI), so every updated user
    // saw a false "CLI incompatible" warning. The extension and the CLI it ships
    // beside reach main in the same deploy, so the gate must never exceed the
    // repo's stamped VERSION.
    const versionFile = fs
      .readFileSync(new URL("../../VERSION", import.meta.url), "utf8")
      .trim();
    const repoVersion = parseVersion(versionFile);
    assert.notEqual(repoVersion, null, `VERSION file unparseable: ${versionFile}`);
    assert.equal(
      meetsMinVersion(repoVersion as string, MIN_CLI_VERSION),
      true,
      `MIN_CLI_VERSION (${MIN_CLI_VERSION}) is ahead of repo VERSION (${repoVersion})`,
    );
  });
});

// ---------------------------------------------------------------------------
// parseVersion
// ---------------------------------------------------------------------------

describe("parseVersion", () => {
  test("parses 'work-plan 2026.06.07+9f049ec' → '2026.06.07'", () => {
    assert.equal(parseVersion("work-plan 2026.06.07+9f049ec"), "2026.06.07");
  });

  test("parses 'work-plan 2026.06.07' with no build suffix", () => {
    assert.equal(parseVersion("work-plan 2026.06.07"), "2026.06.07");
  });

  test("'work-plan unknown' → null", () => {
    assert.equal(parseVersion("work-plan unknown"), null);
  });

  test("bare version string without prefix parses correctly", () => {
    assert.equal(parseVersion("2026.06.07+abc"), "2026.06.07");
  });

  test("empty string → null", () => {
    assert.equal(parseVersion(""), null);
  });
});

// ---------------------------------------------------------------------------
// checkVersion
// ---------------------------------------------------------------------------

describe("checkVersion", () => {
  test("returns {ok:true, version:'2026.07.15'} for a current version", async () => {
    const run = fakeRunner({ code: 0, stdout: "work-plan 2026.07.15+abc", stderr: "" });
    const result = await checkVersion(run);
    assert.equal(result.ok, true);
    assert.equal(result.version, "2026.07.15");
  });

  test("returns {ok:false} for an older version", async () => {
    const run = fakeRunner({ code: 0, stdout: "work-plan 2026.05.30+old", stderr: "" });
    const result = await checkVersion(run);
    assert.equal(result.ok, false);
    assert.equal(result.version, "2026.05.30");
  });

  test("returns {ok:false, version:null} when runner returns code 1", async () => {
    const run = fakeRunner({ code: 1, stdout: "", stderr: "not found" });
    const result = await checkVersion(run);
    assert.equal(result.ok, false);
    assert.equal(result.version, null);
  });

  test("returns {ok:false, version:null} when output is unparseable", async () => {
    const run = fakeRunner({ code: 0, stdout: "work-plan unknown", stderr: "" });
    const result = await checkVersion(run);
    assert.equal(result.ok, false);
    assert.equal(result.version, null);
  });

  test("returns {ok:true} for a version newer than minimum", async () => {
    const run = fakeRunner({ code: 0, stdout: "work-plan 2026.08.01+future", stderr: "" });
    const result = await checkVersion(run);
    assert.equal(result.ok, true);
    assert.equal(result.version, "2026.08.01");
  });

  test("never throws even when runner throws (spawn failure simulation)", async () => {
    const throwingRunner: CliRunner = (_args: string[]) =>
      Promise.reject(new Error("ENOENT: spawn failed"));
    const result = await checkVersion(throwingRunner);
    assert.equal(result.ok, false);
    assert.equal(result.version, null);
  });
});

// ---------------------------------------------------------------------------
// notes-vcs (#103/#224)
// ---------------------------------------------------------------------------

/** A runner that records the args it was called with. */
function capturingRunner(result: CliResult): { run: CliRunner; calls: string[][] } {
  const calls: string[][] = [];
  const run: CliRunner = (args: string[]) => {
    calls.push(args);
    return Promise.resolve(result);
  };
  return { run, calls };
}

const STATUS_JSON = JSON.stringify({
  notes_root: "/home/eve/notes",
  under_git: true,
  is_root: true,
  auto_commit: true,
  last_commit_sha: "ab12cd3",
  last_commit_subject: "ab12cd3 work-plan slot 1 t",
  dirty: false,
});

describe("notesVcsStatus", () => {
  test("parses status --json into a typed object", async () => {
    const { run, calls } = capturingRunner({ code: 0, stdout: STATUS_JSON, stderr: "" });
    const st = await notesVcsStatus(run);
    assert.deepEqual(calls[0], ["notes-vcs", "status", "--json"]);
    assert.equal(st?.is_root, true);
    assert.equal(st?.auto_commit, true);
    assert.equal(st?.last_commit_sha, "ab12cd3");
  });

  test("returns null on non-zero exit (old CLI without the verb)", async () => {
    const run = fakeRunner({ code: 2, stdout: "", stderr: "unknown subcommand" });
    assert.equal(await notesVcsStatus(run), null);
  });

  test("returns null on unparseable stdout", async () => {
    const run = fakeRunner({ code: 0, stdout: "not json", stderr: "" });
    assert.equal(await notesVcsStatus(run), null);
  });

  test("never throws when the runner throws", async () => {
    const throwing: CliRunner = () => Promise.reject(new Error("ENOENT"));
    assert.equal(await notesVcsStatus(throwing), null);
  });

  test("coerces missing fields to safe defaults", async () => {
    const run = fakeRunner({ code: 0, stdout: JSON.stringify({ is_root: false }), stderr: "" });
    const st = await notesVcsStatus(run);
    assert.equal(st?.auto_commit, false);
    assert.equal(st?.last_commit_sha, null);
    assert.equal(st?.under_git, false);
  });
});

describe("notesVcsUndo", () => {
  test("bare undo (HEAD) builds the right argv", async () => {
    const { run, calls } = capturingRunner({ code: 0, stdout: "✓ Reverted HEAD", stderr: "" });
    await notesVcsUndo(run);
    assert.deepEqual(calls[0], ["notes-vcs", "undo"]);
  });

  test("undo with a sha places it after the -- separator", async () => {
    const { run, calls } = capturingRunner({ code: 0, stdout: "✓ Reverted abc", stderr: "" });
    await notesVcsUndo(run, "abc1234");
    assert.deepEqual(calls[0], ["notes-vcs", "undo", "--", "abc1234"]);
  });

  test("throws CliError on non-zero exit", async () => {
    const run = fakeRunner({ code: 1, stdout: "", stderr: "nothing to revert" });
    await assert.rejects(() => notesVcsUndo(run), (e: unknown) => e instanceof CliError);
  });
});

describe("notesVcsRun", () => {
  test("builds [notes-vcs, <action>] and returns stdout", async () => {
    const { run, calls } = capturingRunner({ code: 0, stdout: "✓ auto-commit enabled.", stderr: "" });
    const out = await notesVcsRun(run, "enable");
    assert.deepEqual(calls[0], ["notes-vcs", "enable"]);
    assert.match(out, /enabled/);
  });

  test("throws CliError on non-zero exit", async () => {
    const run = fakeRunner({ code: 1, stdout: "", stderr: "boom" });
    await assert.rejects(() => notesVcsRun(run, "init"), (e: unknown) => e instanceof CliError);
  });
});

// ---------------------------------------------------------------------------
// isAlreadyExistsError — detection lives in the tested pure layer (#290)
// ---------------------------------------------------------------------------

describe("isAlreadyExistsError", () => {
  test("true for a CliError whose STDOUT contains 'already exists'", () => {
    // init-repo prints the error to stdout (print), not stderr.
    const err = new CliError({
      message: "work-plan failed (exit 1): ",
      args: ["init-repo", "--github=org/x", "--", "x"],
      code: 1,
      stdout: "ERROR: repo 'x' already exists in ~/.claude/work-plan/config.yml.\n",
      stderr: "",
    });
    assert.equal(isAlreadyExistsError(err), true);
  });

  test("true when 'already exists' is on stderr instead", () => {
    const err = new CliError({
      message: "failed",
      args: [],
      code: 1,
      stdout: "",
      stderr: "ERROR: repo 'x' already exists",
    });
    assert.equal(isAlreadyExistsError(err), true);
  });

  test("false for a non-CliError", () => {
    assert.equal(isAlreadyExistsError(new Error("repo already exists")), false);
    assert.equal(isAlreadyExistsError("already exists"), false);
    assert.equal(isAlreadyExistsError(undefined), false);
  });

  test("false for an unrelated CliError", () => {
    const err = new CliError({
      message: "work-plan failed (exit 1): notes_root does not exist",
      args: [],
      code: 1,
      stdout: "ERROR: notes_root /x does not exist.\n",
      stderr: "",
    });
    assert.equal(isAlreadyExistsError(err), false);
  });
});

// ---------------------------------------------------------------------------
// normalizeExportIssue (#257)
// ---------------------------------------------------------------------------

describe("normalizeExportIssue", () => {
  test("normalizes missing blocked_by/blocking to [] (older CLI payload)", () => {
    const issue = normalizeExportIssue({ number: 1, title: "x", state: "open",
      assignee: "—", milestone: null, in_progress: false, in_progress_label: false });
    assert.deepStrictEqual(issue.blocked_by, []);
    assert.deepStrictEqual(issue.blocking, []);
  });

  test("preserves provided blocked_by/blocking arrays", () => {
    const dep = { number: 5, repo: "org/repo", title: "dep" };
    const issue = normalizeExportIssue({
      number: 1, title: "x", state: "open",
      assignee: "—", milestone: null, in_progress: false, in_progress_label: false,
      blocked_by: [dep], blocking: [],
    });
    assert.deepStrictEqual(issue.blocked_by, [dep]);
    assert.deepStrictEqual(issue.blocking, []);
  });
});

// ---------------------------------------------------------------------------
// checkAuth (#auth)
// ---------------------------------------------------------------------------

describe("checkAuth", () => {
  function throwingRunner(): CliRunner {
    return () => Promise.reject(new Error("spawn fail"));
  }

  test("authenticated → authenticated:true, ghPresent:true, probeOk:true, user", async () => {
    const run = fakeRunner({
      code: 0,
      stdout: JSON.stringify({ gh_present: true, authenticated: true, user: "eve", error: null }),
      stderr: "",
    });
    assert.deepEqual(await checkAuth(run), { authenticated: true, cliPresent: true, ghPresent: true, probeOk: true, user: "eve", error: null });
  });

  test("gh present but not signed in → authenticated:false, ghPresent:true, probeOk:true", async () => {
    const run = fakeRunner({
      code: 1,
      stdout: JSON.stringify({ gh_present: true, authenticated: false, user: null, error: "x" }),
      stderr: "",
    });
    assert.deepEqual(await checkAuth(run), { authenticated: false, cliPresent: true, ghPresent: true, probeOk: true, user: null, error: null });
  });

  test("gh not installed → ghPresent:false, probeOk:true", async () => {
    const run = fakeRunner({
      code: 2,
      stdout: JSON.stringify({ gh_present: false, authenticated: false, user: null, error: "x" }),
      stderr: "",
    });
    assert.deepEqual(await checkAuth(run), { authenticated: false, cliPresent: true, ghPresent: false, probeOk: true, user: null, error: null });
  });

  test("unparseable output (no stderr) → probeOk:false, error null", async () => {
    const run = fakeRunner({ code: 0, stdout: "not json{{", stderr: "" });
    assert.deepEqual(await checkAuth(run), { authenticated: false, cliPresent: true, ghPresent: true, probeOk: false, user: null, error: null });
  });

  test("unparseable output WITH a launcher error → probeOk:false, error carries the reason", async () => {
    // The exact shape when an older launcher gates the auth probe behind a
    // missing yq: empty stdout, the missing-tool message on stderr, exit 1. This
    // is a CLI dependency problem, NOT "not signed in" — the reason must survive
    // so the caller can name it instead of looping the user through sign-in.
    const run = fakeRunner({
      code: 1,
      stdout: "",
      stderr: "work-plan: missing required tool(s) on PATH: yq\n  yq — YAML config/frontmatter\n",
    });
    assert.deepEqual(await checkAuth(run), {
      authenticated: false, cliPresent: true, ghPresent: true, probeOk: false, user: null,
      error: "work-plan: missing required tool(s) on PATH: yq",
    });
  });

  test("never throws on spawn failure → probeOk:false (transient), error carries message", async () => {
    assert.deepEqual(await checkAuth(throwingRunner()), {
      authenticated: false, cliPresent: true, ghPresent: true, probeOk: false, user: null, error: "spawn fail",
    });
  });

  test("CLI not found (ENOENT) → cliPresent:false, probeOk:false (#402, NOT a sign-in problem)", async () => {
    // The work-plan binary isn't on PATH — makeSpawnRunner rejects with a
    // CliError{notFound:true}. This must read as a missing CLI, not "not signed
    // in to GitHub" (the bug that confused the Remote-WSL user in #402).
    const run: CliRunner = () =>
      Promise.reject(new CliError({
        message: 'work-plan CLI not found at "work-plan"',
        args: ["auth-status", "--json"], code: -1, stdout: "", stderr: "ENOENT", notFound: true,
      }));
    assert.deepEqual(await checkAuth(run), {
      authenticated: false, cliPresent: false, ghPresent: false, probeOk: false, user: null, error: null,
    });
  });
});

// ---------------------------------------------------------------------------
// suggestNextUp (#274) — read-only auto-next feed
// ---------------------------------------------------------------------------

const VALID_SUGGESTION = {
  track: "api-core",
  repo: "your-org/myproject",
  current: [],
  suggested: [
    { number: 142, title: "Add SSO", priority: "P1", milestone: "v0.6" },
    { number: 87, title: "Fix auth", priority: "P2", milestone: "" },
  ],
  skipped: [{ number: 99, claimed_by: "billing" }],
};

describe("suggestNextUp", () => {
  test("parses a canned response into NextUpSuggestion", async () => {
    const run = fakeRunner({ code: 0, stdout: JSON.stringify(VALID_SUGGESTION), stderr: "" });
    const result = await suggestNextUp(run, "api-core");
    assert.equal(result.track, "api-core");
    assert.equal(result.suggested.length, 2);
    assert.equal(result.suggested[0].number, 142);
    assert.equal(result.skipped[0].claimed_by, "billing");
  });

  test("builds args: handoff --suggest-next, track after -- (no repo)", async () => {
    const { run, calls } = recordingRunner({ code: 0, stdout: JSON.stringify(VALID_SUGGESTION), stderr: "" });
    await suggestNextUp(run, "api-core");
    assert.deepEqual(calls[0], ["handoff", "--suggest-next", "--", "api-core"]);
  });

  test("includes --repo=<key> before -- when given", async () => {
    const { run, calls } = recordingRunner({ code: 0, stdout: JSON.stringify(VALID_SUGGESTION), stderr: "" });
    await suggestNextUp(run, "api-core", "myrepo");
    assert.deepEqual(calls[0], ["handoff", "--suggest-next", "--repo=myrepo", "--", "api-core"]);
  });

  test("nonzero exit throws CliError", async () => {
    const run = fakeRunner({ code: 1, stdout: "", stderr: "boom" });
    await assert.rejects(() => suggestNextUp(run, "api-core"), CliError);
  });

  test("unparseable stdout throws CliError", async () => {
    const run = fakeRunner({ code: 0, stdout: "not-json{{", stderr: "" });
    await assert.rejects(() => suggestNextUp(run, "api-core"), CliError);
  });
});

// ---------------------------------------------------------------------------
// doctorScan (#439)
// ---------------------------------------------------------------------------

describe("doctorScan", () => {
  const SAMPLE_FINDING = {
    type: "github_rename_detected", key: "foo", folder: null, track: null,
    message: "renamed", fixable: true, unverified: false,
    old: "org/old", new: "org/new",
  };

  test("returns findings on a clean 0-exit JSON result", async () => {
    const run = fakeRunner({
      code: 0,
      stdout: JSON.stringify({ attempts: [], findings: [SAMPLE_FINDING] }),
      stderr: "",
    });
    const result = await doctorScan(run);
    assert.deepEqual(result, [SAMPLE_FINDING]);
  });

  test("uses exact argv [\"doctor\", \"--json\"]", async () => {
    const calls: string[][] = [];
    const run: CliRunner = (args: string[]) => {
      calls.push(args);
      return Promise.resolve({ code: 0, stdout: JSON.stringify({ attempts: [], findings: [] }), stderr: "" });
    };
    await doctorScan(run);
    assert.deepEqual(calls[0], ["doctor", "--json"]);
  });

  test("nonzero exit returns null", async () => {
    const run = fakeRunner({ code: 1, stdout: "", stderr: "unknown subcommand" });
    assert.equal(await doctorScan(run), null);
  });

  test("spawn rejection returns null", async () => {
    const run: CliRunner = () => Promise.reject(new Error("ENOENT"));
    assert.equal(await doctorScan(run), null);
  });

  test("malformed JSON returns null", async () => {
    const run = fakeRunner({ code: 0, stdout: "not json{{", stderr: "" });
    assert.equal(await doctorScan(run), null);
  });

  test("valid JSON, findings missing, returns null", async () => {
    const run = fakeRunner({ code: 0, stdout: JSON.stringify({ attempts: [] }), stderr: "" });
    assert.equal(await doctorScan(run), null);
  });

  test("valid JSON, findings not an array, returns null", async () => {
    const run = fakeRunner({ code: 0, stdout: JSON.stringify({ attempts: [], findings: "nope" }), stderr: "" });
    assert.equal(await doctorScan(run), null);
  });

  test("a fatal key present returns null, never treated as clean", async () => {
    const run = fakeRunner({
      code: 0,
      stdout: JSON.stringify({ fatal: "config could not be loaded", attempts: [], findings: [] }),
      stderr: "",
    });
    assert.equal(await doctorScan(run), null);
  });
});
