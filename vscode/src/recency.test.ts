import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_STALE_DAYS,
  compareByLeastRecent,
  describeActivity,
  formatAge,
  isStaleTrack,
  lastActivityMs,
  lastActivityRaw,
  normalizeStaleDays,
  parseTrackTimestamp,
  trackAgeDays,
} from "./recency.ts";

// Local-time dates, so the tests hold in any timezone.
const at = (y: number, m: number, d: number, h = 0, mi = 0) => new Date(y, m - 1, d, h, mi).getTime();
const NOW = at(2026, 10, 5, 12, 0);
const DAY = 86_400_000;

describe("parseTrackTimestamp", () => {
  test("date-only and date-time forms, as local time", () => {
    assert.equal(parseTrackTimestamp("2026-09-14"), at(2026, 9, 14));
    assert.equal(parseTrackTimestamp("2026-09-14T08:30"), at(2026, 9, 14, 8, 30));
    assert.equal(parseTrackTimestamp("2026-09-14T08:30:15"), new Date(2026, 8, 14, 8, 30, 15).getTime());
    assert.equal(parseTrackTimestamp("  2026-09-14  "), at(2026, 9, 14));
  });

  test("anything unusable is null, never a throw", () => {
    for (const bad of [
      "", "   ", "yesterday", "2026-9-14", "2026-09-14 08:30", "2026-09-14T08:30Z",
      "2026-13-01", "2026-02-30", "2026-09-14T25:00", "2026-09-14T08:61",
      null, undefined, 20260914, {}, [], true,
    ]) {
      assert.equal(parseTrackTimestamp(bad), null, `expected null for ${JSON.stringify(bad)}`);
    }
  });
});

describe("lastActivityMs", () => {
  test("prefers last_touched", () => {
    assert.equal(lastActivityMs({ last_touched: "2026-09-14", last_handoff: "2026-09-01" }), at(2026, 9, 14));
  });
  test("falls back to last_handoff when last_touched is missing or malformed", () => {
    assert.equal(lastActivityMs({ last_handoff: "2026-09-01" }), at(2026, 9, 1));
    assert.equal(lastActivityMs({ last_touched: "garbage", last_handoff: "2026-09-01" }), at(2026, 9, 1));
  });
  test("null when neither is usable", () => {
    assert.equal(lastActivityMs({}), null);
    assert.equal(lastActivityMs({ last_touched: "x", last_handoff: null }), null);
  });
});

describe("lastActivityRaw", () => {
  test("returns the string that parsed, trimmed; null when none", () => {
    assert.equal(lastActivityRaw({ last_touched: " 2026-09-14 " }), "2026-09-14");
    assert.equal(lastActivityRaw({ last_touched: "junk", last_handoff: "2026-09-01" }), "2026-09-01");
    assert.equal(lastActivityRaw({ last_touched: "junk" }), null);
  });
});

describe("isStaleTrack", () => {
  const touched = (days: number) => {
    const d = new Date(NOW - days * DAY);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  };

  test("at or past the threshold is stale, just under is not", () => {
    // NOW is noon and date-only stamps are local midnight, so day counts carry +12h.
    assert.equal(isStaleTrack({ status: "active", last_touched: touched(14) }, 14, NOW), true);
    assert.equal(isStaleTrack({ status: "active", last_touched: touched(13) }, 14, NOW), false);
    assert.equal(isStaleTrack({ status: "active", last_touched: touched(30) }, 14, NOW), true);
  });

  test("only active, in-progress and blocked tracks qualify", () => {
    for (const status of ["active", "in-progress", "blocked"]) {
      assert.equal(isStaleTrack({ status, last_touched: touched(99) }, 14, NOW), true, status);
    }
    for (const status of ["shipped", "parked", "abandoned", "archived", ""]) {
      assert.equal(isStaleTrack({ status, last_touched: touched(99) }, 14, NOW), false, status);
    }
  });

  test("an archived track is never stale", () => {
    assert.equal(isStaleTrack({ status: "active", archived: true, last_touched: touched(99) }, 14, NOW), false);
  });

  test("unknown activity is never stale", () => {
    assert.equal(isStaleTrack({ status: "active" }, 14, NOW), false);
    assert.equal(isStaleTrack({ status: "active", last_touched: "junk" }, 14, NOW), false);
  });

  test("a future timestamp (clock skew) is not stale", () => {
    assert.equal(isStaleTrack({ status: "active", last_touched: "2027-01-01" }, 14, NOW), false);
  });

  test("the threshold is a parameter, so a change flips the answer with no other input", () => {
    const t = { status: "active", last_touched: touched(20) };
    assert.equal(isStaleTrack(t, 30, NOW), false);
    assert.equal(isStaleTrack(t, 14, NOW), true);
  });
});

describe("compareByLeastRecent", () => {
  const t = (name: string, last_touched?: string | null) => ({ name, last_touched });

  test("oldest first, unknown last, name breaks ties", () => {
    const sorted = [
      t("zed"), t("new", "2026-10-01"), t("bad", "junk"), t("old", "2026-01-01"),
      t("also-old", "2026-01-01"), t("nul", null),
    ].sort(compareByLeastRecent).map(x => x.name);
    assert.deepEqual(sorted, ["also-old", "old", "new", "bad", "nul", "zed"]);
  });

  test("is a total order: either direction agrees", () => {
    const a = t("a", "2026-05-05"), b = t("b", "2026-05-05"), c = t("c");
    assert.ok(compareByLeastRecent(a, b) < 0 && compareByLeastRecent(b, a) > 0);
    assert.ok(compareByLeastRecent(a, c) < 0 && compareByLeastRecent(c, a) > 0);
    assert.equal(compareByLeastRecent(a, a), 0);
  });
});

describe("formatAge / describeActivity", () => {
  test("human-readable ages", () => {
    assert.equal(formatAge(0.2), "today");
    assert.equal(formatAge(-3), "today");
    assert.equal(formatAge(1.5), "1 day ago");
    assert.equal(formatAge(5), "5 days ago");
    assert.equal(formatAge(13.9), "13 days ago");
    assert.equal(formatAge(14), "2 weeks ago");
    assert.equal(formatAge(40), "5 weeks ago");
    assert.equal(formatAge(60), "2 months ago");
    assert.equal(formatAge(400), "13 months ago");
  });

  test("describeActivity is null without a usable timestamp", () => {
    assert.equal(describeActivity({}, NOW), null);
    assert.equal(describeActivity({ last_touched: "junk" }, NOW), null);
    assert.equal(describeActivity({ last_touched: "2026-09-14" }, NOW), "last touched 3 weeks ago");
  });

  test("trackAgeDays is null when unknown, fractional when known", () => {
    assert.equal(trackAgeDays({}, NOW), null);
    assert.equal(trackAgeDays({ last_touched: "2026-10-04" }, NOW), 1.5);
  });
});

describe("normalizeStaleDays", () => {
  test("whole numbers >= 1 pass; anything else is the default", () => {
    assert.equal(normalizeStaleDays(30), 30);
    assert.equal(normalizeStaleDays(1), 1);
    for (const bad of [0, -5, 2.5, NaN, "14", null, undefined, Infinity]) {
      assert.equal(normalizeStaleDays(bad), DEFAULT_STALE_DAYS, String(bad));
    }
  });
});
