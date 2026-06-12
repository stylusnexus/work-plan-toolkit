import type { PlanDoc } from "./model.ts";

export type PlanBucket = "stalled" | "lie-gap" | "active" | "shipped" | "dead" | "other";

const DAY = 86_400_000;

/** Apply the user's threshold to the raw clock. `stallDays === null` = "Match CLI"
 *  → trust the CLI's own `stalled` boolean (#164). */
export function isStalledForDisplay(d: PlanDoc, stallDays: number | null, nowMs: number): boolean {
  if (d.verdict !== "partial") return false;
  if (stallDays === null) return d.stalled;
  if (d.manifest_last_touched === null) return true; // present-but-never-committed = cold
  const days = (nowMs - Date.parse(d.manifest_last_touched)) / DAY;
  return days >= stallDays;
}

export function planBucket(d: PlanDoc, stallDays: number | null, nowMs: number): PlanBucket {
  if (isStalledForDisplay(d, stallDays, nowMs)) return "stalled";
  if (d.verdict === "shipped" && d.lie_gap) return "lie-gap";
  if (d.verdict === "partial") return "active";
  if (d.verdict === "shipped") return "shipped";
  if (d.verdict === "dead") return "dead";
  return "other";
}

export function planDescription(d: PlanDoc, stallDays: number | null, nowMs: number): string {
  const bits = [`${d.checkboxes_done}/${d.checkboxes_total} phases`,
                `${d.files_present}/${d.files_declared} files`];
  if (isStalledForDisplay(d, stallDays, nowMs) && d.manifest_last_touched) {
    const days = Math.floor((nowMs - Date.parse(d.manifest_last_touched)) / DAY);
    bits.push(`${days}d cold`);
  }
  return bits.join(" · ");
}

export function ackKey(repo: string, rel: string): string {
  return `${repo}::${rel}`;
}
