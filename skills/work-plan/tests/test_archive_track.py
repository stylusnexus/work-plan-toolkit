"""archive-track / unarchive-track commands (offline; move primitives mocked)."""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import archive_track, unarchive_track
from lib.write_guard import make_token


def _t(name="ph", repo="o/r", path="/tmp/notes/proj/ph.md", tier="private"):
    return SimpleNamespace(name=name, repo=repo, path=Path(path), tier=tier,
                           folder="proj", has_frontmatter=True, meta={"status": "active"})


class ArchiveTrackTest(unittest.TestCase):
    def _drive(self, args, track=None, outcome="archived", vis="PRIVATE"):
        track = track or _t()
        with patch("commands.archive_track.load_config", return_value={"notes_root": "/tmp/notes"}), \
             patch("commands.archive_track.discover_tracks", return_value=[track]), \
             patch("lib.write_guard.repo_visibility", return_value=vis), \
             patch("commands.archive_track.move_to_archive", return_value=outcome) as mv:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = archive_track.run(args)
        return rc, mv, buf.getvalue()

    def test_archives_private_track(self):
        rc, mv, out = self._drive(["ph"])
        self.assertEqual(rc, 0)
        mv.assert_called_once_with("ph.md", Path("/tmp/notes/proj"), "parked")
        self.assertIn("archived", out)

    def test_shared_track_prints_push_hint(self):
        rc, mv, out = self._drive(["ph"], track=_t(tier="shared"))
        self.assertEqual(rc, 0)
        self.assertIn("commit & push", out)

    def test_collision_is_reported_not_errored(self):
        rc, mv, out = self._drive(["ph"], outcome="skipped_collision")
        self.assertEqual(rc, 0)
        self.assertIn("already exists", out)

    def test_hard_failure_returns_1(self):
        rc, mv, out = self._drive(["ph"], outcome=None)
        self.assertEqual(rc, 1)

    def test_public_blocks_without_confirm(self):
        rc, mv, out = self._drive(["ph"], vis="PUBLIC")
        self.assertEqual(rc, 0)
        mv.assert_not_called()
        self.assertIn("needs_confirm", out)

    def test_public_with_confirm_archives(self):
        tok = make_token("o/r", "ph")
        rc, mv, out = self._drive(["ph", f"--confirm={tok}"], vis="PUBLIC")
        self.assertEqual(rc, 0)
        mv.assert_called_once()


class UnarchiveTrackTest(unittest.TestCase):
    def _drive(self, args, track=None, outcome="restored", vis="PRIVATE"):
        track = track or _t(path="/tmp/notes/proj/archive/parked/ph.md")
        with patch("commands.unarchive_track.load_config", return_value={"notes_root": "/tmp/notes"}), \
             patch("commands.unarchive_track.discover_archived_tracks", return_value=[track]), \
             patch("lib.write_guard.repo_visibility", return_value=vis), \
             patch("commands.unarchive_track.restore_from_archive", return_value=outcome) as rs:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = unarchive_track.run(args)
        return rc, rs, buf.getvalue()

    def test_restores_from_archive_with_correct_rel_and_base(self):
        rc, rs, out = self._drive(["ph"])
        self.assertEqual(rc, 0)
        rs.assert_called_once_with("archive/parked/ph.md", Path("/tmp/notes/proj"))
        self.assertIn("restored", out)

    def test_collision_reported(self):
        rc, rs, out = self._drive(["ph"], outcome="skipped_collision")
        self.assertEqual(rc, 0)
        self.assertIn("already exists", out)

    def test_not_found_returns_1(self):
        with patch("commands.unarchive_track.load_config", return_value={"notes_root": "/tmp/notes"}), \
             patch("commands.unarchive_track.discover_archived_tracks", return_value=[]):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = unarchive_track.run(["nope"])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
