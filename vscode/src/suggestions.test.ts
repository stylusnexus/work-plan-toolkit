import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { parseSuggestions } from "./suggestions.ts";

const BATCH = "abc123";
const noneDismissed = (): boolean => false;

/** Builds a v2 answers JSON string with the given suggestions + batch_id. */
function answers(suggestions: unknown[], batchId: string = BATCH): string {
  return JSON.stringify({ version: 2, batch_id: batchId, suggestions });
}

describe("parseSuggestions — v2 answers parsing + bucketing (#241)", () => {
  test("clear-margin, above-threshold suggest → Suggested bucket", () => {
    const json = answers([
      { issue: 4501, verdict: "suggest", track: "auth-flow", confidence: 0.82, margin: "clear", rationale: "matches auth scope" },
    ]);
    const out = parseSuggestions(json, BATCH, 0.7, noneDismissed);
    assert.equal(out.suggested.length, 1);
    assert.equal(out.needsReview.length, 0);
    assert.equal(out.suggested[0].issueNumber, 4501);
    assert.equal(out.suggested[0].suggestedTrack, "auth-flow");
    assert.equal(out.suggested[0].rationale, "matches auth scope");
  });

  test("narrow margin → Needs review even with high confidence", () => {
    const json = answers([
      { issue: 4502, verdict: "suggest", track: "x", confidence: 0.95, margin: "narrow", rationale: "close call" },
    ]);
    const out = parseSuggestions(json, BATCH, 0.7, noneDismissed);
    assert.equal(out.suggested.length, 0);
    assert.equal(out.needsReview.length, 1);
    assert.equal(out.needsReview[0].margin, "narrow");
  });

  test("clear margin but below threshold → Needs review", () => {
    const json = answers([
      { issue: 4503, verdict: "suggest", track: "x", confidence: 0.5, margin: "clear", rationale: "weak" },
    ]);
    const out = parseSuggestions(json, BATCH, 0.7, noneDismissed);
    assert.equal(out.suggested.length, 0);
    assert.equal(out.needsReview.length, 1);
  });

  test("confidence exactly at threshold → Suggested (>= is inclusive)", () => {
    const json = answers([
      { issue: 4504, verdict: "suggest", track: "x", confidence: 0.7, margin: "clear", rationale: "" },
    ]);
    const out = parseSuggestions(json, BATCH, 0.7, noneDismissed);
    assert.equal(out.suggested.length, 1);
  });

  test("abstain verdict → excluded from both buckets", () => {
    const json = answers([
      { issue: 4507, verdict: "abstain", rationale: "no good fit" },
    ]);
    const out = parseSuggestions(json, BATCH, 0.7, noneDismissed);
    assert.equal(out.suggested.length, 0);
    assert.equal(out.needsReview.length, 0);
  });

  test("dismissed issue → excluded from both buckets", () => {
    const json = answers([
      { issue: 4501, verdict: "suggest", track: "auth-flow", confidence: 0.9, margin: "clear", rationale: "x" },
      { issue: 4502, verdict: "suggest", track: "auth-flow", confidence: 0.9, margin: "clear", rationale: "y" },
    ]);
    const out = parseSuggestions(json, BATCH, 0.7, (n) => n === 4501);
    assert.equal(out.suggested.length, 1);
    assert.equal(out.suggested[0].issueNumber, 4502);
  });

  test("batch_id mismatch → empty buckets + batchMismatch true", () => {
    const json = answers([
      { issue: 4501, verdict: "suggest", track: "x", confidence: 0.9, margin: "clear", rationale: "" },
    ], "stale-batch");
    const out = parseSuggestions(json, BATCH, 0.7, noneDismissed);
    assert.equal(out.suggested.length, 0);
    assert.equal(out.needsReview.length, 0);
    assert.equal(out.batchMismatch, true);
  });

  test("missing batch_id → treated as mismatch", () => {
    const json = JSON.stringify({ version: 2, suggestions: [
      { issue: 1, verdict: "suggest", track: "x", confidence: 0.9, margin: "clear", rationale: "" },
    ] });
    const out = parseSuggestions(json, BATCH, 0.7, noneDismissed);
    assert.equal(out.batchMismatch, true);
  });

  test("unparseable JSON → empty, no mismatch flag", () => {
    const out = parseSuggestions("{not json", BATCH, 0.7, noneDismissed);
    assert.deepEqual(out, { suggested: [], needsReview: [], batchMismatch: false });
  });

  test("missing margin defaults to clear", () => {
    const json = answers([
      { issue: 1, verdict: "suggest", track: "x", confidence: 0.9, rationale: "" },
    ]);
    const out = parseSuggestions(json, BATCH, 0.7, noneDismissed);
    assert.equal(out.suggested.length, 1);
    assert.equal(out.suggested[0].margin, "clear");
  });

  test("missing confidence defaults to 0 → Needs review", () => {
    const json = answers([
      { issue: 1, verdict: "suggest", track: "x", margin: "clear", rationale: "" },
    ]);
    const out = parseSuggestions(json, BATCH, 0.7, noneDismissed);
    assert.equal(out.needsReview.length, 1);
  });

  test("suggest with no track → dropped (unslottable)", () => {
    const json = answers([
      { issue: 1, verdict: "suggest", confidence: 0.9, margin: "clear", rationale: "" },
    ]);
    const out = parseSuggestions(json, BATCH, 0.7, noneDismissed);
    assert.equal(out.suggested.length, 0);
    assert.equal(out.needsReview.length, 0);
  });

  test("runner_up is carried when present", () => {
    const json = answers([
      { issue: 1, verdict: "suggest", track: "x", runner_up: "y", confidence: 0.9, margin: "clear", rationale: "" },
    ]);
    const out = parseSuggestions(json, BATCH, 0.7, noneDismissed);
    assert.equal(out.suggested[0].runnerUp, "y");
  });

  test("non-integer issue → dropped", () => {
    const json = answers([
      { issue: "nope", verdict: "suggest", track: "x", confidence: 0.9, margin: "clear", rationale: "" },
    ]);
    const out = parseSuggestions(json, BATCH, 0.7, noneDismissed);
    assert.equal(out.suggested.length, 0);
  });

  test("mixed batch: suggested + needsReview + abstain together", () => {
    const json = answers([
      { issue: 1, verdict: "suggest", track: "a", confidence: 0.9, margin: "clear", rationale: "strong" },
      { issue: 2, verdict: "suggest", track: "b", confidence: 0.4, margin: "clear", rationale: "weak" },
      { issue: 3, verdict: "suggest", track: "c", confidence: 0.9, margin: "narrow", rationale: "close" },
      { issue: 4, verdict: "abstain", rationale: "none" },
    ]);
    const out = parseSuggestions(json, BATCH, 0.7, noneDismissed);
    assert.deepEqual(out.suggested.map(s => s.issueNumber), [1]);
    assert.deepEqual(out.needsReview.map(s => s.issueNumber).sort(), [2, 3]);
  });
});
