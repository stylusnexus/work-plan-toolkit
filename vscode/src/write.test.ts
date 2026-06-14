import { test, describe } from "node:test";
import assert from "node:assert/strict";
import type { CliResult, CliRunner } from "./cli.ts";
import { CliError } from "./cli.ts";
import {
  actionToArgs,
  executeWrite,
} from "./write.ts";
import type { WriteAction, ConfirmDecision, ConfirmPrompt } from "./write.ts";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Builds a recording fake CliRunner that returns canned results in sequence.
 * Captures every args array it's called with so tests can assert call count
 * and exact arguments.
 */
function recordingRunner(
  results: CliResult[]
): { run: CliRunner; calls: string[][] } {
  const calls: string[][] = [];
  let index = 0;
  const run: CliRunner = (args: string[]) => {
    calls.push([...args]);
    const result = results[index++];
    if (result === undefined) {
      return Promise.reject(new Error("recordingRunner: no more canned results"));
    }
    return Promise.resolve(result);
  };
  return { run, calls };
}

/** A confirm prompt that always returns the given decision. */
function alwaysConfirm(decision: ConfirmDecision): ConfirmPrompt {
  return (_reason: string) => Promise.resolve(decision);
}

/** A confirm prompt that throws if called (proves it was never consulted). */
function neverConfirm(): ConfirmPrompt {
  return (_reason: string) => {
    throw new Error("confirm prompt should not have been called");
  };
}

/** A recording confirm prompt that captures the reason string it received. */
function recordingConfirm(
  decision: ConfirmDecision
): { prompt: ConfirmPrompt; reasons: string[] } {
  const reasons: string[] = [];
  const prompt: ConfirmPrompt = (reason: string) => {
    reasons.push(reason);
    return Promise.resolve(decision);
  };
  return { prompt, reasons };
}

// ---------------------------------------------------------------------------
// actionToArgs
// ---------------------------------------------------------------------------

describe("actionToArgs", () => {
  test("editFields with one field → ['set', 'status=parked', '--', track]", () => {
    const action: WriteAction = {
      kind: "editFields",
      track: "platform-health",
      fields: { status: "parked" },
    };
    assert.deepEqual(actionToArgs(action), ["set", "status=parked", "--", "platform-health"]);
  });

  test("editFields with empty fields {} → ['set', '--', track] (no key=value pairs)", () => {
    const action: WriteAction = {
      kind: "editFields",
      track: "platform-health",
      fields: {},
    };
    assert.deepEqual(actionToArgs(action), ["set", "--", "platform-health"]);
  });

  test("editFields with multiple fields → each key=value before '--', track after", () => {
    const action: WriteAction = {
      kind: "editFields",
      track: "ph",
      fields: { status: "shipped", tier: "P1", milestone: "v2" },
    };
    const result = actionToArgs(action);
    assert.deepEqual(result, ["set", "status=shipped", "tier=P1", "milestone=v2", "--", "ph"]);
  });

  test("setNext with [4167, 4148] → ['handoff', '--set-next=4167,4148', '--', track]", () => {
    const action: WriteAction = {
      kind: "setNext",
      track: "platform-health",
      issues: [4167, 4148],
    };
    assert.deepEqual(actionToArgs(action), [
      "handoff",
      "--set-next=4167,4148",
      "--",
      "platform-health",
    ]);
  });

  test("setNext with a single issue → '--set-next=42' (no trailing comma)", () => {
    const action: WriteAction = {
      kind: "setNext",
      track: "ph",
      issues: [42],
    };
    assert.deepEqual(actionToArgs(action), ["handoff", "--set-next=42", "--", "ph"]);
  });

  test("refresh → ['refresh-md', '--yes', '--', track]", () => {
    const action: WriteAction = { kind: "refresh", track: "platform-health" };
    assert.deepEqual(actionToArgs(action), ["refresh-md", "--yes", "--", "platform-health"]);
  });

  test("reconcileDraft → ['reconcile', '--draft', '--', track]", () => {
    const action: WriteAction = { kind: "reconcileDraft", track: "platform-health" };
    assert.deepEqual(actionToArgs(action), ["reconcile", "--draft", "--", "platform-health"]);
  });

  test("hygiene → ['hygiene', '--yes'] (no positionals, no separator)", () => {
    const action: WriteAction = { kind: "hygiene" };
    assert.deepEqual(actionToArgs(action), ["hygiene", "--yes"]);
  });

  test("slot → ['slot', '--no-move', '--', issue, track]", () => {
    const action: WriteAction = { kind: "slot", issue: 4234, track: "tabletop" };
    assert.deepEqual(actionToArgs(action), ["slot", "--no-move", "--", "4234", "tabletop"]);
  });

  test("close without note → ['close', '--state=shipped', '--', track]", () => {
    const action: WriteAction = { kind: "close", track: "ph", state: "shipped" };
    assert.deepEqual(actionToArgs(action), ["close", "--state=shipped", "--", "ph"]);
  });

  test("close with note → includes '--note=wrapped up' before '--' in equals form", () => {
    const action: WriteAction = { kind: "close", track: "ph", state: "shipped", note: "wrapped up" };
    assert.deepEqual(actionToArgs(action), ["close", "--state=shipped", "--note=wrapped up", "--", "ph"]);
  });

  test("close with state 'parked' → '--state=parked'", () => {
    const action: WriteAction = { kind: "close", track: "ph", state: "parked" };
    assert.deepEqual(actionToArgs(action), ["close", "--state=parked", "--", "ph"]);
  });

  test("close with state 'abandoned' → '--state=abandoned'", () => {
    const action: WriteAction = { kind: "close", track: "ph", state: "abandoned" };
    assert.deepEqual(actionToArgs(action), ["close", "--state=abandoned", "--", "ph"]);
  });

  test("newTrack without optional flags → ['new-track', '--', repo, slug]", () => {
    const action: WriteAction = {
      kind: "newTrack",
      repo: "stylusnexus/work-plan-toolkit",
      slug: "my-feature",
    };
    assert.deepEqual(actionToArgs(action), [
      "new-track",
      "--",
      "stylusnexus/work-plan-toolkit",
      "my-feature",
    ]);
  });

  test("newTrack with priority and milestone → flags before '--', repo+slug after", () => {
    const action: WriteAction = {
      kind: "newTrack",
      repo: "stylusnexus/work-plan-toolkit",
      slug: "my-feature",
      priority: "P1",
      milestone: "v2",
    };
    const result = actionToArgs(action);
    assert.deepEqual(result, [
      "new-track",
      "--priority=P1",
      "--milestone=v2",
      "--",
      "stylusnexus/work-plan-toolkit",
      "my-feature",
    ]);
  });

  test("newTrack with only priority omits milestone", () => {
    const action: WriteAction = {
      kind: "newTrack",
      repo: "stylusnexus/work-plan-toolkit",
      slug: "my-feature",
      priority: "P0",
    };
    assert.deepEqual(actionToArgs(action), [
      "new-track",
      "--priority=P0",
      "--",
      "stylusnexus/work-plan-toolkit",
      "my-feature",
    ]);
  });

  test("newTrack with only milestone omits priority", () => {
    const action: WriteAction = {
      kind: "newTrack",
      repo: "stylusnexus/work-plan-toolkit",
      slug: "my-feature",
      milestone: "v3",
    };
    assert.deepEqual(actionToArgs(action), [
      "new-track",
      "--milestone=v3",
      "--",
      "stylusnexus/work-plan-toolkit",
      "my-feature",
    ]);
  });

  test("renameTrack → ['rename-track', '--', track, newSlug]", () => {
    const action: WriteAction = {
      kind: "renameTrack",
      track: "old-project-name",
      newSlug: "new-project-name",
    };
    assert.deepEqual(actionToArgs(action), [
      "rename-track",
      "--",
      "old-project-name",
      "new-project-name",
    ]);
  });

  test("renameTrack with a '--'-prefixed track name → both positionals after '--'", () => {
    const action: WriteAction = {
      kind: "renameTrack",
      track: "--confirm=evil",
      newSlug: "safe-slug",
    };
    const args = actionToArgs(action);
    const sepIdx = args.indexOf("--");
    assert.deepEqual(args.slice(sepIdx + 1), ["--confirm=evil", "safe-slug"]);
  });

  test("addRepo without local → ['init-repo', '--github=org/myrepo', '--', key]", () => {
    const action: WriteAction = {
      kind: "addRepo",
      key: "myrepo",
      github: "org/myrepo",
    };
    assert.deepEqual(actionToArgs(action), ["init-repo", "--github=org/myrepo", "--", "myrepo"]);
  });

  test("addRepo with local → includes '--local=/path/to/repo' before '--' in equals form", () => {
    const action: WriteAction = {
      kind: "addRepo",
      key: "myrepo",
      github: "org/myrepo",
      local: "/path/to/repo",
    };
    assert.deepEqual(actionToArgs(action), [
      "init-repo",
      "--github=org/myrepo",
      "--local=/path/to/repo",
      "--",
      "myrepo",
    ]);
  });

  test("addRepo with update → appends '--update' before '--'", () => {
    const action: WriteAction = {
      kind: "addRepo",
      key: "myrepo",
      github: "org/myrepo",
      local: "/path/to/repo",
      update: true,
    };
    assert.deepEqual(actionToArgs(action), [
      "init-repo",
      "--github=org/myrepo",
      "--local=/path/to/repo",
      "--update",
      "--",
      "myrepo",
    ]);
  });

  test("addRepo with clearLocal → forces '--update --clear-local', drops --local", () => {
    const action: WriteAction = {
      kind: "addRepo",
      key: "myrepo",
      github: "org/myrepo",
      update: true,
      clearLocal: true,
    };
    assert.deepEqual(actionToArgs(action), [
      "init-repo",
      "--github=org/myrepo",
      "--update",
      "--clear-local",
      "--",
      "myrepo",
    ]);
  });

  test("addRepo clearLocal implies --update even when update is unset", () => {
    const action: WriteAction = {
      kind: "addRepo",
      key: "myrepo",
      github: "org/myrepo",
      clearLocal: true,
    };
    assert.deepEqual(actionToArgs(action), [
      "init-repo",
      "--github=org/myrepo",
      "--update",
      "--clear-local",
      "--",
      "myrepo",
    ]);
  });

  test("removeRepo → ['remove-repo', '--', key]", () => {
    const action: WriteAction = { kind: "removeRepo", key: "myrepo" };
    assert.deepEqual(actionToArgs(action), ["remove-repo", "--", "myrepo"]);
  });

  test("setNotesRoot → ['set-notes-root', '--', path]", () => {
    const action: WriteAction = {
      kind: "setNotesRoot",
      path: "/Users/eve/notes",
    };
    assert.deepEqual(actionToArgs(action), ["set-notes-root", "--", "/Users/eve/notes"]);
  });

  test("move → ['move', '--', issue, fromTrack, toTrack]", () => {
    const action: WriteAction = {
      kind: "move",
      issue: 4234,
      fromTrack: "platform-health",
      toTrack: "org-sharing",
    };
    assert.deepEqual(
      actionToArgs(action),
      ["move", "--", "4234", "platform-health", "org-sharing"],
    );
  });

  test("handoff → ['handoff', '--', track]", () => {
    const action: WriteAction = { kind: "handoff", track: "platform-health" };
    assert.deepEqual(actionToArgs(action), ["handoff", "--", "platform-health"]);
  });

  test("handoff with a '--'-prefixed track name → track stays a positional after '--'", () => {
    const action: WriteAction = { kind: "handoff", track: "--auto-next" };
    const args = actionToArgs(action);
    const sepIdx = args.indexOf("--");
    assert.deepEqual(args.slice(sepIdx + 1), ["--auto-next"]);
  });

  test("batchSlot → ['batch-slot', '--no-move', '--', ...issues, track]", () => {
    const action: WriteAction = {
      kind: "batchSlot",
      issues: [11, 22, 33],
      track: "tabletop",
    };
    assert.deepEqual(actionToArgs(action), [
      "batch-slot",
      "--no-move",
      "--",
      "11",
      "22",
      "33",
      "tabletop",
    ]);
  });

  // #194: a dash-led track name must survive as a positional, never a flag.
  test("editFields with a '--'-prefixed track name → track lands after '--' separator", () => {
    const action: WriteAction = {
      kind: "editFields",
      track: "--confirm=evil-token",
      fields: { status: "parked" },
    };
    const args = actionToArgs(action);
    const sepIdx = args.indexOf("--");
    assert.ok(sepIdx !== -1, "must contain a '--' end-of-options separator");
    // The hostile track name appears only AFTER the separator.
    assert.equal(args[sepIdx + 1], "--confirm=evil-token");
    assert.ok(
      args.slice(0, sepIdx).every((a) => a !== "--confirm=evil-token"),
      "dash-led track name must not appear before the separator",
    );
  });

  test("move with a '--repo'-named source track → all positionals after '--'", () => {
    const action: WriteAction = {
      kind: "move",
      issue: 7,
      fromTrack: "--repo",
      toTrack: "safe-track",
    };
    const args = actionToArgs(action);
    const sepIdx = args.indexOf("--");
    assert.deepEqual(args.slice(sepIdx + 1), ["7", "--repo", "safe-track"]);
  });
});

// ---------------------------------------------------------------------------
// executeWrite — non-confirm path
// ---------------------------------------------------------------------------

describe("executeWrite — non-confirm path", () => {
  test("human success line → exactly ONE runWrite call; outcome {status:'written', stdout}", async () => {
    const successResult: CliResult = {
      code: 0,
      stdout: "✓ set status on ph",
      stderr: "",
    };
    const action: WriteAction = {
      kind: "editFields",
      track: "ph",
      fields: { status: "parked" },
    };
    const { run, calls } = recordingRunner([successResult]);

    const outcome = await executeWrite(run, action, neverConfirm());

    assert.equal(calls.length, 1, "should invoke runWrite exactly once");
    assert.deepEqual(outcome, { status: "written", stdout: "✓ set status on ph" });
  });

  test("non-JSON success stdout is returned verbatim in {status:'written'}", async () => {
    const action: WriteAction = { kind: "hygiene" };
    const { run } = recordingRunner([{ code: 0, stdout: "✓ hygiene done", stderr: "" }]);

    const outcome = await executeWrite(run, action, neverConfirm());

    assert.deepEqual(outcome, { status: "written", stdout: "✓ hygiene done" });
  });

  test("confirm prompt is never called when needs_confirm is absent", async () => {
    const action: WriteAction = { kind: "refresh", track: "ph" };
    const { run } = recordingRunner([{ code: 0, stdout: "refreshed", stderr: "" }]);

    // neverConfirm throws if called — no assertion needed beyond no-throw.
    await assert.doesNotReject(() => executeWrite(run, action, neverConfirm()));
  });
});

// ---------------------------------------------------------------------------
// executeWrite — needs_confirm → writeAnyway
// ---------------------------------------------------------------------------

describe("executeWrite — needs_confirm → writeAnyway", () => {
  const TOKEN = "abc1234567890def";
  const REASON = "platform-health is PUBLIC (or visibility unknown); edit will be written there.";

  const needsConfirmResult: CliResult = {
    code: 0,
    stdout: JSON.stringify({
      needs_confirm: true,
      reason: REASON,
      token: TOKEN,
    }),
    stderr: "",
  };
  const successResult: CliResult = {
    code: 0,
    stdout: "✓ set status on ph",
    stderr: "",
  };

  test("TWO runWrite calls; second call carries --confirm=<token> as a flag (before '--')", async () => {
    const action: WriteAction = {
      kind: "editFields",
      track: "ph",
      fields: { status: "shipped" },
    };
    const { run, calls } = recordingRunner([needsConfirmResult, successResult]);

    await executeWrite(run, action, alwaysConfirm("writeAnyway"));

    assert.equal(calls.length, 2, "should invoke runWrite exactly twice");

    const secondArgs = calls[1];

    // The token must be present in equals form.
    assert.ok(
      secondArgs.includes(`--confirm=${TOKEN}`),
      "confirm arg must use equals form"
    );

    // It MUST sit before the '--' separator so a strict parser reads it as a flag.
    const sepIdx = secondArgs.indexOf("--");
    const confirmIdx = secondArgs.indexOf(`--confirm=${TOKEN}`);
    assert.ok(sepIdx !== -1, "args must still contain the '--' separator");
    assert.ok(confirmIdx < sepIdx, "confirm flag must precede the '--' separator");

    // There must be no separate '--confirm' flag (space-separated) anywhere.
    assert.ok(
      !secondArgs.includes("--confirm"),
      "must not have a bare '--confirm' (space-separated form)"
    );
  });

  test("second call = original args with --confirm=<token> spliced in before '--'", async () => {
    const action: WriteAction = {
      kind: "editFields",
      track: "ph",
      fields: { status: "shipped" },
    };
    const { run, calls } = recordingRunner([needsConfirmResult, successResult]);

    await executeWrite(run, action, alwaysConfirm("writeAnyway"));

    const firstArgs = calls[0];
    const secondArgs = calls[1];

    // Exactly one element longer than the original.
    assert.equal(secondArgs.length, firstArgs.length + 1);
    // editFields → ["set", "status=shipped", "--confirm=<token>", "--", "ph"]
    assert.deepEqual(secondArgs, ["set", "status=shipped", `--confirm=${TOKEN}`, "--", "ph"]);
  });

  test("outcome is {status:'written', stdout} from the second call", async () => {
    const action: WriteAction = {
      kind: "editFields",
      track: "ph",
      fields: { status: "shipped" },
    };
    const { run } = recordingRunner([needsConfirmResult, successResult]);

    const outcome = await executeWrite(run, action, alwaysConfirm("writeAnyway"));

    assert.deepEqual(outcome, { status: "written", stdout: "✓ set status on ph" });
  });

  test("token used verbatim: deadbeefdeadbeef → --confirm=deadbeefdeadbeef", async () => {
    const specificToken = "deadbeefdeadbeef";
    const action: WriteAction = {
      kind: "editFields",
      track: "ph",
      fields: { status: "parked" },
    };
    const { run, calls } = recordingRunner([
      {
        code: 0,
        stdout: JSON.stringify({ needs_confirm: true, reason: "PUBLIC", token: specificToken }),
        stderr: "",
      },
      { code: 0, stdout: "✓ done", stderr: "" },
    ]);

    await executeWrite(run, action, alwaysConfirm("writeAnyway"));

    const secondArgs = calls[1];
    assert.ok(
      secondArgs.includes(`--confirm=${specificToken}`),
      `second call must include '--confirm=${specificToken}'`
    );
  });

  test("reason string from JSON is passed to the confirm prompt", async () => {
    const action: WriteAction = {
      kind: "editFields",
      track: "ph",
      fields: { status: "shipped" },
    };
    const { run } = recordingRunner([needsConfirmResult, successResult]);
    const { prompt, reasons } = recordingConfirm("writeAnyway");

    await executeWrite(run, action, prompt);

    assert.equal(reasons.length, 1, "confirm prompt called exactly once");
    assert.equal(reasons[0], REASON);
  });
});

// ---------------------------------------------------------------------------
// executeWrite — needs_confirm → cancel
// ---------------------------------------------------------------------------

describe("executeWrite — needs_confirm → cancel", () => {
  const needsConfirmResult: CliResult = {
    code: 0,
    stdout: JSON.stringify({
      needs_confirm: true,
      reason: "PUBLIC repo",
      token: "sometoken123",
    }),
    stderr: "",
  };

  test("cancel → exactly ONE runWrite call (no second invocation)", async () => {
    const action: WriteAction = {
      kind: "editFields",
      track: "ph",
      fields: { status: "parked" },
    };
    const { run, calls } = recordingRunner([needsConfirmResult]);

    await executeWrite(run, action, alwaysConfirm("cancel"));

    assert.equal(calls.length, 1, "should NOT make a second runWrite call on cancel");
  });

  test("cancel → outcome {status:'cancelled'}", async () => {
    const action: WriteAction = {
      kind: "editFields",
      track: "ph",
      fields: { status: "parked" },
    };
    const { run } = recordingRunner([needsConfirmResult]);

    const outcome = await executeWrite(run, action, alwaysConfirm("cancel"));

    assert.deepEqual(outcome, { status: "cancelled" });
  });
});

// ---------------------------------------------------------------------------
// executeWrite — missing/fallback reason and token
// ---------------------------------------------------------------------------

describe("executeWrite — defensive reason/token fallbacks", () => {
  test("missing reason falls back to default message", async () => {
    const action: WriteAction = { kind: "editFields", track: "ph", fields: { status: "parked" } };
    const { run } = recordingRunner([
      {
        code: 0,
        stdout: JSON.stringify({ needs_confirm: true, token: "tok123" }),
        stderr: "",
      },
      { code: 0, stdout: "✓ done", stderr: "" },
    ]);
    const { prompt, reasons } = recordingConfirm("writeAnyway");

    await executeWrite(run, action, prompt);

    assert.equal(reasons[0], "This write targets a public repo.");
  });

  test("missing token falls back to empty string → --confirm=", async () => {
    const action: WriteAction = { kind: "editFields", track: "ph", fields: { status: "parked" } };
    const { run, calls } = recordingRunner([
      {
        code: 0,
        stdout: JSON.stringify({ needs_confirm: true, reason: "PUBLIC" }),
        stderr: "",
      },
      { code: 0, stdout: "✓ done", stderr: "" },
    ]);

    await executeWrite(run, action, alwaysConfirm("writeAnyway"));

    const secondArgs = calls[1];
    assert.ok(
      secondArgs.includes("--confirm="),
      "should still append --confirm= even with empty token"
    );
  });
});

// ---------------------------------------------------------------------------
// executeWrite — confirm flow for new verbs (slot/close/newTrack inherit it)
// ---------------------------------------------------------------------------

describe("executeWrite — new verbs inherit the confirm-token flow", () => {
  const TOKEN = "abc123def456";
  const REASON = "tabletop is PUBLIC (or visibility unknown); edit will be written there.";

  const needsConfirmResult: CliResult = {
    code: 0,
    stdout: JSON.stringify({
      needs_confirm: true,
      reason: REASON,
      token: TOKEN,
    }),
    stderr: "",
  };
  const successResult: CliResult = {
    code: 0,
    stdout: "✓ closed ph",
    stderr: "",
  };

  test("close: needs_confirm → writeAnyway → second call has close args + --confirm=<token>", async () => {
    const action: WriteAction = {
      kind: "close",
      track: "ph",
      state: "shipped",
    };
    const { run, calls } = recordingRunner([needsConfirmResult, successResult]);

    const outcome = await executeWrite(run, action, alwaysConfirm("writeAnyway"));

    assert.equal(calls.length, 2, "should invoke runWrite exactly twice");

    // First call: close args without confirm (positional after '--')
    assert.deepEqual(calls[0], ["close", "--state=shipped", "--", "ph"]);

    // Second call: --confirm spliced in before '--' so it parses as a flag.
    assert.deepEqual(calls[1], ["close", "--state=shipped", `--confirm=${TOKEN}`, "--", "ph"]);

    // Outcome is from second call
    assert.deepEqual(outcome, { status: "written", stdout: "✓ closed ph" });
  });

  test("close: needs_confirm → cancel → exactly ONE runWrite call, outcome cancelled", async () => {
    const action: WriteAction = {
      kind: "close",
      track: "ph",
      state: "parked",
    };
    const { run, calls } = recordingRunner([needsConfirmResult]);

    const outcome = await executeWrite(run, action, alwaysConfirm("cancel"));

    assert.equal(calls.length, 1, "should NOT make a second runWrite call on cancel");
    assert.deepEqual(outcome, { status: "cancelled" });
  });
});

// ---------------------------------------------------------------------------
// executeWrite — CliError propagation
// ---------------------------------------------------------------------------

describe("executeWrite — CliError propagation", () => {
  test("CliError from first runWrite call propagates out of executeWrite", async () => {
    const action: WriteAction = { kind: "editFields", track: "ph", fields: { status: "parked" } };
    const errorRunner: CliRunner = (_args: string[]) =>
      Promise.resolve({ code: 1, stdout: "", stderr: "track not found" });

    await assert.rejects(
      () => executeWrite(errorRunner, action, neverConfirm()),
      (err: unknown) => {
        assert.ok(err instanceof CliError, "should be a CliError");
        assert.equal((err as CliError).code, 1);
        return true;
      }
    );
  });

  test("CliError from second runWrite call (after writeAnyway) propagates", async () => {
    const action: WriteAction = { kind: "editFields", track: "ph", fields: { status: "parked" } };
    const { run } = recordingRunner([
      {
        code: 0,
        stdout: JSON.stringify({ needs_confirm: true, reason: "PUBLIC", token: "tok" }),
        stderr: "",
      },
      { code: 2, stdout: "", stderr: "server error" },
    ]);

    await assert.rejects(
      () => executeWrite(run, action, alwaysConfirm("writeAnyway")),
      (err: unknown) => {
        assert.ok(err instanceof CliError, "should be a CliError");
        assert.equal((err as CliError).code, 2);
        return true;
      }
    );
  });
});

// ---------------------------------------------------------------------------
// planConfirm / planConfirmClear — verdict-override frontmatter writes (#286)
// ---------------------------------------------------------------------------

describe("actionToArgs — planConfirm", () => {
  test("set verdict → plan-confirm --repo --verdict, rel after --", () => {
    const action: WriteAction = {
      kind: "planConfirm",
      repoKey: "critforge",
      rel: "docs/superpowers/plans/p.md",
      verdict: "shipped",
    };
    assert.deepEqual(actionToArgs(action), [
      "plan-confirm",
      "--repo=critforge",
      "--verdict=shipped",
      "--",
      "docs/superpowers/plans/p.md",
    ]);
  });

  test("clear → plan-confirm --repo --clear, rel after --", () => {
    const action: WriteAction = {
      kind: "planConfirmClear",
      repoKey: "critforge",
      rel: "docs/superpowers/plans/p.md",
    };
    assert.deepEqual(actionToArgs(action), [
      "plan-confirm",
      "--repo=critforge",
      "--clear",
      "--",
      "docs/superpowers/plans/p.md",
    ]);
  });

  test("inherits the public-repo confirm-token flow (token lands before --)", async () => {
    const action: WriteAction = {
      kind: "planConfirm",
      repoKey: "critforge",
      rel: "docs/superpowers/plans/p.md",
      verdict: "shipped",
    };
    const { run, calls } = recordingRunner([
      {
        code: 0,
        stdout: JSON.stringify({ needs_confirm: true, reason: "PUBLIC", token: "tok123" }),
        stderr: "",
      },
      { code: 0, stdout: "✓ confirmed", stderr: "" },
    ]);
    const outcome = await executeWrite(run, action, alwaysConfirm("writeAnyway"));
    assert.equal(outcome.status, "written");
    assert.equal(calls.length, 2);
    // Second call carries --confirm=<token> as a flag BEFORE the -- separator.
    assert.deepEqual(calls[1], [
      "plan-confirm",
      "--repo=critforge",
      "--verdict=shipped",
      "--confirm=tok123",
      "--",
      "docs/superpowers/plans/p.md",
    ]);
  });
});

// ---------------------------------------------------------------------------
// planAck / planAckClear — durable frontmatter acknowledgment (#286 slice 1)
// ---------------------------------------------------------------------------

describe("actionToArgs — planAck", () => {
  test("ack → plan-ack --repo, rel after --", () => {
    assert.deepEqual(
      actionToArgs({ kind: "planAck", repoKey: "critforge", rel: "docs/plans/p.md" }),
      ["plan-ack", "--repo=critforge", "--", "docs/plans/p.md"],
    );
  });

  test("clear → plan-ack --repo --clear, rel after --", () => {
    assert.deepEqual(
      actionToArgs({ kind: "planAckClear", repoKey: "critforge", rel: "docs/plans/p.md" }),
      ["plan-ack", "--repo=critforge", "--clear", "--", "docs/plans/p.md"],
    );
  });

  test("inherits the public-repo confirm-token flow (token before --)", async () => {
    const { run, calls } = recordingRunner([
      { code: 0, stdout: JSON.stringify({ needs_confirm: true, reason: "PUBLIC", token: "tk" }), stderr: "" },
      { code: 0, stdout: "✓ acknowledged", stderr: "" },
    ]);
    const outcome = await executeWrite(
      run, { kind: "planAck", repoKey: "cf", rel: "docs/plans/p.md" }, alwaysConfirm("writeAnyway"),
    );
    assert.equal(outcome.status, "written");
    assert.deepEqual(calls[1], ["plan-ack", "--repo=cf", "--confirm=tk", "--", "docs/plans/p.md"]);
  });
});

// ---------------------------------------------------------------------------
// planBaseline / planBaselineClear — drift baseline (#286 slice 2)
// ---------------------------------------------------------------------------

describe("actionToArgs — planBaseline", () => {
  test("stamp → plan-baseline --repo, rel after --", () => {
    assert.deepEqual(
      actionToArgs({ kind: "planBaseline", repoKey: "cf", rel: "docs/plans/p.md" }),
      ["plan-baseline", "--repo=cf", "--", "docs/plans/p.md"],
    );
  });
  test("clear → plan-baseline --repo --clear, rel after --", () => {
    assert.deepEqual(
      actionToArgs({ kind: "planBaselineClear", repoKey: "cf", rel: "docs/plans/p.md" }),
      ["plan-baseline", "--repo=cf", "--clear", "--", "docs/plans/p.md"],
    );
  });
});

// ---------------------------------------------------------------------------
// closeIssue — the only GitHub-mutating action (#305)
// ---------------------------------------------------------------------------

describe("actionToArgs — closeIssue", () => {
  test("with reason + comment", () => {
    assert.deepEqual(
      actionToArgs({ kind: "closeIssue", repo: "o/r", number: 287, reason: "completed", comment: "done via dev" }),
      ["close-issue", "--repo=o/r", "--reason=completed", "--comment=done via dev", "--", "287"],
    );
  });
  test("omits --comment when absent", () => {
    assert.deepEqual(
      actionToArgs({ kind: "closeIssue", repo: "o/r", number: 5, reason: "not_planned" }),
      ["close-issue", "--repo=o/r", "--reason=not_planned", "--", "5"],
    );
  });
});

// ---------------------------------------------------------------------------
// issueInProgress — per-issue in-progress toggle via label (#271)
// ---------------------------------------------------------------------------

describe("actionToArgs — issueInProgress", () => {
  test("issueInProgress add → in-progress with --repo, number after --", () => {
    assert.deepStrictEqual(
      actionToArgs({ kind: "issueInProgress", repo: "o/r", number: 271, clear: false }),
      ["in-progress", "--repo=o/r", "--", "271"]);
  });
  test("issueInProgress clear → adds --clear", () => {
    assert.deepStrictEqual(
      actionToArgs({ kind: "issueInProgress", repo: "o/r", number: 271, clear: true }),
      ["in-progress", "--clear", "--repo=o/r", "--", "271"]);
  });
});

// ---------------------------------------------------------------------------
// pushTrack — promote a private track to the shared tier (#306)
// ---------------------------------------------------------------------------

describe("actionToArgs — pushTrack", () => {
  test("with repoKey → push-track --repo, track after --", () => {
    assert.deepEqual(
      actionToArgs({ kind: "pushTrack", track: "my-feature", repoKey: "demo" }),
      ["push-track", "--repo=demo", "--", "my-feature"],
    );
  });
  test("without repoKey → omits --repo", () => {
    assert.deepEqual(
      actionToArgs({ kind: "pushTrack", track: "my-feature" }),
      ["push-track", "--", "my-feature"],
    );
  });
});
