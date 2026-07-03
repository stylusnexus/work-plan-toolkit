"""Pure archive helpers: destination path + shipped-row selection (offline)."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib import reconcile_actions as ra
from lib import archive as archive_lib


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


class MoveToArchiveTest(unittest.TestCase):
    def _repo(self, d):
        root = Path(d)
        (root / "docs/plans").mkdir(parents=True)
        (root / "docs/plans/x.md").write_text("# x")
        return root

    # ------------------------------------------------------------------
    # tracked path: branches through git_mv
    # ------------------------------------------------------------------

    def test_tracked_archived_calls_git_mv(self):
        """Tracked file: is_tracked=True -> git_mv called -> 'archived'."""
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            with mock.patch("lib.archive.git_state.is_tracked", return_value=True), \
                 mock.patch("lib.archive.git_state.git_mv", return_value=True) as mv:
                outcome = archive_lib.move_to_archive("docs/plans/x.md", root, "shipped")
            self.assertEqual(outcome, "archived")
            mv.assert_called_once_with(
                "docs/plans/x.md", "docs/plans/archive/shipped/x.md", root)

    def test_tracked_git_mv_failure_returns_none(self):
        """Tracked file where git_mv fails -> None (hard error)."""
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            with mock.patch("lib.archive.git_state.is_tracked", return_value=True), \
                 mock.patch("lib.archive.git_state.git_mv", return_value=False):
                outcome = archive_lib.move_to_archive("docs/plans/x.md", root, "shipped")
            self.assertIsNone(outcome)

    # ------------------------------------------------------------------
    # untracked/gitignored path: plain filesystem move
    # ------------------------------------------------------------------

    def test_untracked_archived_local_via_filesystem(self):
        """Untracked file: is_tracked=False -> shutil.move called -> 'archived_local'.

        The file must actually move on disk (src gone, dest exists)."""
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            with mock.patch("lib.archive.git_state.is_tracked", return_value=False), \
                 mock.patch("lib.archive.git_state.git_mv") as mv:
                outcome = archive_lib.move_to_archive("docs/plans/x.md", root, "shipped")
            self.assertEqual(outcome, "archived_local")
            mv.assert_not_called()
            # Source is gone; dest exists.
            self.assertFalse((root / "docs/plans/x.md").exists())
            self.assertTrue((root / "docs/plans/archive/shipped/x.md").exists())

    def test_untracked_oserror_returns_none(self):
        """Untracked file where shutil.move raises OSError -> None."""
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            with mock.patch("lib.archive.git_state.is_tracked", return_value=False), \
                 mock.patch("lib.archive.shutil.move",
                            side_effect=OSError("permission denied")):
                outcome = archive_lib.move_to_archive("docs/plans/x.md", root, "shipped")
            self.assertIsNone(outcome)

    # ------------------------------------------------------------------
    # collision: checked before tracking branch, git_mv never called
    # ------------------------------------------------------------------

    def test_collision_skips_without_any_move(self):
        """Destination already exists -> 'skipped_collision', no move attempted."""
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            dest = root / "docs/plans/archive/shipped"
            dest.mkdir(parents=True)
            (dest / "x.md").write_text("# already here")
            with mock.patch("lib.archive.git_state.is_tracked") as is_tracked, \
                 mock.patch("lib.archive.git_state.git_mv") as mv:
                outcome = archive_lib.move_to_archive("docs/plans/x.md", root, "shipped")
            self.assertEqual(outcome, "skipped_collision")
            is_tracked.assert_not_called()
            mv.assert_not_called()


class RestoreFromArchiveTest(unittest.TestCase):
    def _archived_repo(self, d):
        root = Path(d)
        (root / "docs/plans/archive/shipped").mkdir(parents=True)
        (root / "docs/plans/archive/shipped/x.md").write_text("# x")
        return root

    def test_tracked_restore_calls_git_mv_to_original_dir(self):
        """Tracked archived file → staged git mv back out → 'restored'."""
        with tempfile.TemporaryDirectory() as d:
            root = self._archived_repo(d)
            with mock.patch("lib.archive.git_state.is_tracked", return_value=True), \
                 mock.patch("lib.archive.git_state.git_mv", return_value=True) as mv:
                outcome = archive_lib.restore_from_archive(
                    "docs/plans/archive/shipped/x.md", root)
            self.assertEqual(outcome, "restored")
            mv.assert_called_once_with(
                "docs/plans/archive/shipped/x.md", "docs/plans/x.md", root)

    def test_untracked_restore_local_via_filesystem(self):
        """Untracked archived file → shutil.move back → 'restored_local'; moves on disk."""
        with tempfile.TemporaryDirectory() as d:
            root = self._archived_repo(d)
            with mock.patch("lib.archive.git_state.is_tracked", return_value=False), \
                 mock.patch("lib.archive.git_state.git_mv") as mv:
                outcome = archive_lib.restore_from_archive(
                    "docs/plans/archive/shipped/x.md", root)
            self.assertEqual(outcome, "restored_local")
            mv.assert_not_called()
            self.assertFalse((root / "docs/plans/archive/shipped/x.md").exists())
            self.assertTrue((root / "docs/plans/x.md").exists())

    def test_collision_refuses_when_live_doc_exists(self):
        """A live doc already at the destination → 'skipped_collision', no move."""
        with tempfile.TemporaryDirectory() as d:
            root = self._archived_repo(d)
            (root / "docs/plans/x.md").write_text("# live already")
            with mock.patch("lib.archive.git_state.is_tracked") as is_tracked, \
                 mock.patch("lib.archive.git_state.git_mv") as mv:
                outcome = archive_lib.restore_from_archive(
                    "docs/plans/archive/shipped/x.md", root)
            self.assertEqual(outcome, "skipped_collision")
            is_tracked.assert_not_called()
            mv.assert_not_called()

    def test_not_under_archive_returns_none(self):
        """A path not under archive/<kind>/ → None (nothing to restore)."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertIsNone(archive_lib.restore_from_archive("docs/plans/x.md", root))


if __name__ == "__main__":
    unittest.main()
