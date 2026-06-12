import type { PlanDoc } from "./model.ts";

export type PlanBucket = "stalled" | "lie-gap" | "active" | "shipped" | "dead" | "other";

const DAY = 86_400_000;

/**
 * Difference in LOCAL calendar days between a `YYYY-MM-DD` manifest date and
 * `nowMs`. Both ends collapse to local midnight first, so the result matches the
 * CLI's date-based `(today - commit_date).days` regardless of the user's UTC
 * offset — `Date.parse("YYYY-MM-DD")` would anchor the manifest to UTC midnight
 * while `nowMs` is a local instant, drifting the verdict a day for non-UTC users.
 */
function coldDays(manifestDate: string, nowMs: number): number {
  const [y, m, d] = manifestDate.split("-").map(Number);
  const then = new Date(y, m - 1, d).getTime(); // local midnight of the manifest date
  const now = new Date(nowMs);
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  return Math.round((today - then) / DAY);
}

/** Apply the user's threshold to the raw clock. `stallDays === null` = "Match CLI"
 *  → trust the CLI's own `stalled` boolean (#164). */
export function isStalledForDisplay(d: PlanDoc, stallDays: number | null, nowMs: number): boolean {
  if (d.verdict !== "partial") return false;
  if (stallDays === null) return d.stalled;
  if (d.manifest_last_touched === null) return true; // present-but-never-committed = cold
  return coldDays(d.manifest_last_touched, nowMs) >= stallDays;
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
    bits.push(`${coldDays(d.manifest_last_touched, nowMs)}d cold`);
  }
  return bits.join(" · ");
}

export function ackKey(repo: string, rel: string): string {
  return `${repo}::${rel}`;
}
