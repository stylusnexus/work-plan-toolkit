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
  test("editFields with one field → ['set', track, 'status=parked']", () => {
    const action: WriteAction = {
      kind: "editFields",
      track: "platform-health",
      fields: { status: "parked" },
    };
    assert.deepEqual(actionToArgs(action), ["set", "platform-health", "status=parked"]);
  });

  test("editFields with empty fields {} → ['set', track] (no key=value pairs)", () => {
    const action: WriteAction = {
      kind: "editFields",
      track: "platform-health",
      fields: {},
    };
    assert.deepEqual(actionToArgs(action), ["set", "platform-health"]);
  });

  test("editFields with multiple fields → includes each key=value in Object.entries order", () => {
    const action: WriteAction = {
      kind: "editFields",
      track: "ph",
      fields: { status: "shipped", tier: "P1", milestone: "v2" },
    };
    const result = actionToArgs(action);
    assert.deepEqual(result, ["set", "ph", "status=shipped", "tier=P1", "milestone=v2"]);
  });

  test("setNext with [4167, 4148] → ['handoff', track, '--set-next=4167,4148']", () => {
    const action: WriteAction = {
      kind: "setNext",
      track: "platform-health",
      issues: [4167, 4148],
    };
    assert.deepEqual(actionToArgs(action), [
      "handoff",
      "platform-health",
      "--set-next=4167,4148",
    ]);
  });

  test("setNext with a single issue → '--set-next=42' (no trailing comma)", () => {
    const action: WriteAction = {
      kind: "setNext",
      track: "ph",
      issues: [42],
    };
    assert.deepEqual(actionToArgs(action), ["handoff", "ph", "--set-next=42"]);
  });

  test("refresh → ['refresh-md', track, '--yes']", () => {
    const action: WriteAction = { kind: "refresh", track: "platform-health" };
    assert.deepEqual(actionToArgs(action), ["refresh-md", "platform-health", "--yes"]);
  });

  test("reconcileDraft → ['reconcile', track, '--draft']", () => {
    const action: WriteAction = { kind: "reconcileDraft", track: "platform-health" };
    assert.deepEqual(actionToArgs(action), ["reconcile", "platform-health", "--draft"]);
  });

  test("hygiene → ['hygiene', '--yes']", () => {
    const action: WriteAction = { kind: "hygiene" };
    assert.deepEqual(actionToArgs(action), ["hygiene", "--yes"]);
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

  test("TWO runWrite calls; second call has --confirm=<token> appended in equals form", async () => {
    const action: WriteAction = {
      kind: "editFields",
      track: "ph",
      fields: { status: "shipped" },
    };
    const { run, calls } = recordingRunner([needsConfirmResult, successResult]);

    await executeWrite(run, action, alwaysConfirm("writeAnyway"));

    assert.equal(calls.length, 2, "should invoke runWrite exactly twice");

    // The second call must end with '--confirm=<token>' in equals form.
    const secondArgs = calls[1];
    const confirmArg = secondArgs[secondArgs.length - 1];
    assert.equal(confirmArg, `--confirm=${TOKEN}`, "confirm arg must use equals form");

    // There must be no separate '--confirm' flag (space-separated) anywhere.
    assert.ok(
      !secondArgs.includes("--confirm"),
      "must not have a bare '--confirm' (space-separated form)"
    );
  });

  test("second call's args are original args + --confirm=<token>", async () => {
    const action: WriteAction = {
      kind: "editFields",
      track: "ph",
      fields: { status: "shipped" },
    };
    const { run, calls } = recordingRunner([needsConfirmResult, successResult]);

    await executeWrite(run, action, alwaysConfirm("writeAnyway"));

    const firstArgs = calls[0];
    const secondArgs = calls[1];

    // Second call starts with all the same args as the first...
    assert.deepEqual(
      secondArgs.slice(0, firstArgs.length),
      firstArgs,
      "second call should start with original args"
    );
    // ...and appends exactly one more element: the confirm token.
    assert.equal(secondArgs.length, firstArgs.length + 1);
    assert.equal(secondArgs[secondArgs.length - 1], `--confirm=${TOKEN}`);
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
