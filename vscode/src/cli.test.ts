import { test, describe } from "node:test";
import assert from "node:assert/strict";
import type { CliResult, CliRunner } from "./cli.ts";
import {
  CliError,
  exportJson,
  runWrite,
  parseVersion,
  meetsMinVersion,
  checkVersion,
  MIN_CLI_VERSION,
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
      repo: "stylusnexus/CritForge",
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
  test("returns {ok:true, version:'2026.06.07'} for a current version", async () => {
    const run = fakeRunner({ code: 0, stdout: "work-plan 2026.06.07+abc", stderr: "" });
    const result = await checkVersion(run);
    assert.equal(result.ok, true);
    assert.equal(result.version, "2026.06.07");
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
    const run = fakeRunner({ code: 0, stdout: "work-plan 2026.07.01+future", stderr: "" });
    const result = await checkVersion(run);
    assert.equal(result.ok, true);
    assert.equal(result.version, "2026.07.01");
  });

  test("never throws even when runner throws (spawn failure simulation)", async () => {
    const throwingRunner: CliRunner = (_args: string[]) =>
      Promise.reject(new Error("ENOENT: spawn failed"));
    const result = await checkVersion(throwingRunner);
    assert.equal(result.ok, false);
    assert.equal(result.version, null);
  });
});
