// Repo config-drift status decision logic — pure, no vscode import, so it's
// unit-tested. extension.ts is the thin glue that spawns doctorScan (cli.ts)
// and feeds its result here, mirroring the autofocus.ts split.
import type { DoctorFinding } from "./cli.ts";

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
