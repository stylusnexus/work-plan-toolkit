import { test, describe } from "node:test";
import assert from "node:assert/strict";
import type { DiagnosticsReport, DoctorFinding } from "./cli.ts";
import { buildDoctorStatus, diagnosticsToast, formatDiagnostics } from "./doctor.ts";

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


const CHK = (id: string, status: "ok" | "warn" | "fail" | "skip", message: string, remediation: string | null = null) =>
  ({ id, status, message, remediation });

describe("formatDiagnostics (#427)", () => {
  const report: DiagnosticsReport = {
    status: "blocking",
    checks: [
      CHK("python", "ok", "Python 3.12.0"),
      CHK("yq", "fail", "yq not found on PATH", "brew install yq"),
      CHK("yq-implementation", "skip", "skipped: yq is not installed", "ignored for skips"),
      CHK("gh-auth", "warn", "could not verify sign-in", "retry in a moment"),
    ],
    findings: [FINDING("repo renamed")],
  };

  test("marks every check and prints a fix only for fail and warn", () => {
    const lines = formatDiagnostics(report);
    assert.equal(lines[0], "Work Plan diagnostics — blocking");
    assert.ok(lines.includes("  ✓ python: Python 3.12.0"));
    assert.ok(lines.includes("  ✗ yq: yq not found on PATH"));
    assert.ok(lines.includes("      fix: brew install yq"));
    assert.ok(lines.includes("  – yq-implementation: skipped: yq is not installed"));
    assert.ok(lines.includes("  ! gh-auth: could not verify sign-in"));
    assert.ok(lines.includes("      fix: retry in a moment"));
    assert.ok(!lines.some((l) => l.includes("ignored for skips")));
  });

  test("lists drift findings after the checks", () => {
    const lines = formatDiagnostics(report);
    assert.ok(lines.indexOf("Config drift:") > lines.indexOf("  ✓ python: Python 3.12.0"));
    assert.ok(lines.includes("  • repo renamed"));
  });

  test("a fatal config reason is shown", () => {
    const lines = formatDiagnostics({ status: "blocking", checks: [], findings: [], fatal: "bad yaml" });
    assert.ok(lines.includes("Config could not be loaded: bad yaml"));
  });

  test("a healthy report has no fix lines and no drift section", () => {
    const lines = formatDiagnostics({ status: "healthy", checks: [CHK("python", "ok", "Python 3.12")], findings: [] });
    assert.ok(!lines.some((l) => l.includes("fix:") || l.includes("Config drift")));
  });
});

describe("diagnosticsToast (#427)", () => {
  test("blocking names the first failed check and counts the rest", () => {
    const t = diagnosticsToast({
      status: "blocking", findings: [],
      checks: [CHK("git", "fail", "git not found on PATH"), CHK("yq", "fail", "yq not found on PATH"), CHK("python", "ok", "p")],
    });
    assert.equal(t.level, "error");
    assert.equal(t.text, "Work Plan: git — git not found on PATH (+1 more)");
  });

  test("warning counts warned checks plus drift findings", () => {
    const t = diagnosticsToast({ status: "warning", checks: [CHK("gh-auth", "warn", "m")], findings: [FINDING("a")] });
    assert.deepEqual(t, { level: "warning", text: "Work Plan: diagnostics found 2 things to look at" });
    assert.equal(
      diagnosticsToast({ status: "warning", checks: [CHK("a", "warn", "m")], findings: [] }).text,
      "Work Plan: diagnostics found 1 thing to look at",
    );
  });

  test("healthy counts only the checks that actually ran", () => {
    const t = diagnosticsToast({ status: "healthy", findings: [], checks: [CHK("a", "ok", "m"), CHK("b", "skip", "m"), CHK("c", "ok", "m")] });
    assert.deepEqual(t, { level: "info", text: "Work Plan: all 2 diagnostics checks passed" });
  });

  test("blocking with no failed check still says so", () => {
    assert.equal(diagnosticsToast({ status: "blocking", checks: [], findings: [] }).level, "error");
  });
});
