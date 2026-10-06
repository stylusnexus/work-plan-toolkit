// Repo config-drift status decision logic — pure, no vscode import, so it's
// unit-tested. extension.ts is the thin glue that spawns doctorScan (cli.ts)
// and feeds its result here, mirroring the autofocus.ts split.
import type { DiagnosticsReport, DoctorFinding } from "./cli.ts";

/**
 * Builds the status-bar text/tooltip for a set of doctor findings, or null
 * when there's nothing to show (findings is empty — no status-bar item at
 * all, matching how the rest of the extension treats a healthy state as "no
 * UI" rather than a reassuring checkmark).
 */
export function buildDoctorStatus(
  findings: DoctorFinding[],
): { text: string; tooltip: string } | null {
  if (findings.length === 0) return null;
  const noun = findings.length === 1 ? "config issue" : "config issues";
  const text = `$(warning) Work Plan: ${findings.length} ${noun}`;
  const tooltip = findings.map((f) => `• ${f.message}`).join("\n");
  return { text, tooltip };
}

const STATUS_MARK: Record<string, string> = { ok: "✓", warn: "!", fail: "✗", skip: "–" };

/**
 * The Run Diagnostics report as output-channel lines (#427): every check with a
 * mark, the remediation under anything that needs attention, then drift findings.
 * Pure so it is unit-tested.
 */
export function formatDiagnostics(report: DiagnosticsReport): string[] {
  const lines: string[] = [`Work Plan diagnostics — ${report.status}`, ""];
  for (const c of report.checks) {
    lines.push(`  ${STATUS_MARK[c.status] ?? "?"} ${c.id}: ${c.message}`);
    if ((c.status === "fail" || c.status === "warn") && c.remediation) {
      lines.push(`      fix: ${c.remediation}`);
    }
  }
  if (report.fatal) {
    lines.push("", `Config could not be loaded: ${report.fatal}`);
  }
  if (report.findings.length > 0) {
    lines.push("", "Config drift:");
    for (const f of report.findings) lines.push(`  • ${f.message}`);
  }
  return lines;
}

/** One-line toast text + severity for a finished diagnostics run. */
export function diagnosticsToast(
  report: DiagnosticsReport,
): { level: "info" | "warning" | "error"; text: string } {
  const failed = report.checks.filter((c) => c.status === "fail");
  const warned = report.checks.filter((c) => c.status === "warn");
  if (report.status === "blocking") {
    const first = failed[0];
    const more = failed.length > 1 ? ` (+${failed.length - 1} more)` : "";
    return {
      level: "error",
      text: first
        ? `Work Plan: ${first.id} — ${first.message}${more}`
        : "Work Plan: diagnostics found a blocking problem",
    };
  }
  if (report.status === "warning") {
    const n = warned.length + report.findings.length;
    return { level: "warning", text: `Work Plan: diagnostics found ${n} thing${n === 1 ? "" : "s"} to look at` };
  }
  const ran = report.checks.filter((c) => c.status !== "skip").length;
  return { level: "info", text: `Work Plan: all ${ran} diagnostics checks passed` };
}
