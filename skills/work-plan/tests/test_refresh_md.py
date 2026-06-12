"""Tests for refresh-md.

Canonical tables are RE-DERIVED on every run from frontmatter membership + live
GitHub data, milestone-ordered via the shared renderer (#101). This makes the
markdown table self-healing: order, the Milestone column, missing rows, and
statuses are all rebuilt each run, so it can't decay or drift from the viewer.
Tracks WITHOUT a canonical table keep the conservative in-place behavior
(update status cells, append missing rows in frontmatter order — issue #77).
"""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import refresh_md
from lib.status_table import (
    find_canonical_status_tables, render_canonical_table, ISSUE_NUM_RE,
)


def _gh(num, title, state="OPEN", logins=(), milestone=None):
    """A gh-issue dict as fetch_issues returns."""
    d = {"number": num, "title": title, "state": state,
         "assignees": [{"login": l} for l in logins]}
    if milestone:
        d["milestone"] = {"title": milestone}
    return d


def _canon_body(ghs, milestone_alignment=None, *, trailing="## Notes\n\nnarrative\n"):
    """Build a track body whose canonical block is exactly what
    render_canonical_table would emit for `ghs` — so re-derive round-trips."""
    by = {g["number"]: g for g in ghs}
    nums = [g["number"] for g in ghs]
    table = render_canonical_table(nums, by, milestone_alignment)
    return table + "\n---\n\n" + trailing


def _track(*, name, repo, issues, body, milestone_alignment=None):
    meta = {"track": name, "status": "active",
            "github": {"repo": repo, "issues": list(issues)}}
    if milestone_alignment:
        meta["milestone_alignment"] = milestone_alignment
    return SimpleNamespace(
        name=name, path=Path(f"/tmp/fake/{name}.md"), body=body, meta=meta,
        has_frontmatter=True, repo=repo,
    )


def _drive(track, issues, args):
    cfg = {"notes_root": "/tmp/fake"}
    with patch("commands.refresh_md.load_config", return_value=cfg), \
         patch("commands.refresh_md.discover_tracks", return_value=[track]), \
         patch("commands.refresh_md.fetch_issues", return_value=issues), \
         patch("commands.refresh_md.write_file") as mw:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = refresh_md.run(args)
    return rc, mw, buf.getvalue()


class CanonicalRederiveTest(unittest.TestCase):
    def test_missing_frontmatter_issues_appear_after_rederive(self):
        """Issues in frontmatter but absent from the table show up after refresh
        (membership is frontmatter-canonical); table is the new 5-col form."""
        existing = [_gh(1, "first"), _gh(2, "second", "CLOSED")]
        track = _track(name="platform-health", repo="o/r",
                       issues=[1, 2, 30, 40], body=_canon_body(existing))
        fetched = existing + [_gh(30, "third", "OPEN", ["bob"]),
                              _gh(40, "fourth", "CLOSED")]
        rc, mw, out = _drive(track, fetched, ["platform-health", "--yes"])

        self.assertEqual(rc, 0)
        mw.assert_called_once()
        new_body = mw.call_args[0][2]
        table = find_canonical_status_tables(new_body)[0]
        nums = [int(ISSUE_NUM_RE.search(r["cells"][0]).group(1))
                for r in table["rows"] if ISSUE_NUM_RE.search(r["cells"][0])]
        self.assertEqual(nums, [1, 2, 30, 40])
        # New 5-column form: # | Title | Milestone | Assignee | Status
        self.assertIn("| # | Title | Milestone | Assignee | Status |", new_body)
        self.assertIn("| #30 | third |  | @bob | 🔲 Open |", new_body)
        self.assertIn("| #40 | fourth |  | — | ✅ Shipped |", new_body)
        self.assertNotIn("All tracks in sync.", out)

    def test_no_drift_reports_in_sync(self):
        """A canonical block already identical to what render produces → no
        write, 'in sync'. Fixture built from the shared renderer round-trips."""
        ghs = [_gh(1, "first"), _gh(2, "second", "CLOSED")]
        track = _track(name="steady", repo="o/r", issues=[1, 2],
                       body=_canon_body(ghs))
        rc, mw, out = _drive(track, ghs, ["steady", "--yes"])
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        self.assertIn("All tracks in sync.", out)

    def test_status_change_is_rewritten(self):
        """An issue that closed since last refresh gets its status corrected."""
        ghs_old = [_gh(1, "first", "OPEN")]
        track = _track(name="t", repo="o/r", issues=[1], body=_canon_body(ghs_old))
        rc, mw, out = _drive(track, [_gh(1, "first", "CLOSED")], ["t", "--yes"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        self.assertIn("| #1 | first |  | — | ✅ Shipped |", mw.call_args[0][2])

    def test_rederive_orders_active_milestone_first(self):
        """Re-derive groups + orders issues active-milestone-first, even when
        the existing table was in plain numeric order."""
        # Existing table: numeric order, no milestone awareness.
        stale = [_gh(10, "near"), _gh(20, "far"), _gh(30, "someday")]
        track = _track(
            name="mixed", repo="o/r", issues=[10, 20, 30],
            body=_canon_body(stale), milestone_alignment="v2.0.0",
        )
        # Live data: #20 is the active milestone (v2.0.0), #10 is future, #30 none.
        fetched = [
            _gh(10, "near", milestone="v0.4.0 — MVP"),
            _gh(20, "far", milestone="v2.0.0 — Post-Launch"),
            _gh(30, "someday"),
        ]
        rc, mw, out = _drive(track, fetched, ["mixed", "--yes"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        new_body = mw.call_args[0][2]
        # Active milestone (v2.0.0 → #20) first, then v0.4.0 (#10), then none (#30).
        self.assertLess(new_body.index("#20"), new_body.index("#10"))
        self.assertLess(new_body.index("#10"), new_body.index("#30"))
        # Milestone column carries the compact label; a blank divider separates groups.
        self.assertIn("| #20 | far | v2.0.0 |", new_body)
        self.assertIn("| #10 | near | v0.4.0 |", new_body)
        self.assertIn("| | | | | |", new_body)

    def test_dropped_member_is_removed_and_reported(self):
        """A row in the old table but no longer in frontmatter is dropped on
        re-derive (frontmatter is membership truth) and the removal is reported
        in the pending summary — so a batch approver sees the deletion."""
        existing = [_gh(1, "first"), _gh(2, "second"), _gh(3, "third")]
        track = _track(name="t", repo="o/r", issues=[1, 2],  # #3 dropped from frontmatter
                       body=_canon_body(existing))
        rc, mw, out = _drive(track, [_gh(1, "first"), _gh(2, "second")],
                             ["t", "--yes"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        new_body = mw.call_args[0][2]
        self.assertNotIn("#3", new_body)
        self.assertIn("1 row(s) removed", out)

    def test_narrative_block_below_table_is_preserved(self):
        ghs = [_gh(1, "first")]
        track = _track(name="t", repo="o/r", issues=[1, 2],
                       body=_canon_body(ghs, trailing="## Notes\n\nkeep me\n"))
        rc, mw, out = _drive(track, [_gh(1, "first"), _gh(2, "second")], ["t", "--yes"])
        self.assertEqual(rc, 0)
        self.assertIn("## Notes\n\nkeep me", mw.call_args[0][2])


class PartialFetchTest(unittest.TestCase):
    """A degraded GitHub fetch must never overwrite valid rows with
    '(not fetched)'. The track is skipped, left untouched, and the run exits
    nonzero so --yes / hygiene callers see the degradation (#256)."""

    def test_partial_fetch_skips_track_and_preserves_rows(self):
        """One of several frontmatter issues missing → no write, rc=1, the
        existing table is left exactly as it was."""
        existing = [_gh(1, "first"), _gh(2, "second")]
        track = _track(name="t", repo="o/r", issues=[1, 2, 3],
                       body=_canon_body(existing + [_gh(3, "third")]))
        original_body = track.body
        # #3 fails to come back from the fetch.
        rc, mw, out = _drive(track, existing, ["t", "--yes"])
        self.assertEqual(rc, 1)
        mw.assert_not_called()
        self.assertEqual(track.body, original_body)
        self.assertNotIn("(not fetched)", out)
        self.assertIn("#3", out)
        self.assertNotIn("All tracks in sync.", out)

    def test_total_fetch_failure_skips_track(self):
        """Fetch returns nothing (GitHub unreachable) → track skipped, rc=1,
        no write, table untouched."""
        existing = [_gh(1, "first"), _gh(2, "second")]
        track = _track(name="t", repo="o/r", issues=[1, 2],
                       body=_canon_body(existing))
        rc, mw, out = _drive(track, [], ["t", "--yes"])
        self.assertEqual(rc, 1)
        mw.assert_not_called()
        self.assertIn("no issues", out)

    def test_healthy_track_still_refreshes_alongside_degraded(self):
        """In an --all batch, a complete-fetch track writes normally while a
        degraded track is skipped; the run still exits nonzero overall."""
        good_existing = [_gh(1, "first", "OPEN")]
        good = _track(name="good", repo="o/r", issues=[1],
                      body=_canon_body(good_existing))
        bad = _track(name="bad", repo="o/r", issues=[5, 6],
                     body=_canon_body([_gh(5, "fifth"), _gh(6, "sixth")]))

        # good: #1 fetched (and flipped to CLOSED so there's a write); bad: #6 missing.
        fetched = [_gh(1, "first", "CLOSED"), _gh(5, "fifth")]
        cfg = {"notes_root": "/tmp/fake"}
        with patch("commands.refresh_md.load_config", return_value=cfg), \
             patch("commands.refresh_md.discover_tracks", return_value=[good, bad]), \
             patch("commands.refresh_md.fetch_issues", return_value=fetched), \
             patch("commands.refresh_md.write_file") as mw:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = refresh_md.run(["--all", "--yes"])
        out = buf.getvalue()
        self.assertEqual(rc, 1)
        # Only the healthy track is written.
        self.assertEqual(mw.call_count, 1)
        written_path = mw.call_args[0][0]
        self.assertEqual(written_path.name, "good.md")
        self.assertIn("#6", out)  # degraded track's missing issue is reported

    def test_table_only_number_absent_from_frontmatter_does_not_gate(self):
        """A number that appears in the body table but NOT in frontmatter
        doesn't feed the rebuild, so a fetch miss on it is harmless — the track
        still refreshes (rc=0)."""
        # Frontmatter membership is [1, 2]; the body also references #99, which
        # is not in frontmatter. #99 is not fetched, but must not block.
        existing = [_gh(1, "first", "OPEN"), _gh(2, "second")]
        body = _canon_body(existing) + "\nSee also #99 for context.\n"
        track = _track(name="t", repo="o/r", issues=[1, 2], body=body)
        rc, mw, out = _drive(track, [_gh(1, "first", "CLOSED"), _gh(2, "second")],
                             ["t", "--yes"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        self.assertNotIn("(not fetched)", mw.call_args[0][2])


class NarrativeTableTest(unittest.TestCase):
    """Tracks with NO canonical marker keep the conservative in-place behavior."""

    def _narrative_body(self, rows):
        return (
            "## Issues\n\n"
            "| # | Title | Assignee | Status |\n"
            "|---|---|---|---|\n"
            + "\n".join(rows) + "\n"
        )

    def test_in_place_status_update_keeps_4col_shape(self):
        body = self._narrative_body(["| #1 | first | — | 🔲 Open |"])
        track = _track(name="n", repo="o/r", issues=[1], body=body)
        rc, mw, out = _drive(track, [_gh(1, "first", "CLOSED")], ["n", "--yes"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        new_body = mw.call_args[0][2]
        # Narrative tables are NOT migrated to 5 columns or reordered.
        self.assertIn("| #1 | first | — | ✅ Shipped |", new_body)
        self.assertNotIn("Milestone", new_body)

    def test_missing_row_appended_in_frontmatter_order(self):
        body = self._narrative_body(["| #1 | first | — | 🔲 Open |"])
        track = _track(name="n", repo="o/r", issues=[1, 5], body=body)
        rc, mw, out = _drive(track, [_gh(1, "first"), _gh(5, "fifth", "OPEN", ["x"])],
                             ["n", "--yes"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        self.assertIn("| #5 | fifth | @x | 🔲 Open |", mw.call_args[0][2])


if __name__ == "__main__":
    unittest.main()
