"""Pure archive helpers: destination path + shipped-row selection (offline)."""
import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib import reconcile_actions as ra


class ArchiveDestTest(unittest.TestCase):
    def test_default_kind_is_abandoned(self):
        self.assertEqual(
            ra.archive_dest("docs/plans/x.md"),
            "docs/plans/archive/abandoned/x.md",
        )

    def test_shipped_kind(self):
        self.assertEqual(
            ra.archive_dest("docs/plans/x.md", kind="shipped"),
            "docs/plans/archive/shipped/x.md",
        )

    def test_nested_dir_preserved(self):
        self.assertEqual(
            ra.archive_dest("docs/superpowers/specs/y-design.md", kind="shipped"),
            "docs/superpowers/specs/archive/shipped/y-design.md",
        )


class ShippedRowsTest(unittest.TestCase):
    ROWS = [
        {"rel": "a.md", "verdict": "shipped", "lie_gap": False},
        {"rel": "b.md", "verdict": "shipped", "lie_gap": True},   # lie-gap
        {"rel": "c.md", "verdict": "partial", "lie_gap": False},
        {"rel": "d.md", "verdict": "dead", "lie_gap": False},
    ]

    def test_excludes_lie_gap_by_default(self):
        rels = [r["rel"] for r in ra.shipped_rows(self.ROWS)]
        self.assertEqual(rels, ["a.md"])

    def test_includes_lie_gap_when_opted_in(self):
        rels = [r["rel"] for r in ra.shipped_rows(self.ROWS, include_lie_gap=True)]
        self.assertEqual(rels, ["a.md", "b.md"])


import tempfile
from unittest import mock
from lib import archive as archive_lib


class MoveToArchiveTest(unittest.TestCase):
    def _repo(self, d):
        root = Path(d)
        (root / "docs/plans").mkdir(parents=True)
        (root / "docs/plans/x.md").write_text("# x")
        return root

    def test_archived_calls_git_mv_to_shipped_dir(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            with mock.patch("lib.archive.git_state.git_mv", return_value=True) as mv:
                outcome = archive_lib.move_to_archive("docs/plans/x.md", root, "shipped")
            self.assertEqual(outcome, "archived")
            mv.assert_called_once_with(
                "docs/plans/x.md", "docs/plans/archive/shipped/x.md", root)

    def test_collision_skips_without_calling_git_mv(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            dest = root / "docs/plans/archive/shipped"
            dest.mkdir(parents=True)
            (dest / "x.md").write_text("# already here")
            with mock.patch("lib.archive.git_state.git_mv") as mv:
                outcome = archive_lib.move_to_archive("docs/plans/x.md", root, "shipped")
            self.assertEqual(outcome, "skipped_collision")
            mv.assert_not_called()

    def test_git_mv_failure_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            with mock.patch("lib.archive.git_state.git_mv", return_value=False):
                outcome = archive_lib.move_to_archive("docs/plans/x.md", root, "shipped")
            self.assertIsNone(outcome)


if __name__ == "__main__":
    unittest.main()
