import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { isStalledForDisplay, planBucket, planDescription, ackKey, unregisteredTrackRepos } from "./planModel.ts";
import type { Export, PlanDoc, Track } from "./model.ts";

function doc(o: Partial<PlanDoc> = {}): PlanDoc {
  return { rel: "docs/superpowers/plans/p.md", kind: "plan", verdict: "partial", glyph: "🟡",
    rationale: "", files_present: 3, files_declared: 7, checkboxes_done: 2, checkboxes_total: 6,
    last_touched: null, manifest_last_touched: "2026-05-01", stalled: true, lie_gap: false,
    unchecked_items: [], stall_days: 14, ...o };
}

describe("isStalledForDisplay", () => {
  const NOW = Date.parse("2026-06-12");
  test("partial + manifest older than threshold = stalled", () => {
    assert.equal(isStalledForDisplay(doc({ manifest_last_touched: "2026-05-01" }), 14, NOW), true);
  });
  test("raising the threshold re-thresholds to not-stalled", () => {
    assert.equal(isStalledForDisplay(doc({ manifest_last_touched: "2026-05-01" }), 60, NOW), false);
  });
  test("non-partial is never stalled", () => {
    assert.equal(isStalledForDisplay(doc({ verdict: "shipped" }), 14, NOW), false);
  });
  test("partial with null manifest date (present-but-never-committed) = stalled", () => {
    assert.equal(isStalledForDisplay(doc({ manifest_last_touched: null }), 14, NOW), true);
  });
  test("null threshold (Match CLI) falls back to the CLI's emitted stalled boolean", () => {
    assert.equal(isStalledForDisplay(doc({ stalled: true }), null, NOW), true);
    assert.equal(isStalledForDisplay(doc({ stalled: false }), null, NOW), false);
  });
  test("calendar-day math: exactly stallDays calendar days back is stalled; one fewer is not", () => {
    // Build `now` from a LOCAL midnight so the count is the user's calendar-day
    // delta, matching the CLI's date-based (today - commit_date).days — and so
    // the assertion is timezone-independent rather than UTC-anchored.
    const now = new Date(2026, 5, 12).getTime(); // local midnight 2026-06-12
    const minus = (days: number): string => {
      const dt = new Date(2026, 5, 12 - days);
      const m = String(dt.getMonth() + 1).padStart(2, "0");
      const d = String(dt.getDate()).padStart(2, "0");
      return `${dt.getFullYear()}-${m}-${d}`;
    };
    assert.equal(isStalledForDisplay(doc({ manifest_last_touched: minus(14) }), 14, now), true);
    assert.equal(isStalledForDisplay(doc({ manifest_last_touched: minus(13) }), 14, now), false);
  });
});

describe("planBucket", () => {
  const NOW = Date.parse("2026-06-12");
  test("stalled outranks everything", () => assert.equal(planBucket(doc(), 14, NOW), "stalled"));
  test("lie_gap shipped is lie-gap", () => assert.equal(planBucket(doc({ verdict: "shipped", lie_gap: true }), 14, NOW), "lie-gap"));
  test("warm partial is active", () => assert.equal(planBucket(doc({ manifest_last_touched: "2026-06-11" }), 14, NOW), "active"));
  test("clean shipped is shipped", () => assert.equal(planBucket(doc({ verdict: "shipped", lie_gap: false }), 14, NOW), "shipped"));
  test("dead is dead", () => assert.equal(planBucket(doc({ verdict: "dead" }), 14, NOW), "dead"));
});

describe("planDescription", () => {
  test("leads with phases, then files, then coldness for a stalled doc", () => {
    const d = planDescription(doc({ manifest_last_touched: "2026-05-01" }), 14, Date.parse("2026-06-12"));
    assert.match(d, /^2\/6 phases · 3\/7 files · \d+d cold$/);
  });
  test("warm doc omits the cold suffix", () => {
    const d = planDescription(doc({ manifest_last_touched: "2026-06-11" }), 14, Date.parse("2026-06-12"));
    assert.equal(d, "2/6 phases · 3/7 files");
  });
  test("override appends a confirmed marker (#286)", () => {
    const d = planDescription(doc({ verdict: "shipped", lie_gap: false, override: "shipped",
      manifest_last_touched: "2026-06-11" }), 14, Date.parse("2026-06-12"));
    assert.equal(d, "2/6 phases · 3/7 files · ✋ confirmed");
  });
});

describe("ackKey", () => {
  test("is repo::rel", () => assert.equal(ackKey("org/repo", "docs/x.md"), "org/repo::docs/x.md"));
});

describe("unregisteredTrackRepos", () => {
  // Minimal Track — only `repo` matters for this helper.
  const track = (repo: string | null): Track => ({
    name: "t", repo: repo as string, path: null, folder: null, tier: "private",
    status: "active", launch_priority: null, milestone_alignment: null, visibility: null,
    blockers: [], next_up: [], depends_on: [], rollup: { open: 0, closed: 0 }, issues: [],
  });
  const configRepo = (repo: string) => ({
    folder: repo.split("/")[1], repo, local: null, has_local: false, visibility: null,
  });
  const exp = (tracks: Track[], repos: Export["repos"]): Export => ({
    schema: 1, generated_at: "", tracks, ...(repos !== undefined && { repos }),
  });

  test("returns a track slug that has no repos: entry", () => {
    const result = unregisteredTrackRepos(exp([track("org/untracked")], []));
    assert.deepEqual(result, ["org/untracked"]);
  });

  test("excludes a track slug that IS in repos:", () => {
    const result = unregisteredTrackRepos(
      exp([track("org/registered")], [configRepo("org/registered")]),
    );
    assert.deepEqual(result, []);
  });

  test("dedupes two tracks on the same unregistered slug", () => {
    const result = unregisteredTrackRepos(exp([track("org/x"), track("org/x")], []));
    assert.deepEqual(result, ["org/x"]);
  });

  test("excludes a null/empty track repo", () => {
    const result = unregisteredTrackRepos(exp([track(null), track("")], []));
    assert.deepEqual(result, []);
  });

  test("returns slugs sorted for a stable render", () => {
    const result = unregisteredTrackRepos(exp([track("org/zed"), track("org/abe")], []));
    assert.deepEqual(result, ["org/abe", "org/zed"]);
  });

  test("treats a missing repos field as zero registered (all track slugs unregistered)", () => {
    const result = unregisteredTrackRepos(exp([track("org/x")], undefined));
    assert.deepEqual(result, ["org/x"]);
  });

  test("empty when every track slug is registered", () => {
    const result = unregisteredTrackRepos(
      exp([track("org/a"), track("org/b")], [configRepo("org/a"), configRepo("org/b")]),
    );
    assert.deepEqual(result, []);
  });
});
