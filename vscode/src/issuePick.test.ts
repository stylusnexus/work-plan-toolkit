/**
 * Tests for src/issuePick.ts — pure issue QuickPick item builder (#212).
 * No vscode import; runs offline.
 */
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { buildIssuePickItems } from "./issuePick.ts";
import type { Issue } from "./model.ts";

function makeIssue(overrides: Partial<Issue> = {}): Issue {
  return {
    number: 1,
    title: "an issue",
    state: "open",
    assignee: "—",
    milestone: null,
    ...overrides,
  };
}

describe("buildIssuePickItems — ordering", () => {
  it("sorts open issues before closed", () => {
    const items = buildIssuePickItems([
      makeIssue({ number: 5, state: "closed" }),
      makeIssue({ number: 9, state: "open" }),
    ]);
    assert.deepEqual(items.map((i) => i.issueNumber), [9, 5]);
  });

  it("sorts ascending by number within each state group", () => {
    const items = buildIssuePickItems([
      makeIssue({ number: 30, state: "open" }),
      makeIssue({ number: 7, state: "closed" }),
      makeIssue({ number: 10, state: "open" }),
      makeIssue({ number: 4, state: "closed" }),
    ]);
    // open (10, 30) then closed (4, 7)
    assert.deepEqual(items.map((i) => i.issueNumber), [10, 30, 4, 7]);
  });

  it("does not mutate the input array", () => {
    const input = [makeIssue({ number: 2 }), makeIssue({ number: 1 })];
    buildIssuePickItems(input);
    assert.deepEqual(input.map((i) => i.number), [2, 1]);
  });
});

describe("buildIssuePickItems — includeClosed", () => {
  it("includes closed issues by default", () => {
    const items = buildIssuePickItems([
      makeIssue({ number: 1, state: "open" }),
      makeIssue({ number: 2, state: "closed" }),
    ]);
    assert.equal(items.length, 2);
  });

  it("excludes closed issues when includeClosed is false (Set-Next)", () => {
    const items = buildIssuePickItems(
      [
        makeIssue({ number: 1, state: "open" }),
        makeIssue({ number: 2, state: "closed" }),
        makeIssue({ number: 3, state: "open" }),
      ],
      { includeClosed: false },
    );
    assert.deepEqual(items.map((i) => i.issueNumber), [1, 3]);
  });

  it("returns an empty list for no issues", () => {
    assert.deepEqual(buildIssuePickItems([]), []);
  });
});

describe("buildIssuePickItems — label & description format", () => {
  it("label is '#<n>  <title>' with two spaces", () => {
    const [item] = buildIssuePickItems([makeIssue({ number: 87, title: "Fix auth" })]);
    assert.equal(item.label, "#87  Fix auth");
  });

  it("description is the state alone when there is no milestone", () => {
    const [item] = buildIssuePickItems([makeIssue({ state: "open", milestone: null })]);
    assert.equal(item.description, "open");
  });

  it("description appends the milestone when present", () => {
    const [item] = buildIssuePickItems([
      makeIssue({ state: "open", milestone: "v0.6" }),
    ]);
    assert.equal(item.description, "open · v0.6");
  });

  it("carries the issue number for the handler to act on", () => {
    const [item] = buildIssuePickItems([makeIssue({ number: 42 })]);
    assert.equal(item.issueNumber, 42);
  });
});
