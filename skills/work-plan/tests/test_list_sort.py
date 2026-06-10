"""Tests for the `list --sort` flag (issue #181).

Covers:
- --sort=recent orders active tracks by last_touched descending.
- Tracks missing last_touched sort LAST under --sort=recent.
- --sort=priority orders P0→P3 with last_touched recency as tiebreaker;
  tracks missing launch_priority sort after those that have it.
- Default (no --sort) preserves discovery (filesystem) order exactly.
- --all still appends the archived section, and works alongside --sort.
- An invalid --sort value (or bare --sort) returns rc 2.
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

from commands import list_cmd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _track(name, *, repo="ok/repo", status="active", priority=None, last_touched=None):
    meta = {"track": name, "status": status}
    if priority is not None:
        meta["launch_priority"] = priority
    if last_touched is not None:
        meta["last_touched"] = last_touched
    return SimpleNamespace(
        name=name,
        path=Path(f"/tmp/fake/{name}.md"),
        body="# fake",
        meta=meta,
        has_frontmatter=True,
        needs_init=False,
        needs_filing=False,
        repo=repo,
    )


def _drive(args, tracks, archived=None):
    """Run list_cmd.run(args) with config + discovery mocked. Returns (rc, output)."""
    cfg = {"notes_root": "/tmp/fake-notes", "repos": {}}
    with patch("commands.list_cmd.load_config", return_value=cfg), \
         patch("commands.list_cmd.discover_tracks", return_value=tracks), \
         patch("commands.list_cmd.discover_archived_tracks", return_value=archived or []):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = list_cmd.run(args)
    return rc, buf.getvalue()


def _order(output, names):
    """Return the names from `names` in the order they appear in output."""
    positions = [(output.index(n), n) for n in names if n in output]
    return [n for _, n in sorted(positions)]


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class ListSortTest(unittest.TestCase):

    def test_sort_recent_orders_by_last_touched_desc(self):
        """--sort=recent orders tracks most-recently-touched first."""
        tracks = [
            _track("old", last_touched="2026-01-01"),
            _track("newest", last_touched="2026-06-01"),
            _track("middle", last_touched="2026-03-15"),
        ]
        rc, out = _drive(["--sort=recent"], tracks)
        self.assertEqual(rc, 0)
        self.assertEqual(_order(out, ["old", "newest", "middle"]),
                         ["newest", "middle", "old"])

    def test_sort_recent_missing_last_touched_sorts_last(self):
        """Tracks with no last_touched sort after those that have one."""
        tracks = [
            _track("nodate"),
            _track("dated", last_touched="2026-05-01"),
        ]
        rc, out = _drive(["--sort=recent"], tracks)
        self.assertEqual(rc, 0)
        self.assertEqual(_order(out, ["nodate", "dated"]), ["dated", "nodate"])

    def test_sort_priority_orders_p0_to_p3_with_recency_tiebreak(self):
        """--sort=priority orders P0→P3; equal priority breaks by recency."""
        tracks = [
            _track("p2", priority="P2", last_touched="2026-01-01"),
            _track("p0", priority="P0", last_touched="2026-01-01"),
            _track("p1_old", priority="P1", last_touched="2026-01-01"),
            _track("p1_new", priority="P1", last_touched="2026-06-01"),
        ]
        rc, out = _drive(["--sort=priority"], tracks)
        self.assertEqual(rc, 0)
        # P0 first, then P1 (newest of the two first), then P2
        self.assertEqual(
            _order(out, ["p0", "p1_new", "p1_old", "p2"]),
            ["p0", "p1_new", "p1_old", "p2"],
        )

    def test_sort_priority_missing_priority_sorts_after_known(self):
        """Tracks missing launch_priority sort after those that have it."""
        tracks = [
            _track("none"),
            _track("p3", priority="P3"),
            _track("p0", priority="P0"),
        ]
        rc, out = _drive(["--sort=priority"], tracks)
        self.assertEqual(rc, 0)
        self.assertEqual(_order(out, ["none", "p3", "p0"]), ["p0", "p3", "none"])

    def test_default_preserves_discovery_order(self):
        """No --sort flag preserves the exact filesystem discovery order."""
        tracks = [
            _track("zebra", priority="P3", last_touched="2026-01-01"),
            _track("alpha", priority="P0", last_touched="2026-06-01"),
            _track("mango", priority="P1", last_touched="2026-03-01"),
        ]
        rc, out = _drive([], tracks)
        self.assertEqual(rc, 0)
        # Discovery order is preserved despite priority/recency differences.
        self.assertEqual(_order(out, ["zebra", "alpha", "mango"]),
                         ["zebra", "alpha", "mango"])

    def test_all_appends_archived_section_with_sort(self):
        """--all still appends the Archived section alongside --sort."""
        tracks = [
            _track("recent_active", last_touched="2026-06-01"),
            _track("old_active", last_touched="2026-01-01"),
        ]
        archived = [_track("done_track", status="shipped")]
        rc, out = _drive(["--all", "--sort=recent"], tracks, archived=archived)
        self.assertEqual(rc, 0)
        self.assertIn("Archived:", out)
        self.assertIn("done_track", out)
        # Active section still recency-sorted, and archived comes after.
        self.assertLess(out.index("recent_active"), out.index("old_active"))
        self.assertLess(out.index("old_active"), out.index("Archived:"))

    def test_invalid_sort_value_returns_rc2(self):
        """An unrecognized --sort value returns rc 2 (usage error)."""
        rc, out = _drive(["--sort=bogus"], [_track("a")])
        self.assertEqual(rc, 2)
        self.assertIn("usage", out)

    def test_bare_sort_flag_returns_rc2(self):
        """--sort with no value returns rc 2."""
        rc, out = _drive(["--sort"], [_track("a")])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
