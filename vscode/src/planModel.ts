import type { Export, PlanDoc } from "./model.ts";

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
  // A human-confirmed verdict (#286) — flag it so the row reads as affirmed, not
  // merely mechanically scored (the icon already drops to the verdict's bucket).
  if (d.override) bits.push("✋ confirmed");
  return bits.join(" · ");
}

export function ackKey(repo: string, rel: string): string {
  return `${repo}::${rel}`;
}

/**
 * GitHub slugs that tracks reference but that have NO `repos:` config entry
 * (#288 follow-up). The Plans view scans by config folder key — a track-only
 * repo has no registered local clone to scan, so it can't be a real repo node;
 * the view surfaces it as a greyed "not registered — Add Repo to scan" row
 * instead of silently dropping it (the asymmetry that made it look like a bug).
 *
 * Returns distinct slugs sorted for a stable render. A null/empty track `repo`
 * is excluded — it can't be registered or scanned, so there's nothing to offer.
 * Pure (no vscode) so the detection is unit-tested without a provider mock.
 */
export function unregisteredTrackRepos(exp: Export): string[] {
  const registered = new Set(
    (exp.repos ?? []).map((r) => r.repo).filter((s): s is string => !!s),
  );
  const out = new Set<string>();
  for (const t of exp.tracks) {
    if (t.repo && !registered.has(t.repo)) out.add(t.repo);
  }
  return Array.from(out).sort();
}
