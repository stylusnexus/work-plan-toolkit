import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { issuesFingerprint } from "./fingerprint.ts";

// Known vectors computed against the CLI's Python implementation:
//   sha256(json.dumps(sorted(ints), separators=(",",":")).encode()).hexdigest()[:16]
// These MUST stay byte-identical to the CLI or --expect silently mismatches and
// every slot would read as {stale}.
describe("issuesFingerprint — byte-match to the CLI's Python fingerprint (#241)", () => {
  test("matches the Python vector for [10,20]", () => {
    assert.equal(issuesFingerprint([10, 20]), "28c5e638bdf2b3cd");
  });

  test("order-independent: [20,10] hashes the same as [10,20]", () => {
    assert.equal(issuesFingerprint([20, 10]), issuesFingerprint([10, 20]));
    assert.equal(issuesFingerprint([20, 10]), "28c5e638bdf2b3cd");
  });

  test("numeric sort, not lexicographic: [2,10] collapses with [10,2]", () => {
    // Lexicographic sort would order [10,2] as ["10","2"] → wrong hash; numeric
    // sort gives [2,10] both ways.
    assert.equal(issuesFingerprint([2, 10]), issuesFingerprint([10, 2]));
  });

  test("empty list matches the Python vector", () => {
    assert.equal(issuesFingerprint([]), "4f53cda18c2baa0c");
  });

  test("three-element list matches the Python vector", () => {
    assert.equal(issuesFingerprint([1, 2, 3]), "a615eeaee21de517");
  });

  test("does not mutate its input", () => {
    const input = [20, 10, 30];
    issuesFingerprint(input);
    assert.deepEqual(input, [20, 10, 30]);
  });

  test("returns a 16-char hex string", () => {
    assert.match(issuesFingerprint([1, 2, 3]), /^[0-9a-f]{16}$/);
  });
});
