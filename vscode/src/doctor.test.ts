import { test, describe } from "node:test";
import assert from "node:assert/strict";
import type { DoctorFinding } from "./cli.ts";
import { buildDoctorStatus } from "./doctor.ts";

const FINDING = (message: string): DoctorFinding => ({
  type: "github_rename_detected", key: "foo", folder: null, track: null,
  message, fixable: true, unverified: false, old: "org/old", new: "org/new",
});

describe("buildDoctorStatus", () => {
  test("empty findings returns null", () => {
    assert.equal(buildDoctorStatus([]), null);
  });

  test("non-empty findings returns the correct count", () => {
    const status = buildDoctorStatus([FINDING("a"), FINDING("b")]);
    assert.ok(status);
    assert.match(status!.text, /2 config issues/);
  });

  test("singular count reads naturally", () => {
    const status = buildDoctorStatus([FINDING("a")]);
    assert.match(status!.text, /1 config issue\b/);
  });

  test("tooltip lists every finding message", () => {
    const status = buildDoctorStatus([FINDING("first problem"), FINDING("second problem")]);
    assert.match(status!.tooltip, /first problem/);
    assert.match(status!.tooltip, /second problem/);
  });
});
