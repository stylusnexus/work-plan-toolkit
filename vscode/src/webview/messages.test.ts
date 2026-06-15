/**
 * Tests for src/webview/messages.ts — pure message type guard.
 *
 * Regression suite for the silent-dead-button bug: isWebviewMessage was
 * missing cases for openPlan (#285) and closeIssue (#305), so those handlers
 * in _handleMessage were never reached. Extracting the guard to this pure
 * module makes it unit-testable; these tests lock every handled message type
 * and reject unknown/malformed payloads.
 *
 * All assertions are offline; no vscode import anywhere in this file or the
 * module under test.
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { isWebviewMessage } from "./messages.ts";

// ---------------------------------------------------------------------------
// Valid message types — every handled type must pass
// ---------------------------------------------------------------------------

describe("isWebviewMessage — valid messages", () => {
  it("accepts a valid selectTrack message", () => {
    assert.equal(isWebviewMessage({ type: "selectTrack", name: "api-core" }), true);
  });

  it("accepts a valid openIssue message", () => {
    assert.equal(
      isWebviewMessage({ type: "openIssue", repo: "o/r", number: 42 }),
      true,
    );
  });

  it("accepts a valid setFocus message (true)", () => {
    assert.equal(isWebviewMessage({ type: "setFocus", focus: true }), true);
  });

  it("accepts a valid setFocus message (false)", () => {
    assert.equal(isWebviewMessage({ type: "setFocus", focus: false }), true);
  });

  it("accepts a valid moveIssue message", () => {
    assert.equal(isWebviewMessage({ type: "moveIssue", number: 7 }), true);
  });

  it("accepts a valid filterMilestone message", () => {
    assert.equal(
      isWebviewMessage({ type: "filterMilestone", milestone: "v2.0" }),
      true,
    );
  });

  it("accepts a valid openTrackFile message (no payload)", () => {
    assert.equal(isWebviewMessage({ type: "openTrackFile" }), true);
  });

  it("accepts a valid openPlan message (no payload)", () => {
    assert.equal(isWebviewMessage({ type: "openPlan" }), true);
  });

  it("accepts a valid closeIssue message", () => {
    assert.equal(isWebviewMessage({ type: "closeIssue", number: 5 }), true);
  });

  it("accepts a valid toggleInProgress message (clear=false)", () => {
    assert.equal(
      isWebviewMessage({ type: "toggleInProgress", number: 3, clear: false }),
      true,
    );
  });

  it("accepts a valid toggleInProgress message (clear=true)", () => {
    assert.equal(
      isWebviewMessage({ type: "toggleInProgress", number: 1, clear: true }),
      true,
    );
  });

  it("accepts a valid setNextUp message (no payload)", () => {
    assert.equal(isWebviewMessage({ type: "setNextUp" }), true);
  });
});

// ---------------------------------------------------------------------------
// Regression guards — the exact cases that were silently dropped (#285, #305)
// ---------------------------------------------------------------------------

describe("isWebviewMessage — regression: previously-dropped message types", () => {
  it("REGRESSION #305: closeIssue with number passes the guard", () => {
    assert.equal(
      isWebviewMessage({ type: "closeIssue", number: 5 }),
      true,
      "closeIssue was missing from the guard switch and silently dropped",
    );
  });

  it("REGRESSION #285: openPlan passes the guard", () => {
    assert.equal(
      isWebviewMessage({ type: "openPlan" }),
      true,
      "openPlan was missing from the guard switch and silently dropped",
    );
  });

  it("REGRESSION #271: toggleInProgress passes the guard", () => {
    assert.equal(
      isWebviewMessage({ type: "toggleInProgress", number: 2, clear: false }),
      true,
      "toggleInProgress was added with the fix and must stay in the guard",
    );
  });

  it("setNextUp passes the guard (no payload — both union and guard case required)", () => {
    assert.equal(
      isWebviewMessage({ type: "setNextUp" }),
      true,
      "setNextUp must be in BOTH the WebviewMessage union AND the isWebviewMessage guard",
    );
  });
});

// ---------------------------------------------------------------------------
// Unknown / non-object inputs rejected
// ---------------------------------------------------------------------------

describe("isWebviewMessage — rejects non-objects and missing type", () => {
  it("rejects null", () => {
    assert.equal(isWebviewMessage(null), false);
  });

  it("rejects a string", () => {
    assert.equal(isWebviewMessage("selectTrack"), false);
  });

  it("rejects a number", () => {
    assert.equal(isWebviewMessage(42), false);
  });

  it("rejects undefined", () => {
    assert.equal(isWebviewMessage(undefined), false);
  });

  it("rejects an array", () => {
    assert.equal(isWebviewMessage([]), false);
  });

  it("rejects an empty object (no type field)", () => {
    assert.equal(isWebviewMessage({}), false);
  });

  it("rejects an object with a numeric type field", () => {
    assert.equal(isWebviewMessage({ type: 1 }), false);
  });

  it("rejects an unknown type string", () => {
    assert.equal(isWebviewMessage({ type: "bogus" }), false);
  });
});

// ---------------------------------------------------------------------------
// Malformed payloads — valid type but bad/missing fields
// ---------------------------------------------------------------------------

describe("isWebviewMessage — rejects malformed payloads", () => {
  // selectTrack
  it("rejects selectTrack without name", () => {
    assert.equal(isWebviewMessage({ type: "selectTrack" }), false);
  });

  it("rejects selectTrack with numeric name", () => {
    assert.equal(isWebviewMessage({ type: "selectTrack", name: 5 }), false);
  });

  // openIssue — repo must match owner/repo slug pattern
  it("rejects openIssue with a bad repo (not a slug)", () => {
    assert.equal(
      isWebviewMessage({ type: "openIssue", repo: "not-a-slug", number: 1 }),
      false,
    );
  });

  it("rejects openIssue with missing number", () => {
    assert.equal(isWebviewMessage({ type: "openIssue", repo: "o/r" }), false);
  });

  it("rejects openIssue with number 0", () => {
    assert.equal(
      isWebviewMessage({ type: "openIssue", repo: "o/r", number: 0 }),
      false,
    );
  });

  it("rejects openIssue with negative number", () => {
    assert.equal(
      isWebviewMessage({ type: "openIssue", repo: "o/r", number: -1 }),
      false,
    );
  });

  it("rejects openIssue with float number", () => {
    assert.equal(
      isWebviewMessage({ type: "openIssue", repo: "o/r", number: 1.5 }),
      false,
    );
  });

  // setFocus
  it("rejects setFocus without focus field", () => {
    assert.equal(isWebviewMessage({ type: "setFocus" }), false);
  });

  it("rejects setFocus with string focus", () => {
    assert.equal(isWebviewMessage({ type: "setFocus", focus: "true" }), false);
  });

  // moveIssue
  it("rejects moveIssue with number 0", () => {
    assert.equal(isWebviewMessage({ type: "moveIssue", number: 0 }), false);
  });

  it("rejects moveIssue with negative number", () => {
    assert.equal(isWebviewMessage({ type: "moveIssue", number: -5 }), false);
  });

  it("rejects moveIssue without number", () => {
    assert.equal(isWebviewMessage({ type: "moveIssue" }), false);
  });

  // filterMilestone — empty string must be rejected
  it("rejects filterMilestone with empty milestone string", () => {
    assert.equal(
      isWebviewMessage({ type: "filterMilestone", milestone: "" }),
      false,
    );
  });

  it("rejects filterMilestone without milestone field", () => {
    assert.equal(isWebviewMessage({ type: "filterMilestone" }), false);
  });

  // closeIssue
  it("rejects closeIssue without number", () => {
    assert.equal(isWebviewMessage({ type: "closeIssue" }), false);
  });

  it("rejects closeIssue with number 0", () => {
    assert.equal(isWebviewMessage({ type: "closeIssue", number: 0 }), false);
  });

  it("rejects closeIssue with negative number", () => {
    assert.equal(isWebviewMessage({ type: "closeIssue", number: -1 }), false);
  });

  // toggleInProgress
  it("rejects toggleInProgress without clear boolean", () => {
    assert.equal(
      isWebviewMessage({ type: "toggleInProgress", number: 3 }),
      false,
    );
  });

  it("rejects toggleInProgress with string clear", () => {
    assert.equal(
      isWebviewMessage({ type: "toggleInProgress", number: 3, clear: "false" }),
      false,
    );
  });

  it("rejects toggleInProgress with number 0", () => {
    assert.equal(
      isWebviewMessage({ type: "toggleInProgress", number: 0, clear: false }),
      false,
    );
  });

  it("rejects toggleInProgress with negative number", () => {
    assert.equal(
      isWebviewMessage({ type: "toggleInProgress", number: -2, clear: true }),
      false,
    );
  });
});
