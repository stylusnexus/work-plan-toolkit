"""delete-track (offline; git mocked). Verifies the destructive-but-bounded
behavior AND the never-touch-GitHub guarantee."""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import delete_track
from lib.write_guard import make_token


def _t(name="ph", repo="o/r", path="/tmp/notes/proj/ph.md", tier="private"):
    return SimpleNamespace(name=name, repo=repo, path=Path(path), tier=tier,
                           folder="proj", has_frontmatter=True, meta={"status": "active"})


def _drive(args, track=None, vis="PRIVATE", tracked=True, git_rm_ok=True,
           archived=None):
    track = track or _t()
    with patch("commands.delete_track.load_config", return_value={"notes_root": "/tmp/notes"}), \
         patch("commands.delete_track.discover_tracks", return_value=[track]), \
         patch("commands.delete_track.discover_archived_tracks", return_value=archived or []), \
         patch("lib.write_guard.repo_visibility", return_value=vis), \
         patch("commands.delete_track.git_state.is_tracked", return_value=tracked), \
         patch("commands.delete_track.git_state.git_rm", return_value=git_rm_ok) as grm, \
         patch("pathlib.Path.unlink") as unlink:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = delete_track.run(args)
    return rc, grm, unlink, buf.getvalue()


class DeleteTrackTest(unittest.TestCase):
    def test_private_tracked_git_rm_and_undo_message(self):
        rc, grm, unlink, out = _drive(["ph"])
        self.assertEqual(rc, 0)
        grm.assert_called_once_with("ph.md", Path("/tmp/notes/proj"))
        unlink.assert_not_called()
        self.assertIn("deleted track", out)
        self.assertIn("GitHub issues are untouched", out)
        self.assertIn("Recoverable via notes-vcs", out)

    def test_shared_tracked_prints_commit_push(self):
        rc, grm, unlink, out = _drive(["ph"], track=_t(tier="shared"))
        self.assertEqual(rc, 0)
        grm.assert_called_once()
        self.assertIn("commit & push", out)

    def test_untracked_uses_filesystem_unlink_and_warns_permanent(self):
        # notes-vcs off (untracked) → unlink → the message must say PERMANENT,
        # NOT promise notes-vcs undo (the review's borderline-critical finding).
        rc, grm, unlink, out = _drive(["ph"], tracked=False)
        self.assertEqual(rc, 0)
        grm.assert_not_called()
        unlink.assert_called_once()
        self.assertIn("PERMANENT", out)
        self.assertNotIn("Recoverable via notes-vcs", out)

    def test_private_tracked_message_is_recoverable_not_permanent(self):
        # notes-vcs on (tracked) → git rm → recoverable, and NOT flagged permanent.
        rc, grm, unlink, out = _drive(["ph"], tracked=True)
        self.assertEqual(rc, 0)
        self.assertIn("Recoverable via notes-vcs", out)
        self.assertNotIn("PERMANENT", out)

    def test_git_rm_failure_returns_1(self):
        rc, grm, unlink, out = _drive(["ph"], git_rm_ok=False)
        self.assertEqual(rc, 1)

    def test_public_blocks_without_confirm(self):
        rc, grm, unlink, out = _drive(["ph"], vis="PUBLIC")
        self.assertEqual(rc, 0)
        grm.assert_not_called()
        unlink.assert_not_called()
        self.assertIn("needs_confirm", out)

    def test_public_with_confirm_deletes(self):
        tok = make_token("o/r", "ph")
        rc, grm, unlink, out = _drive(["ph", f"--confirm={tok}"], vis="PUBLIC")
        self.assertEqual(rc, 0)
        grm.assert_called_once()

    def test_not_found_returns_1(self):
        with patch("commands.delete_track.load_config", return_value={"notes_root": "/tmp"}), \
             patch("commands.delete_track.discover_tracks", return_value=[]), \
             patch("commands.delete_track.discover_archived_tracks", return_value=[]):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = delete_track.run(["nope"])
        self.assertEqual(rc, 1)

    def test_module_never_touches_github(self):
        """Guardrail: delete-track must not import a GitHub-mutating helper.
        The issues outlive the track (#330)."""
        src = (SKILL_ROOT / "commands" / "delete_track.py").read_text()
        self.assertNotIn("github_state", src)
        self.assertNotIn("gh issue", src)
        self.assertNotIn("subprocess", src)


if __name__ == "__main__":
    unittest.main()
