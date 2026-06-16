import { test, describe } from "node:test";
import assert from "node:assert/strict";
import type { CliResult, CliRunner, CliRunOpts } from "./cli.ts";
import { whichRepo } from "./cli.ts";
import { lensShouldApply, pickAutoFocusSlug } from "./autofocus.ts";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** A runner that returns a canned which-repo payload per cwd, recording every
 *  call's args + cwd. An unmapped cwd yields `{"key": null}` (no match). */
function cwdRunner(
  byCwd: Record<string, Partial<{ key: string | null; github: string | null }>>,
): { run: CliRunner; calls: { args: string[]; cwd?: string }[] } {
  const calls: { args: string[]; cwd?: string }[] = [];
  const run: CliRunner = (args: string[], opts?: CliRunOpts) => {
    calls.push({ args, cwd: opts?.cwd });
    const blob = byCwd[opts?.cwd ?? ""];
    const stdout = blob === undefined ? JSON.stringify({ key: null }) : JSON.stringify(blob);
    return Promise.resolve({ code: 0, stdout, stderr: "" } as CliResult);
  };
  return { run, calls };
}

function fixedRunner(result: CliResult): CliRunner {
  return (_args: string[], _opts?: CliRunOpts) => Promise.resolve(result);
}

const WPT = { key: "work-plan-toolkit", github: "stylusnexus/work-plan-toolkit" };

// ---------------------------------------------------------------------------
// lensShouldApply — the override decision
// ---------------------------------------------------------------------------

describe("lensShouldApply", () => {
  test("auto applies over a prior auto", () => {
    assert.equal(lensShouldApply("auto", "auto"), true);
  });
  test("user always applies (over auto)", () => {
    assert.equal(lensShouldApply("auto", "user"), true);
  });
  test("user applies over a prior user", () => {
    assert.equal(lensShouldApply("user", "user"), true);
  });
  test("auto does NOT override a user choice", () => {
    assert.equal(lensShouldApply("user", "auto"), false);
  });
});

// ---------------------------------------------------------------------------
// whichRepo — parsing + cwd plumbing + never-throw
// ---------------------------------------------------------------------------

describe("whichRepo", () => {
  test("parses {key, github} on a match", async () => {
    const { run } = cwdRunner({ "/code/wpt": WPT });
    assert.deepEqual(await whichRepo(run, "/code/wpt"), {
      key: "work-plan-toolkit",
      github: "stylusnexus/work-plan-toolkit",
    });
  });

  test("runs `which-repo --json` with cwd set to the given dir", async () => {
    const { run, calls } = cwdRunner({ "/code/wpt": WPT });
    await whichRepo(run, "/code/wpt");
    assert.deepEqual(calls[0].args, ["which-repo", "--json"]);
    assert.equal(calls[0].cwd, "/code/wpt");
  });

  test("key:null → null (no match)", async () => {
    const { run } = cwdRunner({});
    assert.equal(await whichRepo(run, "/tmp/elsewhere"), null);
  });

  test("github:null is preserved (slug-less repo)", async () => {
    const { run } = cwdRunner({ "/code/x": { key: "x", github: null } });
    assert.deepEqual(await whichRepo(run, "/code/x"), { key: "x", github: null });
  });

  test("unparseable stdout → null, no throw", async () => {
    const run = fixedRunner({ code: 0, stdout: "not json{{", stderr: "" });
    assert.equal(await whichRepo(run, "/code/x"), null);
  });
});

// ---------------------------------------------------------------------------
// pickAutoFocusSlug — multi-folder selection
// ---------------------------------------------------------------------------

describe("pickAutoFocusSlug", () => {
  test("returns the github slug of the matched folder", async () => {
    const { run } = cwdRunner({ "/code/wpt": WPT });
    assert.equal(
      await pickAutoFocusSlug(run, ["/code/wpt"]),
      "stylusnexus/work-plan-toolkit",
    );
  });

  test("multi-root: first slug-yielding folder wins", async () => {
    const { run } = cwdRunner({
      "/code/wpt": WPT,
      "/code/ds": { key: "defect-scan", github: "stylusnexus/defect-scan" },
    });
    // wpt is listed first → its slug is chosen even though ds also matches.
    assert.equal(
      await pickAutoFocusSlug(run, ["/code/wpt", "/code/ds"]),
      "stylusnexus/work-plan-toolkit",
    );
  });

  test("skips a github-null match and takes the next folder's slug", async () => {
    const { run } = cwdRunner({
      "/code/slugless": { key: "slugless", github: null },
      "/code/ds": { key: "defect-scan", github: "stylusnexus/defect-scan" },
    });
    assert.equal(
      await pickAutoFocusSlug(run, ["/code/slugless", "/code/ds"]),
      "stylusnexus/defect-scan",
    );
  });

  test("no folder matches → null", async () => {
    const { run } = cwdRunner({});
    assert.equal(await pickAutoFocusSlug(run, ["/tmp/a", "/tmp/b"]), null);
  });

  test("all matches are slug-less → null", async () => {
    const { run } = cwdRunner({ "/code/x": { key: "x", github: null } });
    assert.equal(await pickAutoFocusSlug(run, ["/code/x"]), null);
  });

  test("probes each folder with its own cwd", async () => {
    const { run, calls } = cwdRunner({});
    await pickAutoFocusSlug(run, ["/a", "/b"]);
    assert.deepEqual(calls.map(c => c.cwd), ["/a", "/b"]);
  });
});
