import type { Export, PlanDoc } from "./model.ts";

export type PlanBucket = "stalled" | "lie-gap" | "drift" | "active" | "shipped" | "dead" | "other";

/** Display metadata for a verdict bucket: the codicon SHAPE, its themed colour,
 *  a plain-English label, and a one-line meaning. Single source of truth shared
 *  by the Plans tree (icon + tooltip) and the legend (#348). */
export interface BucketMeta {
  /** VS Code codicon id (the SHAPE — carries meaning without colour, #208). */
  icon: string;
  /** ThemeColor id. List-semantic tokens (not charts.*) where contrast matters. */
  color: string;
  /** Plain-English verdict name surfaced in the tooltip + legend (#348). */
  label: string;
  /** One-line meaning for the legend. */
  blurb: string;
}

/**
 * verdict-bucket → display metadata. List-semantic colour tokens (not charts.*)
 * so glyphs meet non-text contrast on dark themes (#208 a11y pass); the distinct
 * SHAPE still carries the meaning, never colour alone — `bucketShapesAreDistinct`
 * guards that invariant in the tests.
 *
 * Plain labels (#348): the raw verdicts (partial/shipped/dead + flags) fan into
 * seven buckets whose icons were undiscoverable; each now carries a plain name so
 * the tooltip and the legend read at a glance.
 */
export const BUCKET_META: Record<PlanBucket, BucketMeta> = {
  // Stalled: a `clock` reads as "gone cold over time" more directly than a generic
  // warning triangle, and frees the triangle from the loud trio (#348).
  stalled: { icon: "clock", color: "list.warningForeground",
    label: "Stalled", blurb: "In progress but gone cold — no commits within your stall window." },
  // Lie-gap keeps the red `error` shape (a strong \"this is wrong\" signal); the
  // plain label is what disambiguates it from a generic failure (#348).
  "lie-gap": { icon: "error", color: "list.errorForeground",
    label: "Unverified", blurb: "Reads as shipped, but its phases are still unchecked — the claim isn't backed by progress." },
  // Drift: `issue-reopened` (diverged/changed) is distinct from stalled's old
  // warning glyph, which `alert` was easily confused with (#348).
  drift: { icon: "issue-reopened", color: "list.warningForeground",
    label: "Drifted", blurb: "Live verdict diverged from its confirmed baseline." },
  // Active unified on charts.blue (matches the active TRACK icon) — charts.yellow
  // was the lowest-contrast hue on dark.
  active: { icon: "circle-filled", color: "charts.blue",
    label: "In progress", blurb: "Partial and recently touched — actively in progress." },
  shipped: { icon: "pass-filled", color: "charts.green",
    label: "Shipped", blurb: "Done — phases checked and declared files present." },
  dead: { icon: "circle-slash", color: "descriptionForeground",
    label: "Abandoned", blurb: "Marked dead — intentionally dropped." },
  other: { icon: "question", color: "descriptionForeground",
    label: "Unknown", blurb: "No clear verdict (foreign or manifest-less doc)." },
};

/** Sort rank for a bucket — loud verdicts (stalled, lie-gap) float to the top.
 *  Doubles as the legend's display order so the legend reads top-down like the
 *  tree. */
export const BUCKET_RANK: Record<PlanBucket, number> = {
  stalled: 0,
  "lie-gap": 1,
  drift: 2,
  active: 3,
  shipped: 4,
  dead: 5,
  other: 6,
};

/** A row in the verdict legend (#348): a bucket's metadata, or the synthetic
 *  "Acknowledged" modifier that isn't a bucket but dims any row. */
export interface LegendRow extends BucketMeta {
  /** True for the non-bucket "Acknowledged" modifier row. */
  modifier?: boolean;
}

/** Legend rows in rank order, with the ack'd-row modifier appended last. The
 *  ack'd state mirrors the muted override in plansTree (`circle-outline`). */
export const LEGEND: LegendRow[] = [
  ...(Object.keys(BUCKET_RANK) as PlanBucket[])
    .sort((a, b) => BUCKET_RANK[a] - BUCKET_RANK[b])
    .map((b) => ({ ...BUCKET_META[b] })),
  {
    icon: "circle-outline", color: "descriptionForeground", modifier: true,
    label: "Acknowledged", blurb: "Dimmed — you acknowledged or confirmed this row, so it's muted.",
  },
];

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
  // Baseline drift (#286): the live verdict diverged from a stamped baseline —
  // loud, like stalled/lie-gap. The CLI already suppresses drift under an
  // override, so a confirmed plan never lands here.
  if (d.verdict_drift) return "drift";
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
  // Drift baseline markers (#286): loud direction when it diverged, faint
  // "watching" marker while it still matches.
  if (d.verdict_drift && d.verdict_baseline) {
    bits.push(`⚠ drifted (${d.verdict_baseline} → ${d.verdict})`);
  } else if (d.verdict_baseline) {
    bits.push("📌 baseline");
  }
  // Off-tree declared paths (#286) — a read-only "your manifest points outside
  // this repo" flag; the count earns a tooltip listing them (see plansTree).
  const offtree = d.offtree_paths?.length ?? 0;
  if (offtree > 0) bits.push(`⚠ ${offtree} off-tree path${offtree === 1 ? "" : "s"}`);
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
